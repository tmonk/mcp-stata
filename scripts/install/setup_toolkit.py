#!/usr/bin/env python3
"""
Cross-agent setup helpers for the mcp-stata toolkit.

This script powers the repo-local installer and is also importable from tests.
Note: When running this script via 'uv run' in the repository root, use '--no-project'
to avoid building the native Rust extension. The extension is optional for registration
and will be fetched as a pre-compiled wheel from PyPI when the server is executed via 'uvx'.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Add the script's directory to sys.path to allow importing local modules like 'agents'
# when run via 'uv run' or from other directories.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents import Agent, all_supported_agent_names, discover_agents

CANONICAL_SERVER_NAME = "mcp-stata"
LEGACY_SERVER_NAMES = ("mcp_stata",)
PACKAGE_NAME = "mcp-stata"
CLAUDE_MARKETPLACE_GITHUB_REF = "tmonk/mcp-stata"
DEFAULT_SCOPE = "user"
# NOTE: Zed and Continue are intentionally NOT supported by mcp-stata at this time.
SUPPORTED_AGENTS = ("claude", "codex", "gemini", "cursor", "windsurf", "vscode")
REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugin"
PLUGIN_SKILLS_DIR = PLUGIN_ROOT / "skills"
AGENTS_BLOCK_START = "<!-- BEGIN MCP-STATA MANAGED BLOCK -->"
AGENTS_BLOCK_END = "<!-- END MCP-STATA MANAGED BLOCK -->"
VERBOSE = False
INSTALL_LOG_PATH = os.environ.get("MCP_STATA_INSTALL_LOG_FILE", "")


def get_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def print_step(msg: str) -> None:
    print(f"\n[STEP] {msg}")


def print_success(msg: str) -> None:
    print(f"  [SUCCESS] {msg}")


def print_warning(msg: str) -> None:
    print(f"  [WARNING] {msg}")


def print_error(msg: str) -> None:
    print(f"  [ERROR] {msg}")


def set_verbose(enabled: bool) -> None:
    global VERBOSE
    VERBOSE = enabled
    if enabled:
        import logging
        logging.basicConfig(level=logging.DEBUG, format="  [LOG] %(name)s: %(message)s")


def _append_install_log(message: str) -> None:
    if not INSTALL_LOG_PATH:
        return
    try:
        with open(INSTALL_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(message.rstrip("\n") + "\n")
    except Exception:
        pass


def print_verbose(msg: str) -> None:
    line = f"  [VERBOSE] {msg}"
    _append_install_log(line)
    if VERBOSE:
        print(line)


def _format_cmd(cmd: list[str]) -> str:
    return shlex.join(str(part) for part in cmd)


def run_logged_subprocess(
    cmd: list[str],
    *,
    check: bool,
    quiet_console: bool = False,
) -> subprocess.CompletedProcess:
    print_verbose(f"Running command: {_format_cmd(cmd)}")
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    print_verbose(f"Command exit code: {result.returncode}")
    if result.stdout:
        _append_install_log("[VERBOSE] stdout:")
        for line in result.stdout.rstrip().splitlines():
            _append_install_log(line)
            if VERBOSE and not quiet_console:
                print(line)
    if result.stderr:
        _append_install_log("[VERBOSE] stderr:")
        for line in result.stderr.rstrip().splitlines():
            _append_install_log(line)
            if VERBOSE and not quiet_console:
                print(line)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def build_uvx_args(
    *,
    version: str | None = None,
    latest: bool = True,
    local_source: str | None = None,
) -> list[str]:
    if local_source:
        return ["--refresh", "--from", local_source, PACKAGE_NAME]
    ref = "latest" if latest or not version else version
    return ["--refresh", "--refresh-package", PACKAGE_NAME, "--from", f"{PACKAGE_NAME}@{ref}", PACKAGE_NAME]


def build_server_entry(
    *,
    include_type: bool = False,
    include_env: bool = False,
    version: str | None = None,
    latest: bool = True,
    local_source: str | None = None,
) -> dict:
    entry = {
        "command": "uvx",
        "args": build_uvx_args(version=version, latest=latest, local_source=local_source),
    }
    if include_type:
        entry = {"type": "stdio", **entry}
    if include_env:
        env = {}
        for key in ("STATA_PATH", "MCP_STATA_STARTUP_DO_FILE", "MCP_STATA_TEMP_DIR"):
            value = os.environ.get(key)
            if value:
                env[key] = value
        if env:
            entry["env"] = env
    return entry


def _migrate_server_keys(mapping: dict, canonical_entry: dict) -> dict:
    for legacy in LEGACY_SERVER_NAMES:
        mapping.pop(legacy, None)
    mapping[CANONICAL_SERVER_NAME] = canonical_entry
    return mapping


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def merge_json_server_config(path: Path, *, top_key: str, entry: dict) -> Path:
    data = _load_json(path)
    section = data.setdefault(top_key, {})
    if not isinstance(section, dict):
        section = {}
        data[top_key] = section
    _migrate_server_keys(section, entry)
    _write_json(path, data)
    return path


def _format_toml_value(value: str) -> str:
    return json.dumps(value)


def upsert_codex_config(
    path: Path,
    *,
    entry: dict,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = path.read_text() if path.exists() else ""
    pattern = re.compile(
        r'(?ms)^\[mcp_servers\.(?:"?mcp-stata"?|"?mcp_stata"?)(?:\.env)?\]\n.*?(?=^\[|\Z)'
    )
    content = pattern.sub("", content).rstrip()

    block_lines = [
        f"[mcp_servers.{CANONICAL_SERVER_NAME}]",
        f'command = "{entry["command"]}"',
        f"args = {json.dumps(entry['args'])}",
    ]
    env = entry.get("env", {})
    if env:
        block_lines.append(f"[mcp_servers.{CANONICAL_SERVER_NAME}.env]")
        for key, value in env.items():
            block_lines.append(f"{key} = {_format_toml_value(value)}")
    block = "\n".join(block_lines) + "\n"
    new_content = (content + "\n\n" + block).lstrip("\n")
    path.write_text(new_content)
    return path


def get_project_root(project_root: Path | None = None) -> Path:
    if project_root is not None:
        return project_root
    env_root = os.environ.get("MCP_STATA_PROJECT_ROOT")
    if env_root:
        return Path(env_root)
    return REPO_ROOT


def get_mcp_config_path(editor: str, scope: str = "user", project_root: Path | None = None) -> Path | None:
    project_root = get_project_root(project_root)
    home = Path.home()
    if scope == "project":
        project_paths = {
            "cursor": project_root / ".cursor" / "mcp.json",
            "claude_desktop": project_root / ".mcp.json",
        }
        if editor in project_paths:
            return project_paths[editor]

    if sys.platform == "darwin":
        paths = {
            "vscode": home / "Library/Application Support/Code/User/mcp.json",
            "cursor": home / ".cursor" / "mcp.json",
            "claude_desktop": home / "Library/Application Support/Claude/claude_desktop_config.json",
        }
    elif sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", home))
        paths = {
            "vscode": appdata / "Code/User/mcp.json",
            "cursor": Path(os.environ.get("USERPROFILE", home)) / ".cursor" / "mcp.json",
            "claude_desktop": appdata / "Claude" / "claude_desktop_config.json",
        }
    else:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        paths = {
            "vscode": config_home / "Code/User/mcp.json",
            "cursor": home / ".cursor" / "mcp.json",
            "claude_desktop": config_home / "Claude" / "claude_desktop_config.json",
        }
    return paths.get(editor)


def check_uv() -> bool:
    print_step("Checking for uv/uvx")
    uv = shutil.which("uv")
    uvx = shutil.which("uvx")
    if uv or uvx:
        print_success(f"Found {'uvx' if uvx else 'uv'}")
        return True
    print_error("uv/uvx not found. Install uv from https://astral.sh/uv")
    return False


def detect_stata(stata_path_override: str | None = None) -> tuple[str | None, str | None]:
    if stata_path_override:
        path = Path(stata_path_override)
        if not path.exists():
            raise FileNotFoundError(f"Stata executable not found: {stata_path_override}")
        return str(path), "manual"

    env_path = os.environ.get("STATA_PATH")
    if env_path and Path(env_path).exists():
        return env_path, "env"

    src_path = REPO_ROOT / "src"
    if src_path.exists():
        sys.path.insert(0, str(src_path))
    try:
        from mcp_stata.discovery import find_stata_path

        path, edition = find_stata_path()
        return path, edition
    except Exception:
        return None, None




def configure_editor_mcp(
    editor: str,
    *,
    scope: str = "user",
    version: str | None = None,
    latest: bool = True,
    local_source: str | None = None,
    project_root: Path | None = None,
) -> Path:
    config_path = get_mcp_config_path(editor, scope=scope, project_root=project_root)
    if not config_path:
        raise RuntimeError(f"Could not determine config path for {editor}")
    top_key = "servers" if editor == "vscode" else "mcpServers"
    include_type = editor == "vscode"
    include_env = False
    entry = build_server_entry(
        include_type=include_type,
        include_env=include_env,
        version=version,
        latest=latest,
        local_source=local_source,
    )
    return merge_json_server_config(config_path, top_key=top_key, entry=entry)


def configure_claude_code(
    *,
    scope: str = "user",
    version: str | None = None,
    latest: bool = True,
    local_source: str | None = None,
    project_root: Path | None = None,
) -> Path | None:
    if scope == "project":
        entry = build_server_entry(
            include_type=True,
            include_env=False,
            version=version,
            latest=latest,
            local_source=local_source,
        )
        return merge_json_server_config(
            get_mcp_config_path("claude_desktop", scope="project", project_root=project_root),
            top_key="mcpServers",
            entry=entry,
        )

    if shutil.which("claude"):
        cmd = ["claude", "mcp", "add", "--scope", scope, CANONICAL_SERVER_NAME, "--", "uvx", *build_uvx_args(version=version, latest=latest, local_source=local_source)]
        try:
            run_logged_subprocess(cmd, check=True)
            return None
        except Exception:
            print_warning("Claude CLI registration failed; falling back to JSON config.")

    entry = build_server_entry(
        version=version,
        latest=latest,
        local_source=local_source,
    )
    return merge_json_server_config(
        get_mcp_config_path("claude_desktop", scope="user", project_root=project_root),
        top_key="mcpServers",
        entry=entry,
    )


def configure_claude_desktop(
    *,
    version: str | None = None,
    latest: bool = True,
    local_source: str | None = None,
) -> Path:
    entry = build_server_entry(version=version, latest=latest, local_source=local_source)
    return merge_json_server_config(
        get_mcp_config_path("claude_desktop", scope="user"),
        top_key="mcpServers",
        entry=entry,
    )


def configure_codex(
    *,
    scope: str = "user",
    version: str | None = None,
    latest: bool = True,
    local_source: str | None = None,
    project_root: Path | None = None,
) -> Path:
    target_dir = get_codex_home() if scope == "user" else get_project_root(project_root) / ".codex"
    config_path = target_dir / "config.toml"
    entry = build_server_entry(
        include_env=False,
        version=version,
        latest=latest,
        local_source=local_source,
    )
    return upsert_codex_config(config_path, entry=entry)


def install_claude_marketplace(
    *,
    scope: str = "project",
    project_root: Path | None = None,
) -> bool:
    if not shutil.which("claude"):
        return False

    root = get_project_root(project_root)
    marketplace_name = "mcp-stata-marketplace"
    _cleanup_claude_marketplace(scope=scope, project_root=project_root)

    try:
        run_logged_subprocess(["claude", "plugin", "marketplace", "add", CLAUDE_MARKETPLACE_GITHUB_REF, "--scope", scope], check=True)
    except Exception as exc:
        print_warning(f"Claude marketplace add did not complete cleanly: {exc}")

    try:
        run_logged_subprocess(["claude", "plugin", "install", f"{CANONICAL_SERVER_NAME}@{marketplace_name}", "--scope", scope], check=True)
        return True
    except Exception as exc:
        print_warning(f"Claude marketplace install failed; falling back to direct configuration: {exc}")
        return False


def install_codex_marketplace(
    *,
    project_root: Path | None = None,
) -> bool:
    if not shutil.which("codex"):
        return False

    _cleanup_codex_marketplace(project_root=project_root)

    try:
        run_logged_subprocess(["codex", "plugin", "marketplace", "add", CLAUDE_MARKETPLACE_GITHUB_REF, "--sparse", ".agents/plugins"], check=True)
        return True
    except Exception as exc:
        print_warning(f"Codex marketplace install failed; falling back to direct configuration: {exc}")
        return False


def _best_effort_subprocess(cmd: list[str]) -> None:
    try:
        run_logged_subprocess(cmd, check=False, quiet_console=True)
    except Exception:
        pass


def _cleanup_claude_marketplace(*, scope: str, project_root: Path | None = None) -> None:
    marketplace_name = "mcp-stata-marketplace"
    for cmd in (
        ["claude", "plugin", "uninstall", f"{CANONICAL_SERVER_NAME}@{marketplace_name}", "--scope", scope],
        ["claude", "plugin", "uninstall", CANONICAL_SERVER_NAME, "--scope", scope],
        ["claude", "plugin", "marketplace", "remove", marketplace_name],
    ):
        _best_effort_subprocess(cmd)


def _cleanup_codex_marketplace(*, project_root: Path | None = None) -> None:
    _best_effort_subprocess(["codex", "plugin", "marketplace", "remove", "mcp-stata"])


def install_codex_skills(*, project_root: Path | None = None) -> list[Path]:
    skills_root = get_codex_home() / "skills"
    return _sync_skills(PLUGIN_SKILLS_DIR, skills_root)


def install_gemini_extension(*, project_root: Path | None = None) -> Path | None:
    extensions_root = Path.home() / ".gemini" / "extensions"
    extensions_root.mkdir(parents=True, exist_ok=True)
    link = extensions_root / CANONICAL_SERVER_NAME
    return link if _ensure_symlink(link, PLUGIN_ROOT) else None


def register_generic_skills(*, project_root: Path | None = None) -> list[Path]:
    skills_root = Path.home() / ".agents" / "skills"
    return _sync_skills(PLUGIN_SKILLS_DIR, skills_root)


def _sync_skills(source_dir: Path, target_dir: Path) -> list[Path]:
    """
    Sync individual skill subdirectories from source_dir to target_dir.
    Only touches symlinks that point into the source_dir (our "own" skills).
    """
    if not source_dir.exists():
        return []

    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Cleanup legacy namespaced link if it exists
    legacy_link = target_dir / CANONICAL_SERVER_NAME
    if legacy_link.is_symlink():
        try:
            if str(legacy_link.resolve()).startswith(str(source_dir)):
                legacy_link.unlink()
                print_verbose(f"Removed legacy namespaced skill link: {legacy_link}")
        except Exception:
            pass

    # Identify skills in the source
    source_skills = {p.name: p for p in source_dir.iterdir() if p.is_dir() and not p.name.startswith(".")}
    synced = []

    # 2. Ensure current skills are linked (Add/Update)
    for skill_name, target_path in source_skills.items():
        link = target_dir / skill_name
        if _ensure_symlink(link, target_path):
            synced.append(link)

    # 3. Remove orphaned symlinks (Remove our OWN removed skills)
    for item in target_dir.iterdir():
        if item.is_symlink():
            try:
                resolved = item.resolve()
                if str(resolved).startswith(str(source_dir)):
                    if item.name not in source_skills:
                        item.unlink()
                        print_verbose(f"Removed orphaned skill symlink: {item}")
            except Exception:
                pass

    return synced


def _cleanup_skills(target_dir: Path):
    """Remove any symlinks in target_dir that point into our PLUGIN_SKILLS_DIR."""
    if not target_dir.exists():
        return []
    removed = []
    # Also check the namespaced legacy link
    legacy_link = target_dir / CANONICAL_SERVER_NAME
    for item in list(target_dir.iterdir()) + [legacy_link]:
        if item.exists() and item.is_symlink():
            try:
                if str(item.resolve()).startswith(str(PLUGIN_SKILLS_DIR)):
                    item.unlink()
                    removed.append(item)
            except Exception:
                pass
    return removed


def _ensure_symlink(link: Path, target: Path) -> bool:
    if os.path.lexists(link):
        try:
            # samefile() handles symlinks and junctions correctly across platforms
            if link.exists() and target.exists() and os.path.samefile(link, target):
                return True
        except Exception:
            pass

        if link.is_symlink():
            link.unlink()
        else:
            # Real directory or Windows junction — remove before re-linking.
            # os.rmdir removes a junction without touching its target; shutil.rmtree
            # would follow the junction and delete the target, so avoid it on Windows.
            try:
                if link.is_dir():
                    # Check if it's a real directory (not a link/junction)
                    # On Windows, is_dir() is true for junctions too, but is_symlink() is false.
                    # We want to be careful not to delete a user's real skills directory.
                    print_warning(f"Existing path {link} is a real directory and would be overwritten. Skipping.")
                    return False
                else:
                    link.unlink()
            except Exception as exc:
                print_warning(f"Skipping {link}: could not remove existing path: {exc}")
                return False

    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError:
        if sys.platform == "win32":
            if target.is_dir():
                # Junctions allow directory linking without special privileges
                try:
                    subprocess.run(
                        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    return True
                except subprocess.CalledProcessError:
                    pass
            else:
                # Hardlinks allow file linking without special privileges
                try:
                    os.link(target, link)
                    return True
                except OSError:
                    pass
        raise
    return True


def _remove_symlink(link: Path) -> bool:
    if link.is_symlink():
        link.unlink()
        return True
    return False


def remove_json_server_config(path: Path, *, top_key: str) -> tuple[Path, bool]:
    """Remove mcp-stata entry (canonical + legacy names) from a JSON config file."""
    data = _load_json(path)
    if not data:
        return path, False
    section = data.get(top_key, {})
    if not isinstance(section, dict):
        return path, False
    changed = False
    for name in (CANONICAL_SERVER_NAME,) + LEGACY_SERVER_NAMES:
        if name in section:
            del section[name]
            changed = True
    if changed:
        data[top_key] = section
        _write_json(path, data)
    return path, changed


def remove_codex_config(path: Path) -> tuple[Path, bool]:
    """Remove the mcp-stata TOML block from a Codex config.toml."""
    if not path.exists():
        return path, False
    content = path.read_text()
    pattern = re.compile(
        r'(?ms)^\[mcp_servers\.(?:"?mcp-stata"?|"?mcp_stata"?)\](?:\.env)?\n.*?(?=^\[|\Z)'
    )
    new_content = pattern.sub("", content).strip()
    if new_content == content.strip():
        return path, False
    path.write_text((new_content + "\n") if new_content else "")
    return path, True


def remove_project_agents_hint(project_root: Path | None = None) -> tuple[Path, bool]:
    """Remove the managed block from AGENTS.md."""
    root = get_project_root(project_root)
    target = root / "AGENTS.md"
    if not target.exists():
        return target, False
    content = target.read_text()
    pattern = re.compile(
        rf"{re.escape(AGENTS_BLOCK_START)}.*?{re.escape(AGENTS_BLOCK_END)}\n?",
        re.DOTALL,
    )
    new_content = pattern.sub("", content).strip()
    if new_content == content.strip():
        return target, False
    if new_content:
        target.write_text(new_content + "\n")
    else:
        target.unlink()
    return target, True


def uninstall_for_agent(
    agent: str,
    *,
    scope: str,
    project_root: Path | None = None,
) -> list[Path]:
    removed: list[Path] = []

    def _append(path: Path | None, changed: bool) -> None:
        if path is not None and changed:
            removed.append(path)

    if agent == "claude":
        if shutil.which("claude"):
            try:
                run_logged_subprocess(
                    ["claude", "mcp", "remove", CANONICAL_SERVER_NAME, "--scope", scope],
                    check=True,
                )
            except Exception:
                pass
        for s in ("user", "project"):
            config_path = get_mcp_config_path("claude_desktop", scope=s, project_root=project_root)
            if config_path:
                _append(*remove_json_server_config(config_path, top_key="mcpServers"))
        return removed

    if agent == "codex":
        target_dir = get_codex_home() if scope == "user" else get_project_root(project_root) / ".codex"
        _append(*remove_codex_config(target_dir / "config.toml"))
        # Cleanup individual and namespaced skills
        skills_dir = get_codex_home() / "skills"
        removed.extend(_cleanup_skills(skills_dir))
        _append(*remove_project_agents_hint(project_root=project_root))
        return removed

    if agent == "gemini":
        link = Path.home() / ".gemini" / "extensions" / CANONICAL_SERVER_NAME
        if _remove_symlink(link):
            removed.append(link)
        # Gemini skills are in ~/.agents/skills
        removed.extend(_cleanup_skills(Path.home() / ".agents" / "skills"))
        return removed

    if agent == "cursor":
        config_path = get_mcp_config_path("cursor", scope=scope, project_root=project_root)
        if config_path:
            _append(*remove_json_server_config(config_path, top_key="mcpServers"))
        return removed

    if agent == "windsurf":
        config_path = Path.home() / ".codeium" / "windsurf" / "mcp_config.json"
        _append(*remove_json_server_config(config_path, top_key="mcpServers"))
        return removed

    if agent == "vscode":
        config_path = get_mcp_config_path("vscode", scope=scope, project_root=project_root)
        if config_path:
            _append(*remove_json_server_config(config_path, top_key="servers"))
        return removed

    return removed


def _run_uninstall(args: argparse.Namespace) -> int:
    print("=== mcp-stata Toolkit Uninstall ===")
    project_root = get_project_root()
    targets = discover_agents()

    if args.agent:
        wanted = {a.strip().lower() for a in args.agent.split(",")}
        if "claude" in wanted:
            wanted.update({"claude-desktop", "claude-code"})
        targets = [a for a in targets if a.name in wanted]

    # Remove the generic skills symlink(s) once, regardless of agent.
    generic_skills_root = Path.home() / ".agents" / "skills"
    if not args.dry_run:
        removed = _cleanup_skills(generic_skills_root)
        for path in removed:
            print_success(f"Removed {path}")
    else:
        print(f"  [dry-run] would remove mcp-stata skill symlinks from {generic_skills_root}")

    if not targets:
        print_warning("No supported agents detected. Nothing to uninstall.")
        return 0

    seen_internal: set[str] = set()
    for agent in targets:
        internal_name = agent.name
        if internal_name.startswith("claude-"):
            internal_name = "claude"
        if internal_name in seen_internal:
            continue
        seen_internal.add(internal_name)

        print_step(f"Uninstalling from {agent.display_name}")
        if args.dry_run:
            print(f"  [dry-run] would remove {CANONICAL_SERVER_NAME} from {agent.display_name} ({args.scope} scope)")
            continue

        if internal_name in SUPPORTED_AGENTS:
            removed = uninstall_for_agent(internal_name, scope=args.scope, project_root=project_root)
            if removed:
                for path in removed:
                    print_success(f"Cleaned {path}")
            else:
                print_warning(f"Nothing to remove for {agent.display_name}")
        else:
            config_path = getattr(agent, "config_path", None)
            if config_path:
                path, changed = remove_json_server_config(Path(config_path), top_key="mcpServers")
                if changed:
                    print_success(f"Cleaned {path}")
                else:
                    print_warning(f"Nothing to remove for {agent.display_name}")

    print("\n=== Uninstall Complete ===")
    return 0


def _managed_agents_block() -> str:
    return "\n".join(
        [
            AGENTS_BLOCK_START,
            "## mcp-stata Toolkit",
            "",
            "Always use the `mcp-stata` toolkit for Stata workflows in this project.",
            "Reach for it for regressions, `.do` files, dataset inspection, graph export,",
            "log review, replication checks, data audit, publication QA, and environment diagnostics.",
            AGENTS_BLOCK_END,
        ]
    )


def merge_project_agents_hint(project_root: Path | None = None) -> Path:
    root = get_project_root(project_root)
    target = root / "AGENTS.md"
    managed_block = _managed_agents_block()
    if target.exists():
        content = target.read_text().rstrip()
        pattern = re.compile(
            rf"{re.escape(AGENTS_BLOCK_START)}.*?{re.escape(AGENTS_BLOCK_END)}",
            re.DOTALL,
        )
        if pattern.search(content):
            new_content = pattern.sub(managed_block, content)
        else:
            separator = "\n\n" if content else ""
            new_content = f"{content}{separator}{managed_block}"
    else:
        new_content = managed_block
    target.write_text(new_content.rstrip() + "\n")
    return target


def test_stata_connection() -> bool:
    print_step("Running setup verification")
    src_path = REPO_ROOT / "src"
    if src_path.exists():
        sys.path.insert(0, str(src_path))

    try:
        from mcp_stata.sessions import SessionManager
    except Exception as exc:
        print_error(f"Unable to import mcp-stata internals for verification: {exc}")
        return False

    try:
        path, edition = detect_stata()
        if not path:
            print_warning("Stata not found. Skipping live verification.")
            return False
        print_success(f"Found Stata: {path} ({edition or 'unknown'})")
    except Exception as exc:
        print_error(str(exc))
        return False

    import asyncio

    async def _run() -> bool:
        manager = SessionManager()
        await manager.start()
        session = await manager.get_or_create_session("setup_verification")
        checks = [
            ("display 2+2", "basic execution"),
            ("cap which reghdfe\nlocal has_reghdfe = (_rc==0)\ndisplay `has_reghdfe'", "reghdfe availability"),
            ("cap which gcollapse\nlocal has_gtools = (_rc==0)\ndisplay `has_gtools'", "gtools availability"),
            ("tempname g\nsysuse auto, clear\nscatter price mpg\ngraph dir", "graph export readiness"),
            ("capture noisily display c(sysdir_stata)\n", "startup/profile readiness"),
        ]
        ok = True
        try:
            for code, label in checks:
                res = await session.call("run_command", {"code": code})
                if res.get("success"):
                    print_success(f"Verified {label}")
                else:
                    ok = False
                    print_warning(f"Verification failed for {label}: {res.get('error')}")
            log_res = await session.call("run_command", {"code": "noi di \"log-check\""})
            if log_res.get("log_path"):
                print_success("Verified log streaming path emission")
            else:
                ok = False
                print_warning("Verification did not emit a log path")
        finally:
            await manager.stop_session("setup_verification")
        return ok

    try:
        return asyncio.run(_run())
    except Exception as exc:
        print_error(f"Verification failed: {exc}")
        return False


def install_for_agent(
    agent: str,
    *,
    scope: str,
    version: str | None,
    latest: bool,
    local_source: str | None,
    project_root: Path | None = None,
) -> list[Path]:
    written: list[Path] = []

    def _append(item: Path | list[Path] | None) -> None:
        if item is None:
            return
        if isinstance(item, list):
            written.extend(item)
        else:
            written.append(item)

    if agent == "claude":
        marketplace_ok = install_claude_marketplace(scope=scope, project_root=project_root)
        if marketplace_ok:
            uninstall_for_agent("claude", scope=scope, project_root=project_root)
            print_success("Plugin installed — MCP server registered by plugin")
            print_success("Removed any conflicting standalone MCP registration")
        else:
            print_warning(
                "Plugin install failed. The plugin is the recommended install method — "
                "it includes skills, agents, and the MCP server in one step.\n"
                f"  To install manually: claude plugin install {PLUGIN_ROOT} --scope user\n"
                "  Falling back to MCP-only JSON config (skills and agents will not be available)."
            )
            _append(configure_claude_code(
                scope=scope,
                version=version,
                latest=latest,
                local_source=local_source,
                project_root=project_root,
            ))
        return written

    if agent == "codex":
        marketplace_ok = install_codex_marketplace(project_root=project_root)
        if marketplace_ok:
            uninstall_for_agent("codex", scope=scope, project_root=project_root)
            print_success("Plugin installed — MCP server registered by plugin")
            print_success("Removed any conflicting standalone MCP registration")
        else:
            print_warning(
                "Plugin install failed. The plugin is the recommended install method.\n"
                f"  To install manually: codex plugin install {PLUGIN_ROOT}\n"
                "  Falling back to MCP-only config (skills and agents will not be available)."
            )
            _append(configure_codex(
                scope=scope,
                version=version,
                latest=latest,
                local_source=local_source,
                project_root=project_root,
            ))
            _append(install_codex_skills(project_root=project_root))
        return written

    if agent == "gemini":
        _append(install_gemini_extension(project_root=project_root))
        _append(register_generic_skills(project_root=project_root))
        return written

    if agent == "cursor":
        _append(
            configure_editor_mcp(
                "cursor",
                scope=scope,
                version=version,
                latest=latest,
                local_source=local_source,
                project_root=project_root,
            )
        )
        _append(register_generic_skills(project_root=project_root))
        return written

    if agent == "windsurf":
        _append(
            merge_json_server_config(
                Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
                top_key="mcpServers",
                entry=build_server_entry(version=version, latest=latest, local_source=local_source),
            )
        )
        _append(register_generic_skills(project_root=project_root))
        return written

    if agent == "vscode":
        _append(
            configure_editor_mcp(
                "vscode",
                scope=scope,
                version=version,
                latest=latest,
                local_source=local_source,
                project_root=project_root,
            )
        )
        _append(register_generic_skills(project_root=project_root))
        return written

    raise ValueError(f"Unsupported agent: {agent}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install and verify the mcp-stata toolkit.")
    parser.add_argument(
        "--agent",
        help=f"Comma-separated list of agents to configure. "
             f"Supported: {', '.join(all_supported_agent_names())}. "
             f"Default: configure every detected agent.",
        default="",
    )
    parser.add_argument(
        "--no-fail-on-empty",
        action="store_true",
        help="Don't exit with error if no agents are found (useful for CI).",
    )
    parser.add_argument("--scope", choices=["project", "user"], default=DEFAULT_SCOPE)
    parser.add_argument("--stata-path", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--latest", action="store_true", help="Force latest package resolution (default).")
    parser.add_argument(
        "--local-source",
        default="",
        help="Install from a local repo or wheel path for offline setups.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show raw behind-the-scenes installer activity in the terminal.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove mcp-stata from all detected (or specified) agent configurations.",
    )
    return parser


def _print_dry_run(
    agent: str,
    *,
    scope: str,
    version: str | None,
    latest: bool,
    local_source: str | None,
    project_root: Path,
) -> None:
    if agent == "claude":
        if scope == "project":
            print(f"  [dry-run] would add marketplace from {project_root}")
            print(f"  [dry-run] would install {CANONICAL_SERVER_NAME}@mcp-stata-marketplace")
        else:
            print("  [dry-run] would add marketplace and install the plugin in Claude")
        return
    if agent == "codex":
        print(f"  [dry-run] would add marketplace from {project_root / '.agents' / 'plugins'}")
        if scope == "user":
            print("  [dry-run] would update Codex user configuration if marketplace install is unavailable")
        else:
            print("  [dry-run] would update Codex project configuration if marketplace install is unavailable")
        print(f"  [dry-run] would symlink individual skills from {PLUGIN_SKILLS_DIR} -> {get_codex_home() / 'skills'}")
        print(f"  [dry-run] would merge project guidance into {project_root / 'AGENTS.md'}")
        return
    if agent == "gemini":
        print(f"  [dry-run] would link {PLUGIN_ROOT} -> {Path.home() / '.gemini' / 'extensions' / CANONICAL_SERVER_NAME}")
        return
    if agent == "cursor":
        print(f"  [dry-run] would write {get_mcp_config_path('cursor', scope=scope, project_root=project_root)}")
        return
    if agent == "windsurf":
        print(f"  [dry-run] would write {Path.home() / '.codeium' / 'windsurf' / 'mcp_config.json'}")
        return
    if agent == "vscode":
        print(f"  [dry-run] would write {get_mcp_config_path('vscode', scope=scope, project_root=project_root)}")
        return
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    set_verbose(args.verbose)
    print_verbose(f"Installer argv: {argv if argv is not None else sys.argv[1:]}")
    print_verbose(f"Resolved project root: {get_project_root()}")

    if args.uninstall:
        return _run_uninstall(args)

    latest = True
    if args.version:
        latest = False
    elif args.latest:
        latest = True

    print("=== mcp-stata Toolkit Setup ===")

    if not check_uv():
        return 1

    try:
        stata_path, stata_edition = detect_stata(args.stata_path or None)
    except FileNotFoundError as exc:
        print_error(str(exc))
        return 1
    if stata_path:
        # Tests and users rely on seeing where Stata came from.
        print_success(f"STATA_PATH={stata_path} ({stata_edition})")
    else:
        print_warning("Stata not found. You can set STATA_PATH or pass --stata-path to enable verification.")

    project_root = get_project_root()
    targets = discover_agents()

    requested: list[str] = []
    if args.agent:
        requested = [a.strip().lower() for a in args.agent.split(",") if a.strip()]

    if requested:
        # If the user explicitly requests agents, we should configure them even if
        # auto-detection fails (e.g. fresh CI HOME with --agent gemini).
        normalized: list[str] = []
        for name in requested:
            if name in ("claude-desktop", "claude-code"):
                normalized.append("claude")
            else:
                normalized.append(name)
        wanted = list(dict.fromkeys(normalized))  # stable unique

        unknown = [a for a in wanted if a not in SUPPORTED_AGENTS]
        if unknown:
            print_error(f"Unsupported agent(s): {', '.join(unknown)}")
            return 1

        # Filter any detected agents, but don't require detection.
        detected_internal: set[str] = set()
        for a in targets:
            internal = a.name
            if internal.startswith("claude-"):
                internal = "claude"
            detected_internal.add(internal)

        explicit_targets: list[tuple[str, str]] = []
        for internal in wanted:
            # Display names in summary output
            display = internal.capitalize() if internal != "vscode" else "VS Code"
            explicit_targets.append((internal, display))
        targets = []  # sentinel: we will use explicit_targets path below
    else:
        explicit_targets = []
    grouped_targets: list[tuple[str, list[str], object | None]] = []
    if not explicit_targets:
        grouped_map: dict[str, tuple[list[str], object | None]] = {}
        grouped_order: list[str] = []
        for agent in targets:
            internal_name = agent.name
            if internal_name.startswith("claude-"):
                internal_name = "claude"
            if internal_name not in grouped_map:
                grouped_map[internal_name] = ([agent.display_name], agent)
                grouped_order.append(internal_name)
            else:
                grouped_map[internal_name][0].append(agent.display_name)
        grouped_targets = [
            (internal_name, grouped_map[internal_name][0], grouped_map[internal_name][1])
            for internal_name in grouped_order
        ]

    if not explicit_targets and not targets:
        if args.no_fail_on_empty:
            print_warning("No supported agents were detected. Nothing to configure.")
            return 0
        print_error("No supported MCP host detected. Install Claude Desktop, Claude Code, Cursor, or Windsurf and re-run.")
        return 1

    agent_names = [d for _, d in explicit_targets] if explicit_targets else [name for _, names, _ in grouped_targets for name in names]
    print_step("Configuration summary")
    print_success(f"Scope: {args.scope}")
    print_success(f"Agents: {', '.join(agent_names)}")
    if args.local_source:
        print_success(f"Install source: local ({args.local_source})")
    elif args.version:
        print_success(f"Install source: PyPI @{args.version}")
    else:
        print_success("Install source: PyPI @latest")
    if stata_path:
        print_success(f"Stata: {stata_path} ({stata_edition or 'unknown'})")
    else:
        print_warning("Stata not found. Set STATA_PATH before verification.")

    if explicit_targets:
        for internal_name, display_name in explicit_targets:
            print_step(f"Configuring {display_name}")
            if args.dry_run:
                _print_dry_run(
                    internal_name,
                    scope=args.scope,
                    version=args.version or None,
                    latest=latest,
                    local_source=args.local_source or None,
                    project_root=project_root,
                )
                continue
            written = install_for_agent(
                internal_name,
                scope=args.scope,
                version=args.version or None,
                latest=latest,
                local_source=args.local_source or None,
                project_root=project_root,
            )
            for path in written:
                print_success(f"Updated {path}")
    else:
        for internal_name, display_names, representative in grouped_targets:
            joined_display_names = ", ".join(display_names)
            print_step(f"Configuring {joined_display_names}")
            if args.dry_run:
                _print_dry_run(
                    internal_name,
                    scope=args.scope,
                    version=args.version or None,
                    latest=latest,
                    local_source=args.local_source or None,
                    project_root=project_root,
                )
                continue

            if internal_name in SUPPORTED_AGENTS:
                written = install_for_agent(
                    internal_name,
                    scope=args.scope,
                    version=args.version or None,
                    latest=latest,
                    local_source=args.local_source or None,
                    project_root=project_root,
                )
                if len(display_names) > 1:
                    print_success(f"Applied shared configuration for: {joined_display_names}")
                for path in written:
                    print_success(f"Updated {path}")
            else:
                # Generic JSON merge
                server_config = build_server_entry(
                    version=args.version or None,
                    latest=latest,
                    local_source=args.local_source or None,
                )
                assert representative is not None
                representative.install_mcp_entry(CANONICAL_SERVER_NAME, server_config)
                if len(display_names) > 1:
                    print_success(f"Applied shared configuration for: {joined_display_names}")
                print_success(f"Updated {representative.config_path}")

    if args.verify and not args.dry_run:
        test_stata_connection()

    print("\n=== Setup Complete ===")
    print(f"Canonical server name: {CANONICAL_SERVER_NAME}")
    print("Verify by asking your agent: Do you have access to mcp-stata, an agentic toolkit for Stata?")
    print("Quick start: /stata-run sysuse auto, clear")
    print("Quick start: /stata-inspect")
    print("Quick start: /stata-run regress price mpg")
    print("Quick start: /stata-results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())