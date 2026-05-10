import time
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp_stata import discovery

def benchmark_discovery():
    print("Benchmarking Stata discovery...")
    
    start_time = time.perf_counter()
    candidates = discovery.find_stata_candidates()
    find_candidates_time = time.perf_counter() - start_time
    print(f"find_stata_candidates() took: {find_candidates_time:.4f}s")
    print(f"Candidates found: {len(candidates)}")
    for i, (path, edition) in enumerate(candidates):
        print(f"  {i+1}. {path} ({edition})")
    
    print("\nBenchmarking find_working_stata_path() (Sequential verification)...")
    start_time = time.perf_counter()
    path, edition = discovery.find_working_stata_path()
    total_time = time.perf_counter() - start_time
    
    print(f"\nResult: {path} ({edition})")
    print(f"Total discovery + verification took: {total_time:.4f}s")

if __name__ == "__main__":
    benchmark_discovery()
