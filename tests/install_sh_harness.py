"""Shared stubs for plugin/install.sh tests (uv, curl) — keep subprocess runs fast."""

from __future__ import annotations

import shlex
import stat
import sys
import textwrap
from pathlib import Path


def make_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def install_curl_noop_stub(bin_dir: Path) -> Path:
    """install.sh curls installer.json at parse time; avoid real network."""
    return make_executable(bin_dir / "curl", "#!/usr/bin/env bash\nexit 0\n")


def install_uv_run_stub(
    bin_dir: Path,
    *,
    python_executable: str | None = None,
    echo_uv_run_line: bool = False,
) -> Path:
    """
    Replace real ``uv``: ``uv run --python 3.11 … setup_toolkit.py`` delegates to
    ``sys.executable`` so tests do not provision CPython 3.11 via uv on every call.
    """
    quoted_py = shlex.quote(python_executable or sys.executable)
    echo_lines = ""
    if echo_uv_run_line:
        echo_lines = '          printf "UV RUN: %s\\n" "$*"\n'
    content = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        if [[ "${{1:-}}" == "--version" ]]; then
          echo "uv 0.5.0 (mcp-stata install.sh test stub)"
          exit 0
        fi
        if [[ "${{1:-}}" == "run" ]]; then
          shift
          while [[ $# -gt 0 ]]; do
            case "$1" in
              --no-project|--no-progress) shift ;;
              --python) shift 2 ;;
              *) break ;;
            esac
          done
        {echo_lines}          exec {quoted_py} "$@"
        fi
        echo "install.sh test stub: unsupported uv invocation: $*" >&2
        exit 1
        """
    )
    return make_executable(bin_dir / "uv", content)
