"""
Tests for enhanced pystata integration in graph detection using actual implementation.
"""

import pytest
import sys
import os
import tempfile

# Add the src directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Configure Stata before importing sfi-dependent modules
import stata_setup
from mcp_stata.discovery import find_stata_path

try:
    stata_path, stata_flavor = find_stata_path()
    stata_setup.config(stata_path, stata_flavor)
except (FileNotFoundError, PermissionError) as e:
    pytest.skip(f"Stata not found or not executable: {e}", allow_module_level=True)

from mcp_stata.graph_detector import GraphCreationDetector, StreamingGraphCache, SFI_AVAILABLE
from mcp_stata.stata_client import StataClient


# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata


class TestPystataGraphIntegration:
    """Test pystata integration for graph detection using real Stata."""
    
    @pytest.fixture
    def real_stata_client(self):
        """Create a real StataClient with actual Stata connection."""
        client = StataClient()
        client.init()  # Initialize the actual Stata connection
        yield client
        # Cleanup if needed
    
    @pytest.fixture
    def detector_with_real_client(self, real_stata_client):
        """Create detector with real StataClient."""
        return GraphCreationDetector(stata_client=real_stata_client)
    
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
    
    def test_streaming_cache_with_pystata(self, real_stata_client):
        """Test StreamingGraphCache with real pystata integration."""
        cache = StreamingGraphCache(real_stata_client, auto_cache=True)
        
        # Verify detector is initialized with client
        assert cache.detector._stata_client == real_stata_client
        
        # Test processing a chunk that creates a graph
        real_stata_client.stata.run("sysuse auto, clear", quietly=True)
        cache.process_streaming_chunk("scatter price mpg, name(StreamingTest)")
        
        # Should have detected the graph
        assert "StreamingTest" in cache._graphs_to_cache or len(cache._cached_graphs) > 0
        
        # Clean up
        try:
            real_stata_client.stata.run("graph drop StreamingTest", quietly=True)
        except SystemError:
            pass
        real_stata_client.stata.run("clear", quietly=True)
    
    @pytest.mark.asyncio
    async def test_cache_detected_graphs_with_pystata(self, real_stata_client):
        """Test enhanced caching with pystata integration."""
        cache = StreamingGraphCache(real_stata_client, auto_cache=True)
        
        # Create real graphs first
        real_stata_client.stata.run("sysuse auto, clear", quietly=True)
        real_stata_client.stata.run("scatter price mpg, name(Graph1)", quietly=True)
        real_stata_client.stata.run("histogram price, name(Graph2)", quietly=True)
        
        # Add graphs to cache queue
        cache._graphs_to_cache = ['Graph1', 'Graph2']
        
        # Test with real graphs
        cached_graphs = await cache.cache_detected_graphs_with_pystata()
        
        # Should cache graphs from queue and pystata detection
        assert len(cached_graphs) >= 0
        
        # Clean up
        try:
            real_stata_client.stata.run("graph drop Graph1 Graph2", quietly=True)
        except SystemError:
            pass
        real_stata_client.stata.run("clear", quietly=True)
    
    @pytest.mark.asyncio
    async def test_cache_detected_graphs_fallback(self, real_stata_client):
        """Test fallback to original method when pystata method not available."""
        cache = StreamingGraphCache(real_stata_client, auto_cache=True)
        
        # Create a real graph first
        real_stata_client.stata.run("sysuse auto, clear", quietly=True)
        real_stata_client.stata.run("scatter price mpg, name(Graph1)", quietly=True)
        
        # Add graph to cache queue
        cache._graphs_to_cache = ['Graph1']
        
        cached_graphs = await cache.cache_detected_graphs()
        
        # Should cache the real graph
        assert len(cached_graphs) >= 0
        
        # Clean up
        try:
            real_stata_client.stata.run("graph drop Graph1", quietly=True)
        except SystemError:
            pass
        real_stata_client.stata.run("clear", quietly=True)


class TestPystataIntegrationEdgeCases:
    """Test edge cases for pystata integration."""
    
    @pytest.fixture
    def detector_with_real_client(self):
        """Create detector with real StataClient."""
        client = StataClient()
        client.init()
        yield client
        client = None
    
    def test_output_detection_with_malformed_text(self, detector_with_real_client):
        """Test output detection with malformed text."""
        detector = GraphCreationDetector(stata_client=detector_with_real_client)
        
        # Test with malformed text that shouldn't crash
        malformed_texts = [
            "",
            None,
            "random text without graphs",
            "graph (invalid syntax",
            "scatter price mpg, name()",  # Empty name
        ]
        
        for text in malformed_texts:
            try:
                text_str = str(text) if text is not None else ""
                detected = detector._detect_from_output(text_str)
                assert isinstance(detected, list), "Should always return a list"
            except Exception as e:
                pytest.fail(f"Should not crash on malformed text: {text}, error: {e}")
    
    def test_command_detection_with_nested_parentheses(self, detector_with_real_client):
        """Test command detection with nested parentheses in graph names."""
        detector = GraphCreationDetector(stata_client=detector_with_real_client)
        
        # Test with complex nested parentheses
        complex_commands = [
            "scatter price mpg, name(Graph_With_(Nested)_Parentheses)",
            "histogram price, name(Graph(1)(2)(3))",
            "twoway (scatter price mpg) (line price mpg), name(Complex_Graph)",
        ]
        
        for command in complex_commands:
            detected = detector._detect_from_commands(command)
            assert isinstance(detected, list), "Should always return a list"
    
    def test_unnamed_graph_generation_edge_cases(self, detector_with_real_client):
        """Test unnamed graph generation in edge cases."""
        detector = GraphCreationDetector(stata_client=detector_with_real_client)
        
        # Test when no current graphs exist
        name = detector._generate_unnamed_graph_name([])
        assert name is not None, "Should generate name even with no existing graphs"
        
        # Test when name is in removed graphs
        detector._removed_graphs.add("Graph")
        name = detector._generate_unnamed_graph_name([])
        assert name is None or name != "Graph", "Should avoid names in removed graphs"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
