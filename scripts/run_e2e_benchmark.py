import sys
import os
import time
import subprocess
import threading
from typing import Optional

# Ensure we can find the src modules
sys.path.insert(0, os.path.abspath("src"))

try:
    import stata_setup
    stata_setup.config("/Applications/StataNow/", "mp")
except ImportError:
    print("stata_setup not found. Ensure it is installed.")
    sys.exit(1)

from mcp_stata.stata_client import StataClient
from mcp_stata.ui_http import UIChannelManager

def setup_data(client: StataClient):
    print("Generating large dataset (1000 rows x 3000 vars)...")
    try:
        client.run_command_structured("clear")
        client.run_command_structured("set obs 1000")
        # Reuse efficient generation logic
        client.run_command_structured("forvalues i=1/3000 { \n generate v`i' = runiform() \n }")
        # Add some strings to mix it up? No, let's stick to floats first to match previous bench.
        # Actually, let's do 2000 floats and 1000 strings to be realistic?
        # Let's keep it simple first: 3000 floats. Can modify later.
    except Exception as e:
        print(f"Failed to generate data: {e}")
        sys.exit(1)

def run_e2e():
    print("Initializing StataClient...")
    client = StataClient()
    setup_data(client)

    print("Starting UIChannelManager...")
    # Use port 0 or a fixed port. Let's use 0 to avoid conflicts, but need to extract it.
    # UIChannelManager defaults to 10101.
    manager = UIChannelManager(client, port=0) 
    
    # Starting the server (implicitly via get_channel call or ensuring it starts)
    # The manager starts thread in _ensure_http_server called by get_channel
    channel_info = manager.get_channel()
    dataset_id = manager.current_dataset_id()
    
    print(f"Server running at: {channel_info.base_url}")
    print(f"Token: {channel_info.token}")
    print(f"Dataset ID: {dataset_id}")

    # Path to JS script
    js_script = os.path.join("scripts", "js_benchmark", "benchmark.js")
    
    cmd = [
        "node",
        js_script,
        channel_info.base_url,
        channel_info.token,
        dataset_id
    ]
    
    print("\n[Orchestrator] Launching JS Benchmark...")
    start_time = time.time()
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        print("\n=== JS Client Output ===")
        print(result.stdout)
        if result.stderr:
            print("=== JS Client Errors ===")
            print(result.stderr)
            
        print(f"\n[Orchestrator] JS Process finished in {time.time() - start_time:.2f}s")
        
    except FileNotFoundError:
        print("Error: 'node' executable not found. Ensure Node.js is installed.")
    except Exception as e:
        print(f"Benchmark failed: {e}")

if __name__ == "__main__":
    try:
        run_e2e()
    except KeyboardInterrupt:
        print("\nCancelled.")
    # Stata bridge might hang on exit if not clean, but script exit should kill it.
