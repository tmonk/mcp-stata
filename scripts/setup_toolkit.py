#!/usr/bin/env python3
"""
Stata Workbench Setup Script
Automates MCP registration and verifies Stata connection.
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path

def print_step(msg):
    print(f"\n[STEP] {msg}")

def print_success(msg):
    print(f"  [SUCCESS] {msg}")

def print_error(msg):
    print(f"  [ERROR] {msg}")

def check_uv():
    print_step("Checking for uv/uvx...")
    if shutil.which("uv"):
        print_success("uv is installed.")
        return True
    else:
        print_error("uv is not installed. Please install it from https://astral.sh/uv")
        return False

def get_mcp_config_path(editor):
    home = Path.home()
    if sys.platform == "darwin":
        paths = {
            "vscode": home / "Library/Application Support/Code/User/mcp.json",
            "cursor": home / "Library/Application Support/Cursor/User/globalStorage/saoudrizwan.claude-dev/settings/mcp.json", # More common path for Claude Dev in Cursor
            "claude_desktop": home / "Library/Application Support/Claude/claude_desktop_config.json"
        }
    elif sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", home))
        paths = {
            "vscode": appdata / "Code/User/mcp.json",
            "cursor": Path(os.environ.get("USERPROFILE", home)) / ".cursor/mcp.json",
            "claude_desktop": appdata / "Claude/claude_desktop_config.json"
        }
    else:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        paths = {
            "vscode": config_home / "Code/User/mcp.json",
            "cursor": home / ".cursor/mcp.json",
            "claude_desktop": config_home / "Claude/claude_desktop_config.json"
        }
    return paths.get(editor)

def configure_editor_mcp(editor):
    print_step(f"Configuring MCP for {editor}...")
    config_path = get_mcp_config_path(editor)
    if not config_path:
        print_error(f"Could not determine config path for {editor}.")
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {}
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
        except Exception:
            pass

    if "mcpServers" not in config and editor == "cursor":
        config["mcpServers"] = {}
    elif "servers" not in config:
        config["servers"] = {}

    server_key = "mcpServers" if editor == "cursor" else "servers"
    
    config[server_key]["mcp_stata"] = {
        "command": "uvx",
        "args": ["--refresh", "--refresh-package", "mcp-stata", "--from", "mcp-stata@latest", "mcp-stata"]
    }

    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print_success(f"Updated {config_path}")
    except Exception as e:
        print_error(f"Failed to update {config_path}: {e}")

def configure_claude_code():
    print_step("Configuring Claude Code...")
    if not shutil.which("claude"):
        print_error("claude CLI not found on PATH. Skipping.")
        return

    cmd = [
        "claude", "mcp", "add", "mcp_stata", "--", 
        "uvx", "--refresh", "--refresh-package", "mcp-stata", "--from", "mcp-stata@latest", "mcp-stata"
    ]
    try:
        subprocess.run(cmd, check=True)
        print_success("Added mcp_stata to Claude Code.")
    except Exception as e:
        print_error(f"Failed to add to Claude Code: {e}")

def configure_claude_desktop():
    print_step("Configuring Claude Desktop...")
    config_path = get_mcp_config_path("claude_desktop")
    if not config_path:
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = {}
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
        except Exception:
            pass

    if "mcpServers" not in config:
        config["mcpServers"] = {}
    
    config["mcpServers"]["mcp_stata"] = {
        "command": "uvx",
        "args": ["--refresh", "--refresh-package", "mcp-stata", "--from", "mcp-stata@latest", "mcp-stata"]
    }

    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print_success(f"Updated Claude Desktop config at {config_path}")
    except Exception as e:
        print_error(f"Failed to update Claude Desktop: {e}")

def configure_codex():
    print_step("Configuring Codex...")
    home = Path.home()
    config_path = home / ".codex" / "config.toml"
    
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    mcp_block = (
        '\n[mcp_servers.mcp_stata]\n'
        'command = "uvx"\n'
        'args = ["--refresh", "--refresh-package", "mcp-stata", "--from", "mcp-stata@latest", "mcp-stata"]\n'
    )
    
    content = ""
    if config_path.exists():
        with open(config_path, "r") as f:
            content = f.read()
            
    if "[mcp_servers.mcp_stata]" in content:
        # Simple replacement if already exists
        import re
        content = re.sub(r'\[mcp_servers\.mcp_stata\].*?(?=\n\[|$)', mcp_block, content, flags=re.DOTALL)
    else:
        content += mcp_block
        
    try:
        with open(config_path, "w") as f:
            f.write(content)
        print_success(f"Updated Codex config at {config_path}")
    except Exception as e:
        print_error(f"Failed to update Codex: {e}")

def test_stata_connection():
    print_step("Testing Stata connection...")
    try:
        # Since we're in the repo, we can import directly
        # The script is in mcp-stata/scripts/, src is in mcp-stata/src/
        repo_root = Path(__file__).parent.parent
        src_path = repo_root / "src"
        if src_path.exists():
            sys.path.insert(0, str(src_path))
        
        # Now we can import
        from mcp_stata.discovery import find_stata_path
        path, edition = find_stata_path()
        print_success(f"Found Stata: {path} ({edition})")
        
        print("  Running test command 'display 2+2'...")
        from mcp_stata.sessions import SessionManager
        import asyncio
        
        async def run_test():
            manager = SessionManager()
            await manager.start()
            session = await manager.get_or_create_session("test_setup")
            res = await session.call("run_command", {"code": "display 2+2"})
            await manager.stop_session("test_setup")
            if res.get("success"):
                print_success("Stata connection verified! Output: " + res.get("stdout", "").strip())
                return True
            else:
                print_error("Stata command failed: " + str(res.get("error")))
                return False

        return asyncio.run(run_test())
    except Exception as e:
        print_error(f"Verification failed: {e}")
        return False

def main():
    print("=== Stata Workbench Setup ===")
    
    if not check_uv():
        sys.exit(1)

    # Configure editors
    for editor in ["vscode", "cursor"]:
        configure_editor_mcp(editor)

    # Configure Claude Code (CLI)
    configure_claude_code()

    # Configure Claude Desktop
    configure_claude_desktop()
    
    # Configure Codex
    configure_codex()

    # Test connection
    test_stata_connection()

    print("\n=== Setup Complete ===")
    print("If you have VS Code or Cursor open, please restart the MCP server or the editor.")

if __name__ == "__main__":
    main()
