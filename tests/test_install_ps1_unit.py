"""Static coverage for plugin/install.ps1 wrapper behavior.

These tests focus on PowerShell-wrapper features that are hard to execute in
this environment because ``pwsh`` is not guaranteed to be available. They
lock down the presence of the same wrapper-level behaviors we rely on in the
shell installer:

- ``--verbose`` toggles raw passthrough of toolkit output
- full raw logs are always captured via ``MCP_STATA_INSTALL_LOG_FILE``
- the Python installer is always delegated to
"""

from __future__ import annotations

from pathlib import Path


INSTALL_PS1 = Path(__file__).resolve().parents[1] / "plugin" / "install.ps1"


def _script_text() -> str:
    return INSTALL_PS1.read_text()


def test_install_ps1_exists() -> None:
    assert INSTALL_PS1.exists()


def test_install_ps1_tracks_verbose_flag() -> None:
    text = _script_text()
    assert "$VerboseMode = $PassthroughArgs -contains '--verbose'" in text


def test_install_ps1_exports_log_path_for_python_installer() -> None:
    text = _script_text()
    assert "$env:MCP_STATA_INSTALL_LOG_FILE = $LogFile" in text


def test_install_ps1_verbose_mode_streams_raw_toolkit_output() -> None:
    text = _script_text()
    assert "if ($VerboseMode) {" in text
    assert "& uv run --no-progress --python 3.11 $pythonInstaller @Arguments" in text


def test_install_ps1_non_verbose_mode_formats_toolkit_output() -> None:
    text = _script_text()
    assert "$output = & uv run --no-progress --python 3.11 $pythonInstaller @Arguments 2>&1" in text
    assert "Format-ToolkitLine ([string]$line)" in text


def test_install_ps1_starts_transcript_for_bug_logs() -> None:
    text = _script_text()
    assert "Start-Transcript -Path $LogFile -Append -ErrorAction SilentlyContinue | Out-Null" in text
    assert "Stop-Transcript -ErrorAction SilentlyContinue | Out-Null" in text
