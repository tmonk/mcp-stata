#!/usr/bin/env python3
"""Sync version fields across server.json and the plugin directory."""

from __future__ import annotations

import glob as _glob
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_JSON = ROOT / "server.json"
PLUGIN_DIR = ROOT / "plugin"
CATALOG_GENERATOR = ROOT / "scripts" / "generate_toolkit_catalog.py"

# JSON files with a top-level "version" field.
PLUGIN_JSON_FILES = [
    PLUGIN_DIR / ".claude-plugin" / "plugin.json",
    PLUGIN_DIR / ".codex-plugin" / "plugin.json",
    PLUGIN_DIR / "gemini-extension.json",
]

# JSON files where version lives inside a nested array (plugins[].version).
PLUGIN_JSON_NESTED = [
    PLUGIN_DIR / ".agents" / "plugins" / "marketplace.json",
]

# Sidecar manifest files with a top-level "version" field.
PLUGIN_MANIFEST_GLOB = [
    PLUGIN_DIR / "skills" / "*" / "manifest.json",
    PLUGIN_DIR / "agents" / "*.manifest.json",
]

def get_version() -> str:
    """Return the canonical version as reported by Hatch."""
    try:
        return subprocess.check_output(
            ["hatch", "version"], cwd=ROOT, text=True
        ).strip()
    except FileNotFoundError:
        sys.stderr.write(
            "hatch not found. Install it (e.g., `pip install hatch`) to compute the version.\n"
        )
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stdout or "")
        sys.stderr.write(exc.stderr or "")
        sys.exit(exc.returncode)


def sync_json_toplevel(path: Path, version: str) -> bool:
    """Update top-level 'version' field in a JSON file."""
    if not path.exists():
        sys.stderr.write(f"Warning: {path} not found, skipping.\n")
        return False
    data = json.loads(path.read_text())
    if data.get("version") == version:
        return False
    data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n")
    return True


def sync_json_nested(path: Path, version: str) -> bool:
    """Update 'version' inside each item of the top-level 'plugins' array."""
    if not path.exists():
        sys.stderr.write(f"Warning: {path} not found, skipping.\n")
        return False
    data = json.loads(path.read_text())
    updated = False
    for item in data.get("plugins", []):
        if item.get("version") != version:
            item["version"] = version
            updated = True
    if updated:
        path.write_text(json.dumps(data, indent=2) + "\n")
    return updated


def sync_markdown_frontmatter(path: Path, version: str) -> bool:
    """Replace `version:` in YAML frontmatter only.

    Requirements (enforced by tests):
    - Only touch the first `version:` inside the YAML frontmatter block.
    - Do not change body content (even if it contains `version:`).
    - If no `version:` exists in frontmatter, return False.
    """
    if not path.exists():
        sys.stderr.write(f"Warning: {path} not found, skipping.\n")
        return False
    text = path.read_text()
    if not text.startswith("---\n"):
        return False
    end = text.find("\n---\n", 4)
    if end == -1:
        return False

    front = text[4:end]
    body = text[end + len("\n---\n") :]

    m = re.search(r"^version:\s*(.+?)\s*$", front, flags=re.MULTILINE)
    if not m:
        return False
    if m.group(1) == version:
        return False

    new_front = re.sub(
        r"^version:\s*.+?\s*$",
        f"version: {version}",
        front,
        count=1,
        flags=re.MULTILINE,
    )
    path.write_text(f"---\n{new_front}\n---\n{body}")
    return True


def sync_server_json(version: str) -> bool:
    """Update server.json version fields."""
    if not SERVER_JSON.exists():
        sys.stderr.write(f"server.json not found at {SERVER_JSON}\n")
        sys.exit(1)
    data = json.loads(SERVER_JSON.read_text())
    updated = False
    if data.get("version") != version:
        data["version"] = version
        updated = True
    for pkg in data.get("packages", []):
        if pkg.get("identifier") == "mcp-stata" and pkg.get("version") != version:
            pkg["version"] = version
            updated = True
    if updated:
        SERVER_JSON.write_text(json.dumps(data, indent=2) + "\n")
    return updated


def main() -> None:
    version = get_version()
    results: list[tuple[Path, bool]] = []

    # server.json
    results.append((SERVER_JSON, sync_server_json(version)))

    # plugin JSON (top-level version)
    for p in PLUGIN_JSON_FILES:
        results.append((p, sync_json_toplevel(p, version)))

    # plugin JSON (nested plugins[].version)
    for p in PLUGIN_JSON_NESTED:
        results.append((p, sync_json_nested(p, version)))

    # sidecar manifests
    for pattern in PLUGIN_MANIFEST_GLOB:
        for p in sorted(Path(m) for m in _glob.glob(str(pattern))):
            results.append((p, sync_json_toplevel(p, version)))

    updated = [p for p, changed in results if changed]
    unchanged = [p for p, changed in results if not changed]

    def _fmt(p: Path) -> str:
        try:
            return str(p.relative_to(ROOT))
        except ValueError:
            return str(p)

    if updated:
        for p in updated:
            print(f"  updated  {_fmt(p)}")
    if unchanged:
        for p in unchanged:
            print(f"  ok       {_fmt(p)}")

    if CATALOG_GENERATOR.exists():
        subprocess.check_call([sys.executable, str(CATALOG_GENERATOR)], cwd=ROOT)

    print(f"\nversion: {version}  ({len(updated)} file(s) updated)")


if __name__ == "__main__":
    main()
