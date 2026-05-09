#!/usr/bin/env python3
import asyncio
import time
import os
import json
import argparse
from pathlib import Path
from datetime import datetime

# Ensure we can import mcp_stata
repo_root = Path(__file__).parent.parent.parent.absolute()
src_path = repo_root / "src"
os.environ["PYTHONPATH"] = str(src_path) + ":" + os.environ.get("PYTHONPATH", "")

from mcp_stata.sessions import SessionManager
from mcp_stata.statest import runner

async def run_benchmark(suite_path: str, parallel: bool, workers: int):
    manager = SessionManager()
    await manager.start()
    try:
        start_time = time.perf_counter()
        summary = await runner.run_tests(suite_path, manager, parallel=parallel, max_workers=workers)
        end_time = time.perf_counter()
        
        return {
            "suite": os.path.basename(suite_path),
            "total_tests": summary.total_tests,
            "passed": summary.passed,
            "failed": summary.failed,
            "wall_clock_seconds": end_time - start_time,
            "parallel": parallel,
            "workers": workers,
            "avg_seconds_per_test": (end_time - start_time) / summary.total_tests if summary.total_tests > 0 else 0
        }
    finally:
        await manager.stop_all()

async def main():
    parser = argparse.ArgumentParser(description="Statest Performance Benchmarking Tool")
    parser.add_argument("--suite", default="significant", help="Name of the suite in benchmarks/suites/")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--sequential", action="store_true", help="Run in sequential mode too")
    parser.add_argument("--output", help="Custom output path for JSON results")
    
    args = parser.parse_args()
    
    suite_path = repo_root / "benchmarks" / "suites" / args.suite
    if not suite_path.exists():
        print(f"Error: Suite path {suite_path} does not exist.")
        return

    print(f"Benchmarking suite: {args.suite} ({len(runner.discover_tests(str(suite_path)))} tests)")
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "suite": args.suite,
        "results": []
    }
    
    # Sequential
    if args.sequential:
        print("Running sequential...")
        seq_res = await run_benchmark(str(suite_path), parallel=False, workers=1)
        results["results"].append(seq_res)
        print(f"  Sequential: {seq_res['wall_clock_seconds']:.2f}s ({seq_res['avg_seconds_per_test']:.3f}s/test)")
    
    # Parallel
    print(f"Running parallel ({args.workers} workers)...")
    par_res = await run_benchmark(str(suite_path), parallel=True, workers=args.workers)
    results["results"].append(par_res)
    print(f"  Parallel:   {par_res['wall_clock_seconds']:.2f}s ({par_res['avg_seconds_per_test']:.3f}s/test)")
    
    # Save results
    output_path = args.output or repo_root / "benchmarks" / "history" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to {output_path}")
    
    # Generate Markdown Summary
    md_path = Path(str(output_path).replace(".json", ".md"))
    with open(md_path, "w") as f:
        f.write(f"# Benchmark Run: {args.suite}\n\n")
        f.write(f"- Date: {results['timestamp']}\n")
        f.write(f"- Total Tests: {par_res['total_tests']}\n\n")
        f.write("| Mode | Duration | Avg/Test | Workers |\n")
        f.write("| :--- | :--- | :--- | :--- |\n")
        for r in results["results"]:
            mode = "Parallel" if r["parallel"] else "Sequential"
            f.write(f"| {mode} | {r['wall_clock_seconds']:.2f}s | {r['avg_seconds_per_test']:.3f}s | {r['workers']} |\n")
            
    print(f"Markdown report generated at {md_path}")

if __name__ == "__main__":
    asyncio.run(main())
