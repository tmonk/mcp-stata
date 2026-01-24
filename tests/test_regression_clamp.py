import asyncio
import json
import pytest
import os
from mcp_stata.stata_client import StataClient

pytestmark = pytest.mark.requires_stata

@pytest.mark.asyncio
async def test_regression_graph_emission_and_log_cleaning(client: StataClient):
    """
    Clamping test for:
    1. Graph re-emission regression: Repeated graph commands should emit graph_ready events.
    2. SMCL log pollution regression: Internal maintenance code (preemptive_cache, save) must be stripped.
    """
    # 1. Setup - Clean Stata state
    try:
        client.stata.run("capture log close _all", echo=False)
    except Exception:
        pass
    client.stata.run("graph drop _all", echo=False)
    client.stata.run("sysuse auto, clear", echo=False)
    
    # 2. Reset client emission trackers to simulate fresh state
    client._last_emitted_graph_signatures = {}
    client._graph_signature_cache = {}
    client._graph_signature_cache_cmd_idx = None
    
    # Track all notify_log events (chunks and control events)
    all_notified_chunks = []
    graph_ready_events = []
    
    async def notify_log(msg: str):
        all_notified_chunks.append(msg)
        try:
            data = json.loads(msg)
            if data.get("event") == "graph_ready":
                graph_ready_events.append(data)
        except json.JSONDecodeError:
            pass

    # Sequence of commands:
    # 1. Regression (mpg) - no graph
    # 2. Scatter (named) - graph 1
    # 3. Scatter (unnamed) - graph 2
    # 4. Same Scatter (unnamed) - graph 2 should be re-emitted if logic is correct
    commands = [
        "reg price mpg",
        "twoway scatter price mpg, name(scatter1, replace)",
        "twoway scatter mpg price",
        "twoway scatter mpg price"
    ]
    
    responses = []
    for cmd in commands:
        resp = await client.run_command_streaming(
            cmd,
            notify_log=notify_log,
            emit_graph_ready=True,
            auto_cache_graphs=True
        )
        responses.append(resp)

    # --- VERIFICATION 1: Graph Events ---
    # Expected: 
    # - graph 1 (scatter1)
    # - graph 2 (Graph - default name)
    # - graph 3 (Graph - re-emitted because it's a new command)
    # Note: Our fix allows re-emission if command index changed OR signature changed.
    
    # In repro_regression.py we saw 2 events for 4 commands because of how it was structured.
    # Command 1: reg - 0
    # Command 2: scatter1 - 1
    # Command 3: Graph - 1
    # Command 4: Graph - 1 (re-emitted)
    # Total should be 3 if we run the same scatter twice.
    
    print(f"Graph ready events: {[e.get('graph', {}).get('name') for e in graph_ready_events]}")
    
    # Verify we got at least 3 graph events (scatter1, Graph, Graph)
    graph_names = [e.get("graph", {}).get("name") for e in graph_ready_events]
    assert "scatter1" in graph_names
    assert "Graph" in graph_names
    # We want to ensure "Graph" emitted twice for the two separate identical commands
    graph_counts = {name: graph_names.count(name) for name in set(graph_names)}
    assert graph_counts.get("Graph", 0) >= 2, f"Expected 2 'Graph' events, got {graph_counts.get('Graph', 0)}"

    # --- VERIFICATION 2: SMCL Cleaning ---
    pollution_indicators = [
        "preemptive_cache",
        "saved as SVG format",
        "capture noisily {",
        "_mcp_rc",
        "stata_client.py" # Should not see python paths in logs
    ]
    
    for i, resp in enumerate(responses):
        smcl = resp.smcl_output
        stdout = resp.stdout
        
        # Check the file at log_path
        if resp.log_path and os.path.exists(resp.log_path):
            with open(resp.log_path, "r") as f:
                log_content = f.read()
        else:
            log_content = ""

        for indicator in pollution_indicators:
            assert indicator not in smcl, f"Pollution '{indicator}' found in SMCL output for command {i+1}:\n{smcl}"
            assert indicator not in log_content, f"Pollution '{indicator}' found in log_path file for command {i+1}:\n{log_content}"
            if indicator != "stata_client.py": # python paths might naturally occur in stdout if user asked for it, but not our internal ones
                assert indicator not in stdout, f"Pollution '{indicator}' found in STDOUT for command {i+1}:\n{stdout}"

    # --- VERIFICATION 3: Streaming Chunks ---
    for chunk in all_notified_chunks:
        # Check if it's a JSON event, ignore those for cleaning check
        try:
            json.loads(chunk)
            continue
        except json.JSONDecodeError:
            pass
            
        for indicator in pollution_indicators:
            assert indicator not in chunk, f"Pollution '{indicator}' found in NOTIFIED chunk:\n{chunk}"

    # Clean up
    client.stata.run("capture log close _all", echo=False)

if __name__ == "__main__":
    pytest.main([__file__])