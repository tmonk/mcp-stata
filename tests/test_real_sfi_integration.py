"""
Tests for enhanced pystata integration using actual sfi interface (no mocks).
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

from mcp_stata.graph_detector import GraphCreationDetector, StreamingGraphCache, SFI_AVAILABLE

# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata

class TestRealSFIIntegration:
    """Test pystata integration with actual sfi interface."""
    
    @pytest.fixture
    def detector_with_real_client(self, client):
        """Create detector with shared StataClient."""
        return GraphCreationDetector(stata_client=client)
    
    def test_sfi_available(self):
        """Test that sfi interface is actually available."""
        assert SFI_AVAILABLE, "sfi interface should be available after stata_setup.config()"
        
        # Test that we can import sfi modules
        from sfi import Data, Macro
        assert hasattr(Macro, 'getGlobal'), "Macro.getGlobal should be available"
        assert hasattr(Macro, 'setGlobal'), "Macro.setGlobal should be available"
    
    def test_macro_get_global_functionality(self):
        """Test actual Macro.getGlobal functionality."""
        from sfi import Macro
        
        # Set a test global macro
        Macro.setGlobal("test_macro", "test_value")
        
        # Retrieve the macro
        value = Macro.getGlobal("test_macro")
        assert value == "test_value", "Should be able to set and get global macros"
        
        # Clean up
        Macro.setGlobal("test_macro", "")
    
    def test_get_current_graphs_from_pystata_real(self, detector_with_real_client, client):
        """Test _get_current_graphs_from_pystata with real Stata connection."""
        detector = detector_with_real_client
        
        # Initially no graphs should be present
        graphs = detector._get_current_graphs_from_pystata()
        assert isinstance(graphs, list), "Should return a list"
        
        # Clear existing graphs and reset detector state
        client.stata.run("graph drop _all", quietly=True)
        client.stata.run("clear", quietly=True)
        detector.clear_detection_state()
        
        # Create a simple graph to test detection
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        detector._stata_client.stata.run("scatter price mpg, name(TestGraph)", quietly=True)
        
        # Now should detect the graph
        graphs = detector._get_current_graphs_from_pystata()
        assert "TestGraph" in graphs, f"Should detect TestGraph, found: {graphs}"
        
        # Clean up
        client.stata.run("graph drop TestGraph", quietly=True)
        client.stata.run("clear", quietly=True)
    
    def test_graph_state_detection_real(self, detector_with_real_client, client):
        """Test _get_graph_state_from_pystata with real Stata connection."""
        detector = detector_with_real_client
        
        # Clear existing graphs and reset detector state
        detector._stata_client.stata.run("graph drop _all", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
        detector.clear_detection_state()
        
        # Create a graph
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        detector._stata_client.stata.run("scatter price mpg, name(StateTestGraph)", quietly=True)
        
        # Get graph state
        state = detector._get_graph_state_from_pystata()
        
        assert isinstance(state, dict), "Should return a dictionary"
        assert "StateTestGraph" in state, "Should contain our test graph"
        
        graph_info = state["StateTestGraph"]
        assert graph_info["name"] == "StateTestGraph", "Should have correct name"
        assert graph_info["exists"] == True, "Should show graph exists"
        assert "timestamp" in graph_info, "Should have timestamp"
        
        # Clean up
        client.stata.run("graph drop StateTestGraph", quietly=True)
        client.stata.run("clear", quietly=True)
    
    def test_detect_graphs_via_pystata_real(self, detector_with_real_client, client):
        """Test _detect_graphs_via_pystata with real Stata connection."""
        detector = detector_with_real_client
        
        # Clear any existing graphs and reset detector state
        detector._stata_client.stata.run("graph drop _all", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
        detector.clear_detection_state()
        
        # Create a graph
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        detector._stata_client.stata.run("scatter price mpg, name(PystataTest)", quietly=True)
        
        # Detect graphs via pystata
        detected = detector._detect_graphs_via_pystata()
        
        assert isinstance(detected, list), "Should return a list"
        assert "PystataTest" in detected, f"Should detect PystataTest, found: {detected}"
        
        # Clean up
        client.stata.run("graph drop PystataTest", quietly=True)
        client.stata.run("clear", quietly=True)
    
    def test_sfi_graph_detection_integration_real(self, detector_with_real_client, client):
        """Test full SFI graph detection integration with real Stata."""
        detector = detector_with_real_client
        
        # Clear existing graphs and reset detector state
        detector._stata_client.stata.run("graph drop _all", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
        detector.clear_detection_state()
        
        # Test SFI detection with real Stata
        detected = detector._detect_graphs_via_pystata()
        assert isinstance(detected, list)
        
        # Test state tracking
        state = detector._get_graph_state_from_pystata()
        assert isinstance(state, dict)
        
        # Create a graph via command
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        output = detector._stata_client.stata.run("scatter price mpg, name(IntegrationTest)", quietly=True)
        
        # Detect using SFI integration
        detected = detector._detect_graphs_via_pystata()
        
        assert isinstance(detected, list), "Should return a list"
        assert "IntegrationTest" in detected, f"Should detect IntegrationTest, found: {detected}"
        
        # Clean up
        client.stata.run("graph drop IntegrationTest", quietly=True)
        client.stata.run("clear", quietly=True)
    
        
    def test_multiple_graph_detection_real(self, detector_with_real_client, client):
        """Test detecting multiple graphs created in sequence."""
        detector = detector_with_real_client
        
        # Clear existing graphs and reset detector state
        detector._stata_client.stata.run("graph drop _all", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
        detector.clear_detection_state()
        
        # Create multiple graphs using valid Stata commands
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        detector._stata_client.stata.run("scatter price mpg, name(Graph1)", quietly=True)
        detector._stata_client.stata.run("histogram price, name(Graph2)", quietly=True)
        detector._stata_client.stata.run("graph bar price, name(Graph3)", quietly=True)
        
        # Detect all graphs
        detected = detector._detect_graphs_via_pystata()
        
        assert isinstance(detected, list), "Should return a list"
        assert len(detected) >= 3, f"Should detect at least 3 graphs, found: {detected}"
        assert "Graph1" in detected, "Should detect Graph1"
        assert "Graph2" in detected, "Should detect Graph2" 
        assert "Graph3" in detected, "Should detect Graph3"
        
        # Clean up
        detector._stata_client.stata.run("graph drop _all", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
    
    def test_graph_modification_detection_real(self, detector_with_real_client):
        """Test detecting when graphs are modified."""
        detector = detector_with_real_client
        
        # Clear existing graphs and reset detector state
        detector._stata_client.stata.run("graph drop _all", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
        detector.clear_detection_state()
        
        # Create initial graph
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        detector._stata_client.stata.run("scatter price mpg, name(ModifyTest)", quietly=True)
        
        # Get initial state
        initial_state = detector._get_graph_state_from_pystata()
        initial_timestamp = initial_state["ModifyTest"]["timestamp"]
        
        # Wait a bit to ensure different timestamp
        import time
        time.sleep(0.1)
        
        # Modify the graph by dropping and recreating with different content
        detector._stata_client.stata.run("graph drop ModifyTest", quietly=True)
        detector._stata_client.stata.run("scatter price weight, name(ModifyTest)", quietly=True)
        
        # Get new state
        new_state = detector._get_graph_state_from_pystata()
        new_timestamp = new_state["ModifyTest"]["timestamp"]
        
        # Should have different timestamp (indicating modification)
        assert new_timestamp > initial_timestamp, "Graph modification should update timestamp"
        
        # Clean up
        detector._stata_client.stata.run("graph drop ModifyTest", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
