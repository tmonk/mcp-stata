from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[1] / "plugin" / "install.sh"

def _make_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path

def _run_with_telemetry_stub(
    args: list[str],
    *,
    home: Path,
    telemetry_log: Path,
) -> subprocess.CompletedProcess:
    """Run install.sh with a stubbed curl that logs telemetry payloads to a file."""
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    
    # Stub curl to log POST data
    curl_stub = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        while [[ "$#" -gt 0 ]]; do
            if [[ "$1" == "-d" ]]; then
                echo "$2" >> "{telemetry_log}"
                shift 2
            else
                shift
            fi
        done
        exit 0
    """)
    _make_executable(bin_dir / "curl", curl_stub)
    
    # Stub uvx so the script doesn't fail on discovery
    _make_executable(bin_dir / "uvx", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = str(bin_dir) + ":" + env.get("PATH", "")
    env["MCP_STATA_PROJECT_ROOT"] = str(home / "project")
    # We want to make sure it doesn't try to use real network
    env["MCP_STATA_TELEMETRY_ENABLED"] = "1"
    
    return subprocess.run(
        ["/bin/bash", str(INSTALL_SH)] + args,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

@pytest.mark.skipif(not INSTALL_SH.exists(), reason="plugin/install.sh not found")
def test_install_sh_telemetry_start_has_full_metadata(tmp_path):
    telemetry_log = tmp_path / "telemetry.log"
    home = tmp_path / "home"
    (home / "project").mkdir(parents=True)
    
    # Create a fake .cursor dir so it detects something to do
    (home / ".cursor").mkdir()

    result = _run_with_telemetry_stub(
        ["--agent", "cursor", "--scope", "user", "--dry-run"],
        home=home,
        telemetry_log=telemetry_log
    )
    
    assert result.returncode == 0
    
    if not telemetry_log.exists():
        pytest.fail(f"Telemetry log not created. Output: {result.stdout}\n{result.stderr}")
        
    payloads = [json.loads(line) for line in telemetry_log.read_text().splitlines() if line.strip()]
    
    assert len(payloads) >= 1
    start_payload = payloads[0]
    
    assert start_payload["event"] == "install_start"
    assert start_payload["client"] == "cursor"
    assert start_payload["scope"] == "user"
    assert start_payload["os"] == "darwin"  # Since we're running on Mac
    assert "user_id" in start_payload
    assert "machine_id" in start_payload
    assert "script_version" in start_payload
    assert start_payload["user_id"] != ""
    assert start_payload["machine_id"] != ""

def test_uninstall_sh_telemetry_start_has_full_metadata(tmp_path):
    telemetry_log = tmp_path / "telemetry.log"
    home = tmp_path / "home"
    (home / "project").mkdir(parents=True)
    
    result = _run_with_telemetry_stub(
        ["--uninstall", "--dry-run"],
        home=home,
        telemetry_log=telemetry_log
    )
    
    assert result.returncode == 0
    
    payloads = [json.loads(line) for line in telemetry_log.read_text().splitlines() if line.strip()]
    
    assert len(payloads) >= 1
    start_payload = payloads[0]
    
    assert start_payload["event"] == "uninstall_start"
    assert start_payload["action"] == "uninstall"
    assert "user_id" in start_payload
