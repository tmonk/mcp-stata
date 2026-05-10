import os
import subprocess
import textwrap
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

INSTALL_PS1 = Path(__file__).resolve().parents[2] / "plugin" / "install.ps1"

pytestmark = pytest.mark.skipif(os.name != "nt", reason="install.ps1 is for Windows only")

@pytest.fixture
def test_env_ps1(tmp_path):
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
    
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
    env["MCP_STATA_TELEMETRY_ENABLED"] = "0"
    env["MCP_STATA_DRY_RUN"] = "1"
    
    return SimpleNamespace(home=home, env=env)

def test_install_ps1_bootstrap_delegation(test_env_ps1):
    # Mock the repo root
    repo_root = test_env_ps1.home / "repo"
    repo_root.mkdir()
    (repo_root / "scripts" / "install").mkdir(parents=True)
    setup_py = repo_root / "scripts" / "install" / "setup_toolkit.py"
    setup_py.write_text("print('STUB TOOLKIT')")
    
    # In PS1, we need to bypass execution policy if it was Windows, 
    # but on Unix it's usually not an issue. We'll use -File.
    result = subprocess.run(
        ["pwsh", "-File", str(INSTALL_PS1), "--agent", "cursor"],
        capture_output=True,
        text=True,
        env={**test_env_ps1.env, "MCP_STATA_PROJECT_ROOT": str(repo_root)}
    )
    
    assert result.returncode == 0
    assert "UV RUN" in result.stdout
    assert "setup_toolkit.py" in result.stdout
    assert "--agent cursor" in result.stdout

def test_install_ps1_failure_path(test_env_ps1):
    repo_root = test_env_ps1.home / "repo"
    repo_root.mkdir()
    (repo_root / "scripts" / "install").mkdir(parents=True)
    setup_py = repo_root / "scripts" / "install" / "setup_toolkit.py"
    setup_py.write_text("print('STUB TOOLKIT')")
    
    # Make uv run fail
    uv_path = Path(test_env_ps1.env["PATH"].split(":")[0]) / "uv"
    uv_path.write_text("#!/usr/bin/env bash\nexit 1")
    
    result = subprocess.run(
        ["pwsh", "-File", str(INSTALL_PS1), "--dry-run"],
        capture_output=True,
        text=True,
        env={**test_env_ps1.env, "MCP_STATA_PROJECT_ROOT": str(repo_root)}
    )
    
    assert result.returncode != 0
    assert "FAILED: INSTALLATION COULD NOT BE COMPLETED" in result.stdout
