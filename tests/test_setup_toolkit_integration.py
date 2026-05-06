import pytest
import os
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

# Since we're in the repo, we can import directly
repo_root = Path(__file__).parent.parent
sys.path.append(str(repo_root / "scripts"))

import setup_toolkit

@pytest.fixture
def mock_home(tmp_path):
    with patch("pathlib.Path.home", return_value=tmp_path):
        yield tmp_path

def test_configure_editor_mcp(mock_home):
    # Setup mock paths for macOS structure
    vscode_path = mock_home / "Library/Application Support/Code/User/mcp.json"
    claude_path = mock_home / "Library/Application Support/Claude/claude_desktop_config.json"
    
    # Run configuration
    setup_toolkit.configure_editor_mcp("vscode")
    setup_toolkit.configure_claude_desktop()
    
    assert vscode_path.exists()
    assert claude_path.exists()
    
    with open(claude_path, "r") as f:
        config = json.load(f)
    assert "mcp_stata" in config["mcpServers"]

def test_configure_codex(mock_home):
    codex_path = mock_home / ".codex/config.toml"
    
    setup_toolkit.configure_codex()
    
    assert codex_path.exists()
    with open(codex_path, "r") as f:
        content = f.read()
    assert "[mcp_servers.mcp_stata]" in content
    assert 'command = "uvx"' in content

def test_configure_editor_mcp_existing(mock_home):
    vscode_path = mock_home / "Library/Application Support/Code/User/mcp.json"
    vscode_path.parent.mkdir(parents=True)
    
    existing_config = {"servers": {"other_server": {"command": "echo"}}}
    with open(vscode_path, "w") as f:
        json.dump(existing_config, f)
        
    setup_toolkit.configure_editor_mcp("vscode")
    
    with open(vscode_path, "r") as f:
        config = json.load(f)
    
    assert "other_server" in config["servers"]
    assert "mcp_stata" in config["servers"]

def test_configure_claude_code():
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("subprocess.run") as mock_run:
        setup_toolkit.configure_claude_code()
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "claude" in args
        assert "mcp" in args
        assert "add" in args
        assert "mcp_stata" in args

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
