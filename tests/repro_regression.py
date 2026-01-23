import asyncio
import json
import os
import sys
from mcp_stata.stata_client import StataClient

async def test_reproduction_graph_regression():
    client = StataClient()
    client.init()
    # Ensure a fresh state for signatures
    client._last_emitted_graph_signatures = {}
    
    client._run_internal("capture log close _all", echo=False)
    log_path = client._create_smcl_log_path()
    client._persistent_log_path = log_path
    client._persistent_log_name = "_mcp_session"
    client._run_internal(f"log using \"{log_path}\", name(_mcp_session) smcl replace", echo=False)

    commands = [
        "sysuse auto, clear",
        "reg price mpg",
        "twoway scatter price mpg, name(scatter1, replace)",
        "twoway scatter mpg price"
    ]
    
    graph_ready_events = []
    
    async def notify_log(msg):
        # We want to see if pollution leaked into the log channel
        if "mcp_" in msg and ("saved" in msg or "found" in msg or "opened" in msg):
             # Skip graph_ready event itself
             if '"event": "graph_ready"' not in msg:
                 print(f"STREAMING POLLUTION DETECTED: {msg}")
        
        try:
            data = json.loads(msg)
            if data.get("event") == "graph_ready":
                graph_ready_events.append(data)
        except:
            pass

    for i, cmd in enumerate(commands):
        resp = await client.run_command_streaming(
            cmd,
            notify_log=notify_log,
            emit_graph_ready=True,
            auto_cache_graphs=True
        )
        print(f"Command {i+1} finished. RC: {resp.rc}")
        
        if "mcp_" in resp.smcl_output and ("saved" in resp.smcl_output or "found" in resp.smcl_output):
            print(f"POLLUTION DETECTED in Command {i+1} response!")
            
        if "_mcp_session" in resp.smcl_output and "opened on:" in resp.smcl_output:
             # This is expected in the very first command if the log was opened before it, 
             # but we want to check for leakage elsewhere.
             pass

    print(f"Total graph_ready events: {len(graph_ready_events)}")
    for i, ev in enumerate(graph_ready_events):
        name = ev.get("graph", {}).get("name")
        print(f"  Graph {i+1}: {name}")

    client._run_internal("capture log close _mcp_session", echo=False)
    if os.path.exists(log_path): 
        try: os.remove(log_path)
        except: pass

    if len(graph_ready_events) == 2:
        print("PASS: Exactly 2 graphs reported.")
    else:
        print(f"FAIL: Expected 2 graphs, got {len(graph_ready_events)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_reproduction_graph_regression())
