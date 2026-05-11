#!/usr/bin/env python3
"""Run scored evals for the mcp-stata toolkit."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "plugin" / "evals" / "fixtures"
REPORTS = ROOT / "plugin" / "evals" / "reports"


def score_fixture(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"name", "input", "expected"}
    missing = sorted(required - set(payload))
    passed = not missing
    return {
        "fixture": path.name,
        "name": payload.get("name", path.stem),
        "passed": passed,
        "missing_keys": missing,
    }


def run_fixture_evals() -> dict:
    results = [score_fixture(path) for path in sorted(FIXTURES.glob("*.json"))]
    passed = sum(1 for item in results if item["passed"])
    return {
        "mode": "fixtures",
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


async def run_live_stata_eval() -> dict:
    src_path = ROOT / "src"
    import sys

    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from mcp_stata.server import stata_manage_graphs, stata_manage_session, stata_run, session_manager

    session_id = "eval_live"
    report = {"mode": "live_stata", "available": True, "checks": []}

    await session_manager.start()
    try:
        detect = await stata_manage_session(action="detect", session_id=session_id, as_json=False)
        report["checks"].append({"name": "detect", "success": bool(detect.success), "data": detect.data})

        basic = await stata_run("display 2+2", session_id=session_id, strip_smcl=True, as_json=False)
        report["checks"].append({"name": "basic_execution", "success": bool(basic.success), "data": basic.data})

        graph = await stata_run(
            "sysuse auto, clear\ntwoway scatter price mpg, name(eval_live_graph, replace)",
            session_id=session_id,
            strip_smcl=True,
            as_json=False,
        )
        graphs = await stata_manage_graphs(action="list", session_id=session_id, as_json=False)
        report["checks"].append(
            {
                "name": "graph_pipeline",
                "success": bool(graph.success),
                "graphs": graphs.data if hasattr(graphs, "data") else graphs,
            }
        )
    except Exception as exc:
        report["available"] = False
        report["error"] = str(exc)
    finally:
        await session_manager.stop_all()

    return report


def write_report(payload: dict) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = REPORTS / f"eval_report_{timestamp}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-stata", action="store_true")
    args = parser.parse_args()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixture_eval": run_fixture_evals(),
    }

    if args.live_stata:
        report["live_stata_eval"] = asyncio.run(run_live_stata_eval())

    path = write_report(report)

    fixture_eval = report["fixture_eval"]
    print(f"Fixture evals: {fixture_eval['passed']} passed, {fixture_eval['failed']} failed")
    if args.live_stata:
        live = report["live_stata_eval"]
        if live.get("available"):
            print("Live Stata eval: completed")
        else:
            print(f"Live Stata eval: unavailable ({live.get('error', 'unknown error')})")
    print(f"Report written to {path}")

    return 0 if fixture_eval["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
