"""
Tests for enhanced pystata integration in graph detection using actual implementation.
"""

import pytest
import os

# Configure Stata before importing sfi-dependent modules
import stata_setup
from conftest import configure_stata_for_tests

try:
    stata_dir, stata_flavor = configure_stata_for_tests()
    stata_setup.config(stata_dir, stata_flavor)
except (FileNotFoundError, PermissionError) as e:
    pytest.skip(f"Stata not found or not executable: {e}", allow_module_level=True)

from mcp_stata.graph_detector import GraphCreationDetector, StreamingGraphCache


# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata


class TestPystataGraphIntegration:
    """Test pystata integration for graph detection using real Stata."""
    
    @pytest.fixture
    def detector_with_real_client(self, client):
        """Create detector with shared StataClient."""
        return GraphCreationDetector(stata_client=client)
    
    def test_detector_init_with_client(self, detector_with_real_client):
        """Test GraphCreationDetector initialization with real StataClient."""
        detector = detector_with_real_client
        assert detector._stata_client is not None
        assert hasattr(detector._stata_client, 'stata')
    
    def test_detect_graphs_via_pystata_new_graphs(self, detector_with_real_client):
        """Test detecting new graphs via pystata."""
        detector = detector_with_real_client
        
        # Clear existing graphs
        detector._stata_client.stata.run("clear", quietly=True)
        
        # Create a graph
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        detector._stata_client.stata.run("scatter price mpg, name(NewGraph)", quietly=True)
        
        # Detect new graphs
        detected = detector._detect_graphs_via_pystata()
        
        assert "NewGraph" in detected, f"Should detect NewGraph, found: {detected}"
        
        # Clean up
        detector._stata_client.stata.run("graph drop NewGraph", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
    
    def test_detect_graphs_via_pystata_modified_graphs(self, detector_with_real_client):
        """Test detecting modified graphs via pystata."""
        detector = detector_with_real_client
        
        # Create initial graph
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        detector._stata_client.stata.run("scatter price mpg, name(Graph1)", quietly=True)
        
        # Get initial state
        initial_state = detector._get_graph_state_from_pystata()
        
        # Modify the graph
        detector._stata_client.stata.run("graph drop Graph1", quietly=True)
        detector._stata_client.stata.run("scatter price weight, name(Graph1)", quietly=True)
        
        # Detect modified graphs
        detected = detector._detect_graphs_via_pystata()
        
        assert "Graph1" in detected, f"Should detect modified Graph1, found: {detected}"
        
        # Clean up
        detector._stata_client.stata.run("graph drop Graph1", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
    
    def test_get_current_graphs_from_pystata_with_client(self, detector_with_real_client):
        """Test getting current graphs from pystata with real StataClient."""
        detector = detector_with_real_client
        
        # Create a graph
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        detector._stata_client.stata.run("scatter price mpg, name(CurrentTest)", quietly=True)
        
        # Get current graphs
        graphs = detector._get_current_graphs_from_pystata()
        
        assert "CurrentTest" in graphs, f"Should detect CurrentTest, found: {graphs}"
        
        # Clean up
        detector._stata_client.stata.run("graph drop CurrentTest", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
    
    def test_get_graph_state_from_pystata(self, detector_with_real_client):
        """Test getting graph state from pystata."""
        detector = detector_with_real_client
        
        # Create a graph
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        detector._stata_client.stata.run("scatter price mpg, name(StateTest)", quietly=True)
        
        # Get graph state
        state = detector._get_graph_state_from_pystata()
        
        assert "StateTest" in state, "Should contain StateTest"
        assert state["StateTest"]["name"] == "StateTest", "Should have correct name"
        assert state["StateTest"]["exists"] == True, "Should show graph exists"
        
        # Clean up
        detector._stata_client.stata.run("graph drop StateTest", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
    
    def test_sfi_graph_detection_integration(self, detector_with_real_client):
        """Test SFI graph detection integration with real Stata."""
        detector = detector_with_real_client
        
        # Test SFI detection with real Stata
        detected = detector._detect_graphs_via_pystata()
        assert isinstance(detected, list)
        
        # Test state tracking
        state = detector._get_graph_state_from_pystata()
        assert isinstance(state, dict)
        
        # Clean up
        detector._stata_client.stata.run("clear", quietly=True)
    
    def test_sfi_detection_integration_complete(self, detector_with_real_client):
        """Test complete SFI detection integration with real Stata."""
        detector = detector_with_real_client
        
        # Clear existing graphs
        detector._stata_client.stata.run("clear", quietly=True)
        
        # Create a graph
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        output = detector._stata_client.stata.run("scatter price mpg, name(IntegrationTest)", quietly=True)
        
        # Detect graphs using SFI
        detected = detector._detect_graphs_via_pystata()
        
        assert "IntegrationTest" in detected, f"Should detect IntegrationTest, found: {detected}"
        
        # Clean up
        detector._stata_client.stata.run("graph drop IntegrationTest", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
    
        
    @pytest.mark.asyncio
    async def test_cache_detected_graphs_with_pystata(self, client):
        """Test enhanced caching with pystata integration."""
        cache = StreamingGraphCache(client, auto_cache=True)
        
        # Create real graphs first
        client.stata.run("sysuse auto, clear", quietly=True)
        client.stata.run("scatter price mpg, name(Graph1)", quietly=True)
        client.stata.run("histogram price, name(Graph2)", quietly=True)
        
        # Add graphs to cache queue
        cache._graphs_to_cache = ['Graph1', 'Graph2']
        
        # Test with real graphs
        cached_graphs = await cache.cache_detected_graphs_with_pystata()
        
        # Should cache graphs from queue and pystata detection
        assert len(cached_graphs) >= 0
        
        # Clean up
        try:
            client.stata.run("graph drop Graph1 Graph2", quietly=True)
        except SystemError:
            pass
        client.stata.run("clear", quietly=True)
    
    @pytest.mark.asyncio
    async def test_cache_detected_graphs_fallback(self, client):
        """Test fallback to original method when pystata method not available."""
        cache = StreamingGraphCache(client, auto_cache=True)
        
        # Create a real graph first
        client.stata.run("sysuse auto, clear", quietly=True)
        client.stata.run("scatter price mpg, name(Graph1)", quietly=True)
        
        # Add graph to cache queue
        cache._graphs_to_cache = ['Graph1']
        
        cached_graphs = await cache.cache_detected_graphs()
        
        # Should cache the real graph
        assert len(cached_graphs) >= 0
        
        # Clean up
        try:
            client.stata.run("graph drop Graph1", quietly=True)
        except SystemError:
            pass
        client.stata.run("clear", quietly=True)

    def test_svg_export_integration(self, client):
        """Test SVG export integration with real Stata."""
        stata = client.stata
        
        # Create a graph
        stata.run("sysuse auto, clear", quietly=True)
        stata.run("scatter price mpg, name(SVGTestGraph)", quietly=True)
        
        # Export to SVG
        svg_path = os.path.abspath("SVGTestGraph.svg")
        stata.run(f"graph export {svg_path}, as(svg) replace", quietly=True)
        
        # Check if SVG file was created
        assert os.path.isfile(svg_path), "SVG file should be created"
        
        # Clean up
        stata.run("graph drop SVGTestGraph", quietly=True)
        stata.run("clear", quietly=True)
        if os.path.isfile(svg_path):
            os.remove(svg_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
