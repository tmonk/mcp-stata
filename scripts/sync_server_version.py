#!/usr/bin/env python3
"""Sync server.json version fields with the canonical project version."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_JSON = ROOT / "server.json"


def get_version() -> str:
    """Return the canonical version as reported by Hatch."""
    try:
        return (
            subprocess.check_output(["hatch", "version"], cwd=ROOT, text=True)
            .strip()
        )
    except FileNotFoundError:
        sys.stderr.write(
            "hatch not found. Install it (e.g., `pip install hatch`) to compute the version.\n"
        )
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stdout or "")
        sys.stderr.write(exc.stderr or "")
        sys.exit(exc.returncode)


def sync_server_json(version: str) -> bool:
    """Update server.json version fields; return True if a write occurred."""
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
    updated = sync_server_json(version)
    if updated:
        print(f"Updated server.json to {version}")
    else:
        print(f"server.json already at {version}")


if __name__ == "__main__":
    main()

