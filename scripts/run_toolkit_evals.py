#!/usr/bin/env python3
"""Run lightweight mocked evals for the mcp-stata toolkit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "plugin" / "evals" / "fixtures"


def run_mocked_evals() -> list[str]:
    failures: list[str] = []
    for path in sorted(FIXTURES.glob("*.json")):
        payload = json.loads(path.read_text())
        required = {"name", "input", "expected"}
        missing = required - set(payload)
        if missing:
            failures.append(f"{path.name}: missing keys {sorted(missing)}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-stata", action="store_true")
    args = parser.parse_args()

    failures = run_mocked_evals()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1

    print(f"PASS mocked evals ({len(list(FIXTURES.glob('*.json')))} fixture files)")
    if args.live_stata:
        print("SKIP live Stata evals: scaffold only, opt-in hook not implemented here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
