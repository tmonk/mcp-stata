"""
Agent auto-detection for mcp-stata.

Detects every supported MCP host installed on the user's machine and returns
a list of (agent_name, config_path) targets. setup_toolkit.py iterates this
list and writes the mcp-stata MCP entry into each one.

Usage:
    from agents import discover_agents

    targets = discover_agents()
    if not targets:
        sys.exit("No supported agent found. Install Claude Desktop, Claude "
                 "Code, Cursor, Windsurf, or Continue and re-run.")

    for agent in targets:
        agent.install_mcp_entry(server_config)
        print(f"Configured mcp-stata for {agent.name}")

The --agent flag, if passed, filters this list:
    targets = discover_agents()
    if args.agent:
        wanted = set(a.strip().lower() for a in args.agent.split(","))
        targets = [a for a in targets if a.name in wanted]
"""

from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class Agent:
    """One installed MCP host on this machine."""
    name: str             # 'claude-desktop' | 'claude-code' | 'cursor' | ...
    display_name: str     # 'Claude Desktop' | ...
    config_path: Path     # JSON config to merge into
    detected_via: str     # 'config_exists' | 'binary_in_path' | 'dir_exists'
    config_key: str = "mcpServers"

    def install_mcp_entry(self, name: str, server_config: dict) -> None:
        """Merge {config_key: {name: server_config}} into the agent's config.

        Idempotent — re-running with the same input is a no-op.
        Creates the parent directory and an empty file if needed.
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        if self.config_path.exists() and self.config_path.stat().st_size > 0:
            with open(self.config_path) as f:
                config = json.load(f)
        else:
            config = {}

        config.setdefault(self.config_key, {})[name] = server_config

        # Write atomically: write to .tmp, then rename. Avoids corrupting the
        # config if the process is interrupted mid-write.
        tmp = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(config, f, indent=2)
        tmp.replace(self.config_path)


# ── Config path resolution ───────────────────────────────────────────────────

def _home() -> Path:
    return Path.home()


def _claude_desktop_path() -> Optional[Path]:
    system = platform.system()
    if system == "Darwin":
        return _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
    if system == "Linux":
        # Less common but documented; respects XDG_CONFIG_HOME
        xdg = os.environ.get("XDG_CONFIG_HOME") or str(_home() / ".config")
        return Path(xdg) / "Claude" / "claude_desktop_config.json"
    return None


def _claude_code_path() -> Path:
    # Claude Code uses ~/.claude.json for user-scoped MCP servers.
    # `claude mcp add` is the official CLI; we write the file directly to
    # avoid the dependency on the binary being on PATH at install time.
    return _home() / ".claude.json"


def _cursor_path() -> Path:
    # Global Cursor MCP config (project-level configs live in <repo>/.cursor/mcp.json)
    return _home() / ".cursor" / "mcp.json"


def _windsurf_path() -> Path:
    # Codeium Windsurf, MCP support added early 2026
    return _home() / ".codeium" / "windsurf" / "mcp_config.json"


def _zed_path() -> Path:
    # Zed exposes context servers in its main settings file
    return _home() / ".config" / "zed" / "settings.json"


def _vscode_path() -> Optional[Path]:
    system = platform.system()
    if system == "Darwin":
        return _home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Code" / "User" / "mcp.json" if appdata else None
    if system == "Linux":
        xdg = os.environ.get("XDG_CONFIG_HOME") or str(_home() / ".config")
        return Path(xdg) / "Code" / "User" / "mcp.json"
    return None


def _gemini_path() -> Path:
    # Gemini extension path is a symlink to the plugin dir, not a JSON config.
    # We return the extension root; setup_toolkit.py handles the symlink.
    return _home() / ".gemini" / "extensions"


# ── Detection ────────────────────────────────────────────────────────────────

def _binary_in_path(name: str) -> bool:
    return shutil.which(name) is not None


# Each detector returns an Agent if installed, else None. A detector counts
# the agent as "installed" if EITHER the config dir exists OR a binary is on
# PATH. We never require both, because users may have launched the app once
# (creating the dir) without running it via CLI, or vice versa.

def _detect_claude_desktop() -> Optional[Agent]:
    path = _claude_desktop_path()
    if path is None:
        return None
    # The Claude/ directory is created by the app on first launch.
    if path.parent.exists():
        return Agent("claude-desktop", "Claude Desktop", path, "dir_exists")
    return None


def _detect_claude_code() -> Optional[Agent]:
    if _binary_in_path("claude"):
        return Agent("claude-code", "Claude Code", _claude_code_path(), "binary_in_path")
    if _claude_code_path().exists():
        return Agent("claude-code", "Claude Code", _claude_code_path(), "config_exists")
    return None


def _detect_cursor() -> Optional[Agent]:
    path = _cursor_path()
    if _binary_in_path("cursor") or path.parent.exists():
        return Agent("cursor", "Cursor", path,
                     "binary_in_path" if _binary_in_path("cursor") else "dir_exists")
    return None


def _detect_windsurf() -> Optional[Agent]:
    path = _windsurf_path()
    if _binary_in_path("windsurf") or path.parent.parent.exists():
        return Agent("windsurf", "Windsurf", path,
                     "binary_in_path" if _binary_in_path("windsurf") else "dir_exists")
    return None


def _detect_zed() -> Optional[Agent]:
    path = _zed_path()
    if _binary_in_path("zed") or path.exists():
        return Agent("zed", "Zed", path,
                     "binary_in_path" if _binary_in_path("zed") else "config_exists",
                     config_key="context_servers")
    return None


def _detect_vscode() -> Optional[Agent]:
    path = _vscode_path()
    if path is None:
        return None
    if _binary_in_path("code") or path.parent.exists():
        return Agent("vscode", "VS Code", path,
                     "binary_in_path" if _binary_in_path("code") else "dir_exists",
                     config_key="servers")
    return None


def _detect_gemini() -> Optional[Agent]:
    path = _gemini_path()
    # Gemini is detected if ~/.gemini exists
    if path.parent.exists():
        return Agent("gemini", "Gemini", path, "dir_exists")
    return None


_DETECTORS: list[Callable[[], Optional[Agent]]] = [
    _detect_claude_desktop,
    _detect_claude_code,
    _detect_cursor,
    _detect_windsurf,
    _detect_vscode,
    _detect_gemini,
]


def discover_agents() -> list[Agent]:
    """Return every supported MCP host that appears to be installed."""
    return [agent for d in _DETECTORS if (agent := d()) is not None]


def all_supported_agent_names() -> list[str]:
    """Names that can be passed to --agent. Useful for help text and validation."""
    return [
        # Canonical detected agent ids
        "claude-desktop",
        "claude-code",
        "cursor",
        "windsurf",
        "vscode",
        "gemini",
        # Aliases / explicit configuration targets (not auto-detected)
        "claude",
        "codex",
    ]
