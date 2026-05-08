import pytest
import os
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

# Since we're in the repo, we can import directly
repo_root = Path(__file__).parent.parent
sys.path.append(str(repo_root / "scripts" / "install"))

import setup_toolkit

@pytest.fixture
def mock_home(tmp_path):
    # Clear env vars that might override Path.home() based logic
    env_patch = {
        "XDG_CONFIG_HOME": str(tmp_path / ".config"),
        "APPDATA": str(tmp_path / "AppData/Roaming"),
        "USERPROFILE": str(tmp_path),
        "HOME": str(tmp_path)
    }
    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.dict(os.environ, env_patch):
        yield tmp_path

def test_configure_editor_mcp(mock_home):
    # Get platform-specific paths
    vscode_path = setup_toolkit.get_mcp_config_path("vscode", scope="user")
    claude_path = setup_toolkit.get_mcp_config_path("claude_desktop", scope="user")
    
    # Run configuration
    setup_toolkit.configure_editor_mcp("vscode", scope="user")
    setup_toolkit.configure_claude_desktop()
    
    assert vscode_path.exists()
    assert claude_path.exists()
    
    with open(claude_path, "r") as f:
        config = json.load(f)
    assert "mcp-stata" in config["mcpServers"]

def test_configure_codex(mock_home):
    codex_path = mock_home / ".codex/config.toml"
    
    setup_toolkit.configure_codex(scope="user")
    
    assert codex_path.exists()
    with open(codex_path, "r") as f:
        content = f.read()
    assert "[mcp_servers.mcp-stata]" in content
    assert 'command = "uvx"' in content

def test_configure_editor_mcp_existing(mock_home):
    vscode_path = setup_toolkit.get_mcp_config_path("vscode", scope="user")
    vscode_path.parent.mkdir(parents=True, exist_ok=True)
    
    existing_config = {"servers": {"other_server": {"command": "echo"}}}
    with open(vscode_path, "w") as f:
        json.dump(existing_config, f)
        
    setup_toolkit.configure_editor_mcp("vscode", scope="user")
    
    with open(vscode_path, "r") as f:
        config = json.load(f)
    
    assert "other_server" in config["servers"]
    assert "mcp-stata" in config["servers"]

def test_configure_claude_code():
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("subprocess.run") as mock_run:
        setup_toolkit.configure_claude_code()
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "claude" in args
        assert "mcp" in args
        assert "add" in args
        assert "mcp-stata" in args

def test_configure_project_scope_cursor(mock_home):
    project_root = mock_home / "project"
    cfg = project_root / ".cursor" / "mcp.json"
    setup_toolkit.configure_editor_mcp("cursor", scope="project", project_root=project_root)
    data = json.loads(cfg.read_text())
    assert "mcp-stata" in data["mcpServers"]
    assert data["mcpServers"]["mcp-stata"]["env"]["STATA_PATH"] == "${STATA_PATH:-}"

def test_install_gemini_extension(mock_home):
    link = setup_toolkit.install_gemini_extension()
    assert link.exists()
    assert link.is_symlink()

@pytest.mark.requires_stata
def test_stata_connection_verification():
    # This actually tries to run the verification logic
    # We need to make sure the script can find mcp_stata
    with patch("setup_toolkit.print_success") as mock_success:
        res = setup_toolkit.test_stata_connection()
        # If Stata is installed, this should return True or at least have found Stata
        assert res is True
        # Check if any call matches "Found Stata"
        assert any("Found Stata" in call.args[0] for call in mock_success.call_args_list)
