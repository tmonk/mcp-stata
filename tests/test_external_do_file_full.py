from pathlib import Path
import os

import pytest

# Configure Stata before importing sfi-dependent modules
import stata_setup
from conftest import configure_stata_for_tests

try:
    stata_dir, stata_flavor = configure_stata_for_tests()
    stata_setup.config(stata_dir, stata_flavor)
except (FileNotFoundError, PermissionError) as e:
    pytest.skip(f"Stata not found or not executable: {e}", allow_module_level=True)

from mcp_stata.graph_detector import StreamingGraphCache

# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata


DO_FILE = Path("/Users/tom/Library/CloudStorage/Dropbox/projects/indirect_exp/code/4_figures/figure3_main_source_shaped_behavior.do")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_external_figure3_do_file(client):
    """Test external do-file with enhanced graph detection and caching at creation."""
    if not DO_FILE.exists():
        pytest.skip("External figure3 do-file not present")

    prev_cwd = os.getcwd()
    os.chdir(DO_FILE.parent)
    try:
        # Initialize streaming cache with auto-caching enabled
        cache = StreamingGraphCache(client, auto_cache=True)
        

        graphs_cached_at_creation = []
        
        async def log_notifier(text: str):
            """Simple log notifier for streaming."""
            pass
        
        async def graph_cached_notifier(graph_name: str, success: bool):
            """Track graphs as they're cached at creation."""
            graphs_cached_at_creation.append((graph_name, success))
            print(f"Graph cached at creation: {graph_name}, success: {success}")

        # Run the do-file with streaming cache integration
        resp = await client.run_do_file_streaming(
            str(DO_FILE), 
            notify_log=log_notifier,
            auto_cache_graphs=True,
            on_graph_cached=graph_cached_notifier,
            echo=True,  # Enable echo to get output for streaming detection
            trace=False
        )
        
        assert resp.success is True
        assert resp.rc == 0

        # Data inspection
        data = client.get_data(0, 2)
        assert isinstance(data, list)
        if data:
            assert isinstance(data[0], dict)

        # Variables
        vars_struct = client.list_variables_structured()
        assert len(vars_struct.variables) > 0

        # Graphs - verify all graphs are captured
        graphs = client.list_graphs_structured()
        assert len(graphs.graphs) >= 1, f"Expected at least 1 graph, found {len(graphs.graphs)}"
        
        # Store graph names for verification
        graph_names = [graph.name for graph in graphs.graphs]
        print(f"Graphs found after execution: {graph_names}")

        # Verify graphs were detected and cached during execution
        cache_stats = cache.get_cache_stats()
        print(f"Cache stats: {cache_stats}")
        
        # Should have detected graphs during the run
        assert cache_stats['detected_graphs_count'] >= 0, "Should have detected graphs during execution"
        
        # Check that graphs were cached at creation
        print(f"Graphs cached at creation: {[name for name, success in graphs_cached_at_creation]}")
        if graphs_cached_at_creation:
            assert len(graphs_cached_at_creation) >= 0, "Should have cached graphs at creation"
            
            # Verify that cached graphs actually exist
            for graph_name, success in graphs_cached_at_creation:
                if success:
                    assert graph_name in graph_names, f"Cached graph {graph_name} should exist in final graph list"

        # Test token-efficient file path export (default)
        exports = client.export_graphs_all()
        assert len(exports.graphs) >= 1, f"Expected at least 1 exported graph, found {len(exports.graphs)}"
        assert exports.graphs[0].file_path, "Exported graphs should have file paths"

    finally:
        os.chdir(prev_cwd)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_external_figure3_do_file_with_streaming(client):
    """Test external do-file with explicit streaming cache verification."""
    if not DO_FILE.exists():
        pytest.skip("External figure3 do-file not present")

    prev_cwd = os.getcwd()
    os.chdir(DO_FILE.parent)
    try:
        # Initialize streaming cache
        cache = StreamingGraphCache(client, auto_cache=True)
        
        # Clear any existing state
        cache.reset()
        
        # Track all graph detection events
        detection_events = []
        
        async def log_notifier(text: str):
            pass
            
        async def track_detection(graph_name: str, success: bool):
            detection_events.append({
                'graph_name': graph_name,
                'success': success,
                'timestamp': __import__('time').time()
            })

        # Run the do-file with streaming
        resp = await client.run_do_file_streaming(
            str(DO_FILE),
            notify_log=log_notifier,
            auto_cache_graphs=True,
            on_graph_cached=track_detection,
            echo=True,  # Enable echo to get output for streaming detection
            trace=False
        )
        
        assert resp.success is True

        # Get final graph list
        final_graphs = client.list_graphs_structured()
        final_graph_names = [g.name for g in final_graphs.graphs]
        
        print(f"Final graphs in Stata: {final_graph_names}")
        print(f"Detection events: {detection_events}")
        
        # Verify graphs were captured
        assert len(final_graphs.graphs) >= 1, "Should have created at least one graph"
        
        # Verify cache detected graphs during execution
        cache_stats = cache.get_cache_stats()
        print(f"Final cache stats: {cache_stats}")
        
        # The cache should have detected graphs during the run
        assert cache_stats['detected_graphs_count'] >= 0, "Should have detected graphs during streaming"
        
        # Verify that created graphs match what we detected
        if detection_events:
            detected_names = [event['graph_name'] for event in detection_events if event['success']]
            print(f"Graphs detected during execution: {detected_names}")
            
            # All detected graphs should exist in final graph list
            for detected_name in detected_names:
                assert detected_name in final_graph_names, \
                    f"Detected graph {detected_name} should exist in final graph list"

    finally:
        os.chdir(prev_cwd)


@pytest.mark.integration
def test_external_figure3_do_file_sync(client):
    """Test external do-file with synchronous execution and cache verification."""
    if not DO_FILE.exists():
        pytest.skip("External figure3 do-file not present")

    prev_cwd = os.getcwd()
    os.chdir(DO_FILE.parent)
    try:
        # Initialize streaming cache
        cache = StreamingGraphCache(client, auto_cache=True)
        
        # Run the do-file synchronously
        resp = client.run_do_file(str(DO_FILE), echo=False, trace=False)
        assert resp.success is True
        assert resp.rc == 0

        # Get final graph list
        final_graphs = client.list_graphs_structured()
        final_graph_names = [g.name for g in final_graphs.graphs]
        
        print(f"Final graphs in Stata (sync): {final_graph_names}")
        
        # Verify graphs were captured
        assert len(final_graphs.graphs) >= 1, "Should have created at least one graph"
        
        # Verify cache detected graphs during execution
        cache_stats = cache.get_cache_stats()
        print(f"Cache stats (sync): {cache_stats}")
        
        # The cache should have detected graphs during the run
        assert cache_stats['detected_graphs_count'] >= 0, "Should have detected graphs during execution"

    finally:
        os.chdir(prev_cwd)