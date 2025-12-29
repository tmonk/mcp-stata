
import asyncio
import time
import sys
import os
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent / "src"))

from mcp_stata.stata_client import StataClient
from mcp_stata.graph_detector import GraphCreationDetector

async def run_benchmark():
    client = StataClient()
    client.init()
    
    detector = GraphCreationDetector(client)
    
    print("Creating 50 graphs...")
    client.run_command_structured("sysuse auto, clear")
    for i in range(50):
        client.run_command_structured(f"scatter price mpg if _n <= {i+1}, name(g{i}, replace)")
    
    print("Initial detection...")
    start = time.time()
    new_graphs = detector._detect_graphs_via_pystata()
    end = time.time()
    print(f"Detected {len(new_graphs)} graphs in {end - start:.4f}s")
    
    print("\nSubsequent detection (no changes)...")
    start = time.time()
    new_graphs = detector._detect_graphs_via_pystata()
    end = time.time()
    print(f"Detected {len(new_graphs)} graphs in {end - start:.4f}s")
    
    print("\nModifying 1 graph...")
    client.run_command_structured("scatter price mpg if _n <= 10, name(g25, replace)")
    start = time.time()
    new_graphs = detector._detect_graphs_via_pystata()
    end = time.time()
    print(f"Detected {len(new_graphs)} graphs in {end - start:.4f}s")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
