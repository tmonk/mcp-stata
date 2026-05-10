import os
import subprocess
import textwrap
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

INSTALL_SH = Path(__file__).resolve().parents[2] / "plugin" / "install.sh"

@pytest.fixture
def test_env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = home / "bin"
    bin_dir.mkdir()
    
    # Mock uv
    uv_path = bin_dir / "uv"
    uv_path.write_text("#!/usr/bin/env bash\n"
                       "if [[ \"$*\" == *\"--version\"* ]]; then echo \"uv 0.1.0\"; exit 0; fi\n"
                       "echo \"UV RUN: $@\"\n"
                       "exit 0")
    uv_path.chmod(0o755)
    
    # Mock curl for telemetry and source download
    telemetry_log = tmp_path / "telemetry.log"
    curl_path = bin_dir / "curl"
    curl_path.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Capture telemetry
        if [[ "$*" == *"-d"* ]]; then
            # Extract payload from -d
            payload=""
            seen_d=0
            for arg in "$@"; do
                if [[ "$seen_d" -eq 1 ]]; then payload="$arg"; break; fi
                if [[ "$arg" == "-d" ]]; then seen_d=1; fi
            done
            echo "$payload" >> "{telemetry_log}"
            exit 0
        fi
        # Handle source download (mock tarball)
        if [[ "$*" == *"github.com"* ]]; then
            exit 0
        fi
        exit 0
    """))
    curl_path.chmod(0o755)
    
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["MCP_STATA_TELEMETRY_ENABLED"] = "1"
    env["MCP_STATA_DRY_RUN"] = "1"
    
    return SimpleNamespace(home=home, telemetry_log=telemetry_log, env=env)

def test_install_sh_bootstrap_delegation(test_env):
    # Mock the repo root so it doesn't try to download
    repo_root = test_env.home / "repo"
    repo_root.mkdir()
    (repo_root / "scripts" / "install").mkdir(parents=True)
    setup_py = repo_root / "scripts" / "install" / "setup_toolkit.py"
    setup_py.write_text("print('STUB TOOLKIT')")
    
    result = subprocess.run(
        ["/bin/bash", str(INSTALL_SH), "--agent", "cursor"],
        capture_output=True,
        text=True,
        env={**test_env.env, "MCP_STATA_PROJECT_ROOT": str(repo_root)}
    )
    
    assert result.returncode == 0
    assert "UV RUN" in result.stdout
    assert "setup_toolkit.py" in result.stdout
    assert "--agent cursor" in result.stdout

def test_install_sh_telemetry_flow(test_env):
    repo_root = test_env.home / "repo"
    repo_root.mkdir()
    (repo_root / "scripts" / "install").mkdir(parents=True)
    setup_py = repo_root / "scripts" / "install" / "setup_toolkit.py"
    setup_py.write_text("print('STUB TOOLKIT')")
    
    result = subprocess.run(
        ["/bin/bash", str(INSTALL_SH), "--dry-run"],
        capture_output=True,
        text=True,
        env={**test_env.env, "MCP_STATA_PROJECT_ROOT": str(repo_root)}
    )
    
    assert result.returncode == 0
    
    payloads = [json.loads(line) for line in test_env.telemetry_log.read_text().splitlines()]
    assert any(p["event"] == "install_start" for p in payloads)
    assert any(p["event"] == "install_success" for p in payloads)

def test_install_sh_failure_telemetry(test_env):
    repo_root = test_env.home / "repo"
    repo_root.mkdir()
    (repo_root / "scripts" / "install").mkdir(parents=True)
    setup_py = repo_root / "scripts" / "install" / "setup_toolkit.py"
    setup_py.write_text("print('STUB TOOLKIT')")
    
    # Make uv run fail
    uv_path = Path(test_env.env["PATH"].split(":")[0]) / "uv"
    uv_path.write_text("#!/usr/bin/env bash\nexit 1")
    
    result = subprocess.run(
        ["/bin/bash", str(INSTALL_SH), "--dry-run"],
        capture_output=True,
        text=True,
        env={**test_env.env, "MCP_STATA_PROJECT_ROOT": str(repo_root)}
    )
    
    assert result.returncode != 0
    
    payloads = [json.loads(line) for line in test_env.telemetry_log.read_text().splitlines()]
    assert any(p["event"] == "install_start" for p in payloads)
    assert any(p["event"] == "install_failure" for p in payloads)
    
    failure = next(p for p in payloads if p["event"] == "install_failure")
    assert failure["error_code"] == "Python installer failed"
    assert "BOOTSTRAP SOURCE" in failure["log_tail"]
