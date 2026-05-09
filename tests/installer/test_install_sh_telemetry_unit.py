"""Unit-level coverage for the telemetry helpers in plugin/install.sh.

These tests source the installer in non-execute mode and exercise individual
shell functions (``json_escape``, ``json_escape_stream``) directly. They
complement the end-to-end test in ``test_installer_telemetry_e2e.py`` which
runs the full installer flow.

Two long-standing failure modes that these tests guard against:

1. ``python3 - <<'PY' …`` heredoc: silently makes ``sys.stdin.read()`` return
   '' because the heredoc binds python's stdin instead of the upstream pipe.
   Every install_failure since this code shipped in 3.1.x had ``log_tail=""``
   for this reason.
2. Line-based ``tail -n N`` capture: the worker caps at 4000 chars of
   ``log_tail``, but a single very long line (e.g. uv installer dumping a
   stack trace) collapses N=50 into a few hundred chars of useless prefix.
   Byte-based capture (``tail -c …``) is what we want.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[2] / "plugin" / "install.sh"
pytestmark = pytest.mark.skipif(
    not INSTALL_SH.exists(),
    reason="plugin/install.sh not found",
)


def _script_text() -> str:
    return INSTALL_SH.read_text()


def _source_and_run(snippet: str, *, env_extra: dict | None = None, tmp_path: Path | None = None) -> subprocess.CompletedProcess:
    """Source install.sh as a library (no main()) and run a snippet against
    its functions.

    We strip the trailing ``main "$@"`` invocation so sourcing leaves all
    helpers defined without running the installer flow.
    """
    body = INSTALL_SH.read_text()
    # Remove the final 'main "$@"' invocation. The script ends with a single
    # such line followed (optionally) by a blank line.
    library_body = body.rsplit('\nmain "$@"', 1)[0]
    if tmp_path is None:
        # Use a per-test temp file name based on snippet hash.
        import hashlib
        h = hashlib.md5(snippet.encode()).hexdigest()[:8]
        lib_file = Path(os.environ.get("TMPDIR", "/tmp")) / f"install_sh_lib_{h}.sh"
    else:
        lib_file = tmp_path / "install_lib.sh"
    lib_file.write_text(library_body)
    wrapper = textwrap.dedent(
        f"""\
        source "{lib_file}"
        {snippet}
        """
    )
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["/bin/bash", "-c", wrapper],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


# ── Static lock-down: regression tests for the heredoc bug ────────────────────


def test_no_heredoc_stdin_capture_for_log_tail() -> None:
    """``python3 - <<'PY' … PY`` makes the heredoc python's stdin and silently
    drops piped input. We must not use this pattern for log capture.
    """
    text = _script_text()
    # The bad pattern: heredoc on python3 with a pipe feeding it.
    # If anyone re-introduces this for log_tail capture, fail loudly.
    assert "python3 - <<'PY'" not in text or "log_tail" not in text.split("python3 - <<'PY'")[0].splitlines()[-1], (
        "regression: log_tail capture must not use a heredoc — that binds "
        "python's stdin to the heredoc and drops the piped log content."
    )


def test_log_tail_capture_uses_pipe_friendly_python_invocation() -> None:
    """The capture must be a ``python3 -c '…'`` (or fallback) invocation that
    reads its stdin from the upstream pipe."""
    text = _script_text()
    # Either python3 -c is used directly, or json_escape_stream is invoked.
    assert "python3 -c 'import json, sys; sys.stdout.write(json.dumps(sys.stdin.read())[1:-1])'" in text


def test_log_tail_capture_is_byte_based_not_line_based() -> None:
    """We capture ``tail -c …`` so the worker's char-cap is reached, not
    ``tail -n …`` which can collapse to a near-empty string when the log
    has long single-line tracebacks."""
    text = _script_text()
    assert "tail -c" in text, "log_tail capture should be byte-based (tail -c)"
    # A historical regression placed `tail -n 50` here. Lock against it.
    failure_block = text.split("if [[ \"$event\" == *\"failure\"* ]]", 1)[1].split("fi\n", 1)[0]
    assert "tail -n" not in failure_block, (
        "log_tail capture must not use line-based tail; the worker caps by "
        "chars, and a single long line could collapse the capture."
    )


def test_log_tail_size_is_configurable_via_env() -> None:
    """Operators should be able to dial down ``log_tail`` size via env var
    (useful for emergency mitigation if the worker tightens its caps)."""
    text = _script_text()
    assert "MCP_STATA_LOG_TAIL_BYTES" in text


def test_log_tail_size_default_fits_worker_cap() -> None:
    """Default capture must comfortably fit the worker's 4000-char log_tail
    cap and 8 KB total payload cap, even after JSON escaping."""
    text = _script_text()
    # Search for `${MCP_STATA_LOG_TAIL_BYTES:-NNNN}` and assert NNNN <= 4096.
    import re

    match = re.search(r"MCP_STATA_LOG_TAIL_BYTES:-(\d+)", text)
    assert match, "default log_tail byte cap not found"
    default_bytes = int(match.group(1))
    assert 1024 <= default_bytes <= 4096, (
        f"default log_tail byte cap ({default_bytes}) outside expected range. "
        "Too small → loses diagnostic info. Too large → worker rejects."
    )


# ── json_escape behaviour (python path) ───────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected_substring"),
    [
        ("hello", "hello"),
        ('with "quotes"', '\\"quotes\\"'),
        ("with\nnewline", "\\n"),
        ("with\ttab", "\\t"),
        ("with `backtick`", "`backtick`"),  # backticks unchanged
        ("with \\backslash", "\\\\backslash"),
    ],
)
def test_json_escape_python_path(raw: str, expected_substring: str) -> None:
    """``json_escape`` must produce JSON-string-safe output that round-trips
    when wrapped in quotes and parsed.

    We pass the raw input via an env var to avoid bash-quoting mishaps when
    the value contains newlines, tabs, or backslashes.
    """
    snippet = 'json_escape "$RAW"'
    result = _source_and_run(snippet, env_extra={"RAW": raw})
    assert result.returncode == 0, result.stderr
    escaped = result.stdout
    # Wrap and parse — must be a valid JSON string that decodes back to raw.
    decoded = json.loads(f'"{escaped}"')
    assert decoded == raw
    assert expected_substring in escaped


def test_json_escape_handles_full_install_log_excerpt() -> None:
    """Realistic excerpt: ASCII-art banner with backticks + multi-line + tabs."""
    raw = (
        "======================================================================\n"
        "                                    __        __\n"
        "   ____ ___  _________        _____/ /_____ _/ /_____ _\n"
        "  / __ `__ \\/ ___/ __ \\______/ ___/ __/ __ `/ __/ __ `/\n"
        "STDERR: UV INSTALL FAILED\n"
    )
    # We can't easily pass this as an arg without escaping issues, so we
    # write it to a file and read+escape via the streaming helper.
    snippet = textwrap.dedent(
        """
        printf '%s' "$RAW" | json_escape_stream
        """
    )
    result = _source_and_run(snippet, env_extra={"RAW": raw})
    assert result.returncode == 0, result.stderr
    decoded = json.loads(f'"{result.stdout}"')
    assert decoded == raw
    assert "STDERR: UV INSTALL FAILED" in decoded


# ── json_escape_stream awk fallback (python3 missing) ─────────────────────────


def test_json_escape_stream_awk_fallback_handles_basic_chars() -> None:
    """When python3 is not on PATH, the awk fallback must still produce JSON
    output that the worker accepts (round-trips, no embedded literal newlines).
    """
    # Stub PATH to exclude python3 by routing through a dir without it.
    # We do this by setting PATH to a single dir containing only awk/bash/tail.
    snippet = textwrap.dedent(
        """
        # Simulate "python3 not available" by overriding command -v.
        command() {
            if [[ "$1" == "-v" && "$2" == "python3" ]]; then
                return 1
            fi
            builtin command "$@"
        }
        printf 'line1\\nline2\\twith tab\\n"quoted"\\n' | json_escape_stream
        """
    )
    result = _source_and_run(snippet)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    # Must parse as JSON and round-trip.
    decoded = json.loads(f'"{out}"')
    assert "line1" in decoded
    assert "line2" in decoded
    assert "with tab" in decoded
    assert '"quoted"' in decoded
    # No literal embedded newlines (would break JSON).
    assert "\n" not in out, f"awk fallback emitted literal newline: {out!r}"
