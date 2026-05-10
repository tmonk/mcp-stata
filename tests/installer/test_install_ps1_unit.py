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


INSTALL_PS1 = Path(__file__).resolve().parents[2] / "plugin" / "install.ps1"


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
    assert "& uv run --no-project --no-progress --python 3.11 \"$pythonInstaller\" @Arguments" in text


def test_install_ps1_non_verbose_mode_formats_toolkit_output() -> None:
    text = _script_text()
    assert "$output = & uv run --no-project --no-progress --python 3.11 \"$pythonInstaller\" @Arguments 2>&1" in text
    assert "Format-ToolkitLine ([string]$line)" in text


def test_install_ps1_contains_telemetry_endpoint() -> None:
    text = _script_text()
    assert "$TelemetryUrl = \"https://${InstallHost}/telemetry\"" in text

def test_install_ps1_contains_fallback_urls() -> None:
    text = _script_text()
    assert "$InstallFallbackSh = \"${GithubRawUrl}/install.sh\"" in text
    assert "$InstallFallbackPs1 = \"${GithubRawUrl}/install.ps1\"" in text

def test_install_ps1_contains_dynamic_config_block() -> None:
    text = _script_text()
    assert "Invoke-RestMethod -Uri \"${GithubRawUrl}/installer.json\"" in text
    assert "$InstallHost = $dynamicConfig.urls.primary.base.Replace('https://', '')" in text

def test_install_ps1_implements_send_telemetry() -> None:
    text = _script_text()
    assert "function Send-Telemetry" in text
    assert "Invoke-RestMethod -Uri $TelemetryUrl -Method Post" in text

def test_install_ps1_enforces_runner_mcp_username() -> None:
    text = _script_text()
    assert "if ($env:MCP_STATA_TELEMETRY_USERNAME) {" in text
    assert "elseif ($env:GITHUB_ACTIONS -eq 'true') {" in text
    assert "$telemetryUser = 'runner-mcp'" in text
def test_install_ps1_sends_telemetry_early() -> None:
    text = _script_text()
    # Check that Send-Telemetry is called early in the entry point
    assert "$script:UserId = Get-UserId" in text
    assert "$startEvent = if ($PassthroughArgs -contains '--uninstall') { 'uninstall_start' } else { 'install_start' }" in text
    assert "Send-Telemetry $startEvent" in text

    # Check the ordering: UserId must be set before Send-Telemetry
    user_id_pos = text.find("$script:UserId = Get-UserId")
    telemetry_pos = text.find("Send-Telemetry $startEvent")
    assert user_id_pos != -1
    assert telemetry_pos != -1
    assert user_id_pos < telemetry_pos

def test_install_ps1_flushes_transcript_on_failure() -> None:
    """Without flushing the PowerShell transcript, ``Get-Content $LogFile``
    inside ``Send-Telemetry`` returns nothing or stale content — which is
    exactly what produced the empty Log column for failure events on the
    dashboard. ``Stop-Transcript`` must fire **before** the failure
    telemetry POST so the file on disk is current."""
    text = _script_text()
    assert "} catch {" in text
    assert "Stop-Transcript -ErrorAction SilentlyContinue" in text
    # Check that Stop-Transcript happens before Send-Telemetry in the catch block
    catch_pos = text.find("} catch {")
    stop_transcript_pos = text.find("Stop-Transcript -ErrorAction SilentlyContinue", catch_pos)
    telemetry_pos = text.find("Send-Telemetry $failEvent", catch_pos)
    assert catch_pos != -1
    assert stop_transcript_pos != -1
    assert telemetry_pos != -1
    assert stop_transcript_pos < telemetry_pos


def test_install_ps1_log_tail_is_byte_based_not_line_based() -> None:
    """Like install.sh, install.ps1 should slice the log by characters/bytes
    rather than lines so a single very long line doesn't collapse the
    capture to a useless prefix."""
    text = _script_text()
    # Locate the failure-block where logTail is populated.
    block_start = text.find("if ($Event -like '*failure*'")
    assert block_start != -1, "log_tail capture block not found"
    block_end = text.find("}\n", block_start + 1)
    block = text[block_start:block_end + 200]
    assert "-Tail 100" not in block, (
        "regression: install.ps1 must not use line-based -Tail capture; the "
        "worker caps log_tail by characters, and a long single-line traceback "
        "would collapse the capture to near-nothing."
    )
    # Must use Get-Content -Raw + Substring slicing, OR an equivalent byte-based read.
    assert ("-Raw" in block and "Substring" in block) or ".Read(" in block, (
        "log_tail capture should slice the raw file content by character/byte "
        "count, not by line count."
    )


def test_install_ps1_log_tail_size_is_configurable_via_env() -> None:
    text = _script_text()
    assert "MCP_STATA_LOG_TAIL_BYTES" in text


def test_install_ps1_log_tail_default_fits_worker_cap() -> None:
    """Default capture must comfortably fit the worker's 4000-char log_tail
    cap (server-side enforcement) and 8 KB total payload cap."""
    import re

    text = _script_text()
    match = re.search(r"\$TelemetryLogTailBytes\s*=\s*if[^{]*{[^}]*}\s*else\s*{\s*(\d+)\s*}", text)
    assert match, "default log_tail byte cap not found in install.ps1"
    default_bytes = int(match.group(1))
    assert 1024 <= default_bytes <= 4096, (
        f"default log_tail byte cap ({default_bytes}) outside expected range. "
        "Too small → loses diagnostic info. Too large → worker rejects."
    )

def test_install_ps1_boxed_titles_present() -> None:
    text = _script_text()
    assert "Write-BoxedTitle -Title 'MCP-STATA IS LIVE' -Color Green" in text
    assert "Write-BoxedTitle -Title \"FAILED: $($ActionLabel.ToUpper()) COULD NOT BE COMPLETED\" -Color Red" in text
