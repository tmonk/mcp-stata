import pytest
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Add scripts/install to sys.path
repo_root = Path(__file__).resolve().parents[2]
sys.path.append(str(repo_root / "scripts" / "install"))

import setup_toolkit
import agents

@pytest.fixture
def win32_platform():
    with patch("sys.platform", "win32"):
        yield

def test_get_mcp_config_path_win32(win32_platform, tmp_path):
    appdata = tmp_path / "Roaming"
    userprofile = tmp_path / "User"
    
    env = {
        "APPDATA": str(appdata),
        "USERPROFILE": str(userprofile),
    }
    
    with patch.dict(os.environ, env):
        # VSCode
        path = setup_toolkit.get_mcp_config_path("vscode", scope="user")
        assert path == appdata / "Code" / "User" / "mcp.json"
        
        # Cursor
        path = setup_toolkit.get_mcp_config_path("cursor", scope="user")
        assert path == userprofile / ".cursor" / "mcp.json"
        
        # Claude Desktop
        path = setup_toolkit.get_mcp_config_path("claude_desktop", scope="user")
        assert path == appdata / "Claude" / "claude_desktop_config.json"

def test_agents_windows_paths(win32_platform, tmp_path):
    appdata = tmp_path / "Roaming"
    
    env = {
        "APPDATA": str(appdata),
    }
    
    with patch.dict(os.environ, env), patch("platform.system", return_value="Windows"):
        # Claude Desktop
        path = agents._claude_desktop_path()
        assert path == appdata / "Claude" / "claude_desktop_config.json"
        
        # VSCode
        path = agents._vscode_path()
        assert path == appdata / "Code" / "User" / "mcp.json"

def test_build_uvx_args_local_source():
    args = setup_toolkit.build_uvx_args(local_source="C:\\repo")
    assert "--from" in args
    assert "C:\\repo" in args
    assert "mcp-stata" in args
    assert "--refresh" in args

def test_build_uvx_args_version():
    args = setup_toolkit.build_uvx_args(version="3.1.2", latest=False)
    assert "mcp-stata@3.1.2" in args[args.index("--from") + 1]

def test_merge_json_server_config_migration(tmp_path):
    config_file = tmp_path / "mcp.json"
    # Create config with legacy key
    existing = {
        "mcpServers": {
            "mcp_stata": {"command": "old"}
        }
    }
    import json
    config_file.write_text(json.dumps(existing), encoding="utf-8")
    
    new_entry = {"command": "new", "args": []}
    setup_toolkit.merge_json_server_config(config_file, top_key="mcpServers", entry=new_entry)
    
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert "mcp-stata" in data["mcpServers"]
    assert "mcp_stata" not in data["mcpServers"]
    assert data["mcpServers"]["mcp-stata"]["command"] == "new"
