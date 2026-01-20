#!/usr/bin/env python3
"""Benchmark UI HTTP sorting performance (server-side).

Usage:
  python scripts/benchmark_ui_sort.py --obs 200000 --iters 30
"""
from __future__ import annotations

import argparse
import statistics
import time

from mcp_stata.stata_client import StataClient
from mcp_stata.ui_http import UIChannelManager, handle_page_request


def _timed(fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    return time.perf_counter() - start, result


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark UI sort performance")
    parser.add_argument("--obs", type=int, default=200_000, help="Number of observations to generate")
    parser.add_argument("--iters", type=int, default=30, help="Number of timed iterations")
    parser.add_argument("--limit", type=int, default=200, help="Rows per page request")
    args = parser.parse_args()

    client = StataClient()
    client.init()

    # Build a sizable dataset to make sorts measurable.
    client.run_command_structured("clear", echo=False)
    client.run_command_structured(f"set obs {args.obs}", echo=False)
    client.run_command_structured("generate price = runiform()", echo=False)
    client.run_command_structured("generate mpg = runiform()", echo=False)
    client.run_command_structured("generate make = string(_n)", echo=False)

    manager = UIChannelManager(client)
    dataset_id = manager.current_dataset_id()

    base_req = {
        "datasetId": dataset_id,
        "frame": "default",
        "offset": 0,
        "limit": args.limit,
        "vars": ["price", "mpg", "make"],
    }

    # Baseline without sorting.
    baseline_times = []
    for _ in range(min(5, args.iters)):
        dt, _ = _timed(handle_page_request, manager, dict(base_req), view_id=None)
        baseline_times.append(dt)

    # First sort (cache miss) + repeated cached sort calls.
    sort_req = dict(base_req)
    sort_req["sortBy"] = ["-price", "mpg"]

    first_sort_time, _ = _timed(handle_page_request, manager, sort_req, view_id=None)
    cached_times = []
    for _ in range(args.iters):
        dt, _ = _timed(handle_page_request, manager, sort_req, view_id=None)
        cached_times.append(dt)

    def _fmt(stats):
        return {
            "mean_ms": round(statistics.mean(stats) * 1000, 2),
            "p50_ms": round(statistics.median(stats) * 1000, 2),
            "p95_ms": round(statistics.quantiles(stats, n=20)[-1] * 1000, 2) if len(stats) >= 20 else None,
        }

    print("Baseline (no sort):", _fmt(baseline_times))
    print("First sort (cache miss):", round(first_sort_time * 1000, 2), "ms")
    print("Cached sort calls:", _fmt(cached_times))

if __name__ == "__main__":
    main()
