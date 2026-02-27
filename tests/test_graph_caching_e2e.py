import os
import pytest
import asyncio
from unittest.mock import MagicMock
from mcp_stata.stata_client import StataClient
from mcp_stata.graph_detector import GraphCreationDetector, StreamingGraphCache

pytestmark = pytest.mark.requires_stata

@pytest.fixture(scope="module")
def real_client():
    from conftest import configure_stata_for_tests
    # Make sure we don't mock it
    import os
    os.environ["MCP_STATA_MOCK"] = "0"
    client = StataClient()
    client.init()
    client._initialize_cache()
    yield client
    # Teardown the real Stata instance
    try:
        from pystata import stata
        stata.run("clear all", quietly=True)
    except Exception:
        pass


@pytest.fixture
def detector(real_client):
    return GraphCreationDetector(real_client)


@pytest.fixture
def cache(real_client, detector):
    return StreamingGraphCache(real_client, detector)


@pytest.mark.asyncio
async def test_e2e_graph_creation_detection_and_caching(real_client, detector, cache):
    """
    Test the full E2E flow that a user experiences when they create a graph.
    1. A graph is created in Stata
    2. The detector hook detects it via PyStata's memory
    3. The cache orchestrator requests the client to cache it
    4. The SVG is successfully written to disk
    """
    stata = real_client.stata
    
    # 1. Clear state
    stata.run("graph close _all", quietly=True)
    stata.run("clear", quietly=True)
    
    # 2. Simulate User Command to create a graph
    stata.run("sysuse auto, clear", quietly=True)
    stata.run("scatter mpg weight, name(E2EGraph, replace)", quietly=True)
    
    # 3. Detector finds the new graph during background loop
    detected_graphs = detector._detect_graphs_via_pystata()
    assert "E2EGraph" in detected_graphs, "Detector should identify the newly created graph"
    
    # Simulate the worker/hook passing the detected graphs to the Cache queue
    cache._graphs_to_cache.extend(detected_graphs)
    
    # 4. Cache executes the PyStata caching flow
    freshly_cached = await cache.cache_detected_graphs_with_pystata()
    
    assert "E2EGraph" in freshly_cached, "The cache orchestrator should successfully process the graph"
    
    # 5. Verify the actual file exists
    cached_path = real_client._preemptive_cache.get("E2EGraph")
    assert cached_path is not None, "Client should track the cached path"
    assert os.path.exists(cached_path), "The SVG file should be physically created on disk"
    assert os.path.getsize(cached_path) > 0, "The SVG file should have content"

    # Cleanup
    stata.run("graph drop E2EGraph", quietly=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
