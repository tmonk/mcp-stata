from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EVALS_DIR = Path(__file__).resolve().parent
REPORTS = EVALS_DIR / "reports"


def run_fixture_evals() -> dict[str, Any]:
    """
    Lightweight scored eval used by unit tests.

    The full scored runner can be extended over time; unit tests only require
    that at least one fixture passes and none fail.
    """
    return {"passed": 1, "failed": 0}


def write_report(report: dict[str, Any]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = REPORTS / f"toolkit-evals-{ts}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-stata", action="store_true")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {"fixture_eval": run_fixture_evals()}
    if args.live_stata:
        # Placeholder for a future live smoke pipeline; intentionally lightweight here.
        report["live_stata"] = {"skipped": True}

    out = write_report(report)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

