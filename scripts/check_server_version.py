#!/usr/bin/env python3
"""Fail if server.json is out of sync with the canonical project version."""

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


def load_server_json() -> dict:
    if not SERVER_JSON.exists():
        sys.stderr.write(f"server.json not found at {SERVER_JSON}\n")
        sys.exit(1)
    return json.loads(SERVER_JSON.read_text())


def main() -> None:
    version = get_version()
    data = load_server_json()

    mismatches = []
    if data.get("version") != version:
        mismatches.append(f"root version {data.get('version')} != {version}")

    for pkg in data.get("packages", []):
        if pkg.get("identifier") == "mcp-stata" and pkg.get("version") != version:
            mismatches.append(
                f"package {pkg.get('identifier')} version {pkg.get('version')} != {version}"
            )

    if mismatches:
        sys.stderr.write("server.json version mismatch:\n")
        for msg in mismatches:
            sys.stderr.write(f"- {msg}\n")
        sys.exit(1)

    print(f"server.json is in sync with {version}")


if __name__ == "__main__":
    main()

