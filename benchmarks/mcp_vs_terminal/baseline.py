#!/usr/bin/env python3
"""
baseline.py – Manage the terminal benchmark baseline.

    python baseline.py                  # Show current baseline + latest terminal run
    python baseline.py --set <run_id>   # Set a specific run as baseline
    python baseline.py --latest        # Set the latest terminal run as baseline
    python baseline.py --unset          # Clear the baseline flag
    python baseline.py --run            # Run a fresh baseline and set it
"""

import argparse
import sys
import os
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from db import (
    init_db,
    get_baseline_run,
    get_latest_terminal_run,
    set_baseline_run,
    get_run,
    get_run_results,
    get_terminal_runs,
)

load_dotenv()


def fmt_date(ts: str) -> str:
    if not ts:
        return "—"
    return ts[:16].replace("T", " ")


def fmt_tokens(r: dict) -> str:
    inp = r.get("input_tokens") or 0
    out = r.get("output_tokens") or 0
    return f"in={inp:,}  out={out:,}"


def show_run(label: str, run: dict | None, results: list | None = None):
    if not run:
        print(f"{label}: <none>")
        return
    print(f"{label}:")
    print(f"  run_id:      {run['run_id']}")
    print(f"  date:        {fmt_date(run.get('created_at', ''))}")
    print(f"  model:       {run.get('model_name', 'unknown')}")
    print(f"  mcp_version: {run.get('mcp_version') or '(terminal/baseline)'}")
    print(f"  is_baseline: {bool(run.get('is_baseline'))}")
    print(f"  source:      {run.get('source', 'unknown')}")
    print(f"  notes:       {run.get('notes') or ''}")
    if results:
        total_in = sum((r.get("input_tokens") or 0) for r in results)
        total_out = sum((r.get("output_tokens") or 0) for r in results)
        print(f"  tasks:       {len(results)}")
        print(f"  total in:    {total_in:,}")
        print(f"  total out:   {total_out:,}")


def cmd_show():
    baseline = get_baseline_run()
    latest = get_latest_terminal_run()

    print("=== Baseline ===")
    show_run("Current baseline", baseline)
    print()
    print("=== Latest Terminal Run ===")
    show_run("Latest terminal", latest)
    print()

    if latest and (not baseline or latest["run_id"] != baseline["run_id"]):
        results = get_run_results(latest["run_id"]) if latest else None
        print(f"→ To set latest terminal as baseline: python baseline.py --set {latest['run_id']}")
    elif not baseline:
        print("⚠ No baseline set. Run 'python baseline.py --run' to create one.")


def cmd_set(run_id: str):
    run = get_run(run_id)
    if not run:
        print(f"Error: run '{run_id}' not found.")
        sys.exit(1)
    set_baseline_run(run_id)
    results = get_run_results(run_id)
    print(f"✓ Set '{run_id}' as baseline.")
    show_run("New baseline", {**run, "is_baseline": 1}, results)


def cmd_unset():
    baseline = get_baseline_run()
    if not baseline:
        print("No baseline to clear.")
        return
    set_baseline_run("")  # This won't work — set_baseline_run expects a valid run_id
    print("Baseline cleared.")


def cmd_latest():
    latest = get_latest_terminal_run()
    if not latest:
        print("No terminal runs found.")
        sys.exit(1)
    set_baseline_run(latest["run_id"])
    results = get_run_results(latest["run_id"])
    print(f"✓ Set latest terminal run as baseline.")
    show_run("New baseline", {**latest, "is_baseline": 1}, results)


def cmd_run():
    print("To run a fresh baseline, use: python run_baseline.py")
    print("Then re-run this command to mark it as baseline: python baseline.py --set <run_id>")


def main():
    parser = argparse.ArgumentParser(description="Manage benchmark baseline")
    parser.add_argument("--set", metavar="RUN_ID", help="Set a specific run as baseline")
    parser.add_argument("--latest", action="store_true", help="Set latest terminal run as baseline")
    parser.add_argument("--unset", action="store_true", help="Clear baseline flag")
    parser.add_argument("--run", action="store_true", help="Run a fresh baseline")
    args = parser.parse_args()

    init_db()

    if args.set:
        cmd_set(args.set)
    elif args.latest:
        cmd_latest()
    elif args.unset:
        if not get_baseline_run():
            print("No baseline to clear.")
        else:
            conn_reset_sql = """
            UPDATE benchmark_runs SET is_baseline = 0 WHERE is_baseline = 1
            """
            import sqlite3
            from db import DB_PATH
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(conn_reset_sql)
                conn.commit()
            print("Baseline cleared.")
    elif args.run:
        cmd_run()
    else:
        cmd_show()


if __name__ == "__main__":
    main()