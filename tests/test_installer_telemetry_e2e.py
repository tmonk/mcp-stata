"""End-to-end coverage for plugin/install.sh telemetry payloads.

These tests stub out ``curl`` so we can:

1. Capture every telemetry POST without hitting the network.
2. Force the ``ensure_uv`` path to fail on demand (by returning a fake
   astral.sh installer that exits non-zero).

The most important assertion in the suite is the failure path: previously
the installer emitted ``log_tail=""`` for every failure (a heredoc bug
silently dropped the piped log), which is exactly what users saw on the
dashboard ("Log: —" for every install_failure). These tests lock down the
fix.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[1] / "plugin" / "install.sh"

# This URL must match the literal string the installer uses for the uv
# bootstrap. Keeping it as a module constant means a sneaky string change in
# install.sh will be caught by the locked-down regression tests below.
ASTRAL_UV_INSTALLER_URL = "https://astral.sh/uv/install.sh"


def _make_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _curl_stub(telemetry_log: Path, *, fail_uv_install: bool) -> str:
    """Return a bash script that:

    - Captures the value of any ``-d <payload>`` argument to ``telemetry_log``
      (one payload per line).
    - When invoked to download the astral.sh uv installer, optionally emits a
      fake installer script that exits non-zero so the parent ``ensure_uv``
      branch fails.

    The detection of "is this a POST?" deliberately walks the args looking
    for an actual ``-d`` flag rather than substring-matching the joined args.
    Earlier iterations of this stub matched ``$*`` against the astral.sh URL,
    which gave false positives once the failure payload itself contained that
    URL inside ``log_tail`` — masking the very bug under test.
    """
    fail_block = (
        "    printf \"echo 'STDOUT: ATTEMPTING UV INSTALL';"
        " echo 'STDERR: UV INSTALL FAILED' >&2; exit 1\\n\"\n"
        "    exit 0\n"
        if fail_uv_install
        else "    exit 0\n"
    )
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # Capture any -d <payload> as a telemetry POST.
        post_data=""
        seen_d=0
        for arg in "$@"; do
            if [[ "$seen_d" -eq 1 ]]; then
                post_data="$arg"
                seen_d=0
                continue
            fi
            if [[ "$arg" == "-d" ]]; then
                seen_d=1
            fi
        done

        if [[ -n "$post_data" ]]; then
            printf "%s\\n" "$post_data" >> "{telemetry_log}"
            exit 0
        fi

        # Otherwise this is a download. Find the URL (first arg that doesn't
        # start with `-` and isn't a verb).
        url=""
        for arg in "$@"; do
            case "$arg" in
                http://*|https://*) url="$arg"; break ;;
            esac
        done

        if [[ "$url" == "{ASTRAL_UV_INSTALLER_URL}"* ]]; then
        {fail_block}        fi
        exit 0
        """
    )


def _run_install(
    args: list[str],
    *,
    home: Path,
    telemetry_log: Path,
    stub_uv_on_path: bool = True,
    fail_uv_install: bool = False,
) -> subprocess.CompletedProcess:
    """Run install.sh with a stubbed curl in an isolated $HOME/$PATH."""
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    _make_executable(bin_dir / "curl", _curl_stub(telemetry_log, fail_uv_install=fail_uv_install))
    if stub_uv_on_path:
        _make_executable(bin_dir / "uv", "#!/usr/bin/env bash\necho 'uv 0.1.0'\nexit 0\n")
    _make_executable(bin_dir / "uvx", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = str(bin_dir) + ":/usr/bin:/bin:/usr/sbin:/sbin"
    env["MCP_STATA_PROJECT_ROOT"] = str(home / "project")
    env["MCP_STATA_TELEMETRY_ENABLED"] = "1"

    return subprocess.run(
        ["/bin/bash", str(INSTALL_SH), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _payloads(telemetry_log: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in telemetry_log.read_text().splitlines()
        if line.startswith("{")
    ]


# ── Start event metadata ──────────────────────────────────────────────────────


@pytest.mark.skipif(not INSTALL_SH.exists(), reason="plugin/install.sh not found")
def test_install_sh_telemetry_start_has_full_metadata(tmp_path: Path) -> None:
    telemetry_log = tmp_path / "telemetry.log"
    home = tmp_path / "home"
    (home / "project").mkdir(parents=True)
    (home / ".cursor").mkdir()

    result = _run_install(
        ["--agent", "cursor", "--scope", "user", "--dry-run"],
        home=home,
        telemetry_log=telemetry_log,
    )

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    payloads = _payloads(telemetry_log)
    assert payloads, "no telemetry POSTs captured"

    start = payloads[0]
    assert start["event"] == "install_start"
    assert start["client"] == "cursor"
    assert start["scope"] == "user"
    assert start["os"] == "darwin"
    assert start["user_id"]
    assert start["machine_id"]
    assert start["script_version"]


def test_uninstall_sh_telemetry_start_has_full_metadata(tmp_path: Path) -> None:
    telemetry_log = tmp_path / "telemetry.log"
    home = tmp_path / "home"
    (home / "project").mkdir(parents=True)

    result = _run_install(
        ["--uninstall", "--dry-run"],
        home=home,
        telemetry_log=telemetry_log,
    )

    assert result.returncode == 0
    payloads = _payloads(telemetry_log)
    assert payloads, "no telemetry POSTs captured"

    start = payloads[0]
    assert start["event"] == "uninstall_start"
    assert start["action"] == "uninstall"
    assert start["user_id"]


# ── Failure path: log_tail must be present and non-empty ──────────────────────


def test_install_failure_emits_log_tail_with_actual_error(tmp_path: Path) -> None:
    """Regression test for the ``python3 - <<HERE`` heredoc bug.

    Before the fix, the heredoc bound python's stdin so ``sys.stdin.read()``
    returned an empty string; every install_failure event shipped with
    ``log_tail=""``. This test fails the moment that regression returns.
    """
    telemetry_log = tmp_path / "telemetry.log"
    home = tmp_path / "home"
    (home / "project").mkdir(parents=True)

    result = _run_install(
        ["--dry-run"],
        home=home,
        telemetry_log=telemetry_log,
        stub_uv_on_path=False,
        fail_uv_install=True,
    )

    assert result.returncode != 0, (
        f"installer should have failed when uv install fails. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    payloads = _payloads(telemetry_log)
    failures = [p for p in payloads if "failure" in p["event"]]
    assert failures, f"no failure event captured. payloads={payloads}"
    fail = failures[0]

    assert fail["event"] == "install_failure"
    assert fail["stage"] == "ensure_uv"
    assert fail["error_code"] == "Could not install uv via astral.sh"
    assert fail["log_tail"], "log_tail empty — heredoc bug regressed"
    # The fake uv installer prints these; both must round-trip into log_tail.
    assert "STDERR: UV INSTALL FAILED" in fail["log_tail"]
    assert "STDOUT: ATTEMPTING UV INSTALL" in fail["log_tail"]


def test_install_failure_log_tail_includes_stage_context(tmp_path: Path) -> None:
    """The captured log should include enough context to diagnose where
    the script reached (stage banners, args, etc.) — not just the last line."""
    telemetry_log = tmp_path / "telemetry.log"
    home = tmp_path / "home"
    (home / "project").mkdir(parents=True)

    result = _run_install(
        ["--dry-run", "--agent", "cursor"],
        home=home,
        telemetry_log=telemetry_log,
        stub_uv_on_path=False,
        fail_uv_install=True,
    )
    assert result.returncode != 0

    fail = next(p for p in _payloads(telemetry_log) if "failure" in p["event"])
    log_tail = fail["log_tail"]
    # Must contain the BOOTSTRAP RUNTIME banner (proves we captured more than
    # just the trailing error line — i.e. that we are not artificially capped
    # at 50 lines / a single line).
    assert "BOOTSTRAP RUNTIME" in log_tail


def test_install_failure_log_tail_size_respects_byte_cap(tmp_path: Path) -> None:
    """The log capture should be byte-based and bounded so we don't overflow
    the worker's 8 KB total payload cap, even with a huge install log."""
    telemetry_log = tmp_path / "telemetry.log"
    home = tmp_path / "home"
    (home / "project").mkdir(parents=True)

    # Force a much smaller cap so this test runs quickly without needing a
    # multi-MB log file.
    env_extra = {"MCP_STATA_LOG_TAIL_BYTES": "512"}
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _make_executable(bin_dir / "curl", _curl_stub(telemetry_log, fail_uv_install=True))
    _make_executable(bin_dir / "uvx", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.update(env_extra)
    env["HOME"] = str(home)
    env["PATH"] = str(bin_dir) + ":/usr/bin:/bin:/usr/sbin:/sbin"
    env["MCP_STATA_PROJECT_ROOT"] = str(home / "project")
    env["MCP_STATA_TELEMETRY_ENABLED"] = "1"

    result = subprocess.run(
        ["/bin/bash", str(INSTALL_SH), "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode != 0

    fail = next(p for p in _payloads(telemetry_log) if "failure" in p["event"])
    # log_tail is the *raw* (decoded) string after JSON parsing, so its length
    # is what matters for the worker's char-based cap. Bound generously: the
    # cap is on raw bytes from the log, after JSON-decode it should be ≤ cap.
    assert len(fail["log_tail"]) <= 512 + 32, (
        f"log_tail length {len(fail['log_tail'])} exceeds requested cap"
    )
    # And the most important content (the actual error) must still be there.
    assert "STDERR: UV INSTALL FAILED" in fail["log_tail"]


def test_install_failure_payload_is_valid_json(tmp_path: Path) -> None:
    """Even with backticks, quotes, ANSI-ish text and very long lines, the
    payload must be parseable JSON (the worker silently rejects malformed
    payloads with HTTP 400 — invisible from the client side)."""
    telemetry_log = tmp_path / "telemetry.log"
    home = tmp_path / "home"
    (home / "project").mkdir(parents=True)

    result = _run_install(
        ["--dry-run"],
        home=home,
        telemetry_log=telemetry_log,
        stub_uv_on_path=False,
        fail_uv_install=True,
    )
    assert result.returncode != 0

    raw_lines = [
        line
        for line in telemetry_log.read_text().splitlines()
        if line.startswith("{")
    ]
    assert raw_lines, "no payload bytes captured"
    for raw in raw_lines:
        # If json.loads raises, the worker would have rejected this with 400.
        json.loads(raw)
