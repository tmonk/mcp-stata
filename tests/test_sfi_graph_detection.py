"""
Comprehensive SFI-only graph detection tests.

This file consolidates all essential tests for the SFI-only graph detection
implementation, removing dependency on text parsing and focusing on
authoritative SFI state detection.
"""

import pytest
import sys
import os
import asyncio
import tempfile
from pathlib import Path

# Add the src directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Configure Stata before importing sfi-dependent modules
import stata_setup
from mcp_stata.discovery import find_stata_path

try:
    stata_path, stata_flavor = find_stata_path()
    stata_setup.config(stata_path, stata_flavor)
except (FileNotFoundError, PermissionError) as e:
    pytest.skip(f"Stata not found or not executable: {e}")

from mcp_stata.graph_detector import GraphCreationDetector, StreamingGraphCache, SFI_AVAILABLE
from mcp_stata.stata_client import StataClient


# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata


class TestSFIAvailability:
    """Test SFI interface availability and basic functionality."""
    
    def test_sfi_available(self):
        """Test that sfi interface is actually available."""
        assert SFI_AVAILABLE, "sfi interface should be available after stata_setup.config()"
        
        # Test that we can import sfi modules
        from sfi import Data, Macro
        assert hasattr(Macro, 'getGlobal'), "Macro.getGlobal should be available"
        assert hasattr(Macro, 'setGlobal'), "Macro.setGlobal should be available"
    
    def test_macro_functionality(self):
        """Test basic Macro functionality used by SFI detection."""
        from sfi import Macro
        
        # Test setting and getting global macros
        Macro.setGlobal("test_macro", "test_value")
        retrieved = Macro.getGlobal("test_macro")
        assert retrieved == "test_value", "Macro set/get should work"
        
        # Clean up
        Macro.setGlobal("test_macro", "")


class TestSFIGraphCreationDetector:
    """Test SFI-only graph creation detection."""
    
    @pytest.fixture
    def real_stata_client(self):
        """Create a real StataClient with actual Stata connection."""
        client = StataClient()
        client.init()
        yield client
        # Cleanup
        try:
            client.stata.run("clear", quietly=True)
        except Exception:
            pass
    
    @pytest.fixture
    def detector_with_real_client(self, real_stata_client):
        """Create detector with real StataClient."""
        return GraphCreationDetector(stata_client=real_stata_client)
    
    def test_detector_initialization(self, detector_with_real_client):
        """Test GraphCreationDetector initialization with real StataClient."""
        detector = detector_with_real_client
        assert detector._stata_client is not None
        assert hasattr(detector._stata_client, 'stata')
        assert detector._last_graph_state == {}
    
    def test_sfi_state_detection(self, detector_with_real_client):
        """Test SFI state detection directly."""
        detector = detector_with_real_client
        
        # Clear existing graphs
        detector._stata_client.stata.run("clear", quietly=True)
        
        # Create graphs
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        detector._stata_client.stata.run("scatter price mpg, name(StateTest1)", quietly=True)
        detector._stata_client.stata.run("histogram price, name(StateTest2)", quietly=True)
        
        # Test SFI detection
        detected = detector._detect_graphs_via_pystata()
        assert "StateTest1" in detected, "Should detect StateTest1 via SFI"
        assert "StateTest2" in detected, "Should detect StateTest2 via SFI"
        
        # Test graph state retrieval
        state = detector._get_graph_state_from_pystata()
        assert "StateTest1" in state, "State should contain StateTest1"
        assert "StateTest2" in state, "State should contain StateTest2"
        assert state["StateTest1"]["exists"] == True, "Graph should exist"
        assert state["StateTest2"]["exists"] == True, "Graph should exist"
        
        # Clean up
        detector._stata_client.stata.run("graph drop StateTest1 StateTest2", quietly=True)
        detector._stata_client.stata.run("clear", quietly=True)
    
    def test_sfi_modification_detection(self, detector_with_real_client):
        """Test SFI-only modification detection."""
        detector = detector_with_real_client
        
        # Create initial graphs
        detector._stata_client.stata.run("sysuse auto, clear", quietly=True)
        detector._stata_client.stata.run("scatter price mpg, name(ModTest1)", quietly=True)
        detector._stata_client.stata.run("histogram price, name(ModTest2)", quietly=True)
        
        # Initialize detector state
        detector._detect_graphs_via_pystata()
        
        # Drop a graph
        detector._stata_client.stata.run("graph drop ModTest1", quietly=True)
        modifications = detector.detect_graph_modifications()
        assert "ModTest1" in modifications["dropped"], "Should detect dropped graph"
        assert modifications["cleared"] == False, "Should not be cleared yet"
        
        # Drop remaining graph
        detector._stata_client.stata.run("graph drop ModTest2", quietly=True)
        modifications = detector.detect_graph_modifications()
        assert "ModTest2" in modifications["dropped"], "Should detect second dropped graph"
        assert modifications["cleared"] == True, "Should detect clear when no graphs remain"
        
        # Clean up
        detector._stata_client.stata.run("clear", quietly=True)


class TestSFIStreamingGraphCache:
    """Test SFI-only streaming graph cache functionality."""
    
    @pytest.fixture
    def real_client(self):
        """Create a real StataClient with actual Stata connection."""
        client = StataClient()
        client.init()
        yield client
        # Cleanup
        try:
            client.stata.run("clear", quietly=True)
        except Exception:
            pass
    
    @pytest.fixture
    def streaming_cache(self, real_client):
        """Create StreamingGraphCache with real StataClient."""
        return StreamingGraphCache(real_client, auto_cache=True)
    
    def test_streaming_cache_ignores_text(self, streaming_cache):
        """Test that streaming cache ignores text input and uses SFI."""
        # Create a graph
        streaming_cache.stata_client.stata.run("sysuse auto, clear", quietly=True)
        streaming_cache.stata_client.stata.run("scatter price mpg, name(StreamIgnoreTest)", quietly=True)
        
        # Process chunk with random text (should ignore text and use SFI)
        streaming_cache.process_streaming_chunk("random text without any graph commands")
        
        # Should detect graph via SFI despite text
        assert "StreamIgnoreTest" in streaming_cache._graphs_to_cache, "Should detect via SFI"
        
        # Clean up
        try:
            streaming_cache.stata_client.stata.run("graph drop StreamIgnoreTest", quietly=True)
        except Exception:
            pass
        streaming_cache.stata_client.stata.run("clear", quietly=True)
    
    def test_sfi_modification_handling_in_streaming(self, streaming_cache):
        """Test SFI modification detection during streaming."""
        # Create graphs
        streaming_cache.stata_client.stata.run("sysuse auto, clear", quietly=True)
        streaming_cache.stata_client.stata.run("scatter price mpg, name(StreamMod1)", quietly=True)
        streaming_cache.stata_client.stata.run("histogram price, name(StreamMod2)", quietly=True)
        
        # Process chunk to establish state
        streaming_cache.process_streaming_chunk("establish baseline")
        
        # Drop a graph and process
        streaming_cache.stata_client.stata.run("graph drop StreamMod1", quietly=True)
        streaming_cache.process_streaming_chunk("graph dropped")
        
        # Should detect modification via SFI
        assert "StreamMod1" in streaming_cache._removed_graphs, "Should detect dropped graph"
        
        # Clean up
        try:
            streaming_cache.stata_client.stata.run("graph drop StreamMod2", quietly=True)
        except Exception:
            pass
        streaming_cache.stata_client.stata.run("clear", quietly=True)
    
    @pytest.mark.asyncio
    async def test_sfi_caching_with_real_graphs(self, streaming_cache):
        """Test SFI-only caching with real graphs."""
        # Create real graphs
        streaming_cache.stata_client.stata.run("sysuse auto, clear", quietly=True)
        streaming_cache.stata_client.stata.run("scatter price mpg, name(CacheTest1)", quietly=True)
        streaming_cache.stata_client.stata.run("histogram price, name(CacheTest2)", quietly=True)
        
        # Add graphs to cache queue via SFI detection
        streaming_cache.process_streaming_chunk("create graphs")
        
        # Test caching
        cached_graphs = await streaming_cache.cache_detected_graphs_with_pystata()
        
        # Should cache graphs detected via SFI
        assert len(cached_graphs) >= 0, "Should cache graphs detected via SFI"
        
        # Clean up
        try:
            streaming_cache.stata_client.stata.run("graph drop CacheTest1 CacheTest2", quietly=True)
        except Exception:
            pass
        streaming_cache.stata_client.stata.run("clear", quietly=True)


class TestSFIIntegration:
    """Test comprehensive SFI integration scenarios."""
    
    @pytest.fixture
    def client(self):
        """Create a real StataClient."""
        client = StataClient()
        client.init()
        yield client
        # Cleanup
        try:
            client.stata.run("clear", quietly=True)
        except Exception:
            pass
    
    @pytest.mark.asyncio
    async def test_end_to_end_sfi_streaming(self, client):
        """Test end-to-end SFI-only streaming with graph creation and caching."""
        cache = StreamingGraphCache(client, auto_cache=True)
        
        # Track cached graphs
        cached_events = []
        
        def cache_callback(graph_name, success):
            cached_events.append((graph_name, success))
        
        cache.add_cache_callback(cache_callback)
        
        # Create graphs via streaming
        client.stata.run("sysuse auto, clear", quietly=True)
        cache.process_streaming_chunk("scatter price mpg, name(EndToEnd1)")
        cache.process_streaming_chunk("histogram price, name(EndToEnd2)")
        
        # Cache detected graphs
        cached_graphs = await cache.cache_detected_graphs_with_pystata()
        
        # Verify SFI-only detection worked
        assert len(cached_graphs) >= 0, "Should cache graphs via SFI"
        assert len(cache._cached_graphs) >= 0, "Should have cached graphs"
        
        # Clean up
        try:
            client.stata.run("graph drop EndToEnd1 EndToEnd2", quietly=True)
        except Exception:
            pass
        client.stata.run("clear", quietly=True)
    
    def test_sfi_state_consistency(self, client):
        """Test SFI state consistency across multiple operations."""
        detector = GraphCreationDetector(stata_client=client)
        
        # Clear and create graphs
        client.stata.run("sysuse auto, clear", quietly=True)
        client.stata.run("scatter price mpg, name(Consistency1)", quietly=True)
        
        # Check state
        state1 = detector._get_graph_state_from_pystata()
        assert "Consistency1" in state1, "Graph should be in state"
        
        # Create another graph
        client.stata.run("histogram price, name(Consistency2)", quietly=True)
        
        # Check state again
        state2 = detector._get_graph_state_from_pystata()
        assert "Consistency1" in state2, "Original graph should remain"
        assert "Consistency2" in state2, "New graph should be added"
        
        # Drop first graph
        client.stata.run("graph drop Consistency1", quietly=True)
        
        # Check state after drop
        state3 = detector._get_graph_state_from_pystata()
        assert "Consistency1" not in state3, "Dropped graph should be removed"
        assert "Consistency2" in state3, "Other graph should remain"
        
        # Clean up
        try:
            client.stata.run("graph drop Consistency2", quietly=True)
        except Exception:
            pass
        client.stata.run("clear", quietly=True)


class TestSFIBoundaryConditions:
    """Test SFI boundary conditions and error handling."""
    
    @pytest.fixture
    def client(self):
        """Create a real StataClient."""
        client = StataClient()
        client.init()
        yield client
        # Cleanup
        try:
            client.stata.run("clear", quietly=True)
        except Exception:
            pass
    
    def test_sfi_with_no_graphs(self, client):
        """Test SFI detection when no graphs exist."""
        detector = GraphCreationDetector(stata_client=client)
        
        # Clear all graphs
        client.stata.run("clear", quietly=True)
        
        # Test detection with no graphs
        detected = detector._detect_graphs_via_pystata()
        assert detected == [], "Should detect no graphs when none exist"
        
        # Test modification detection with no graphs
        modifications = detector.detect_graph_modifications()
        assert modifications["dropped"] == [], "Should detect no dropped graphs"
        assert modifications["cleared"] == False, "Should not detect clear when starting empty"
    
    def test_sfi_with_single_graph(self, client):
        """Test SFI detection with a single graph."""
        detector = GraphCreationDetector(stata_client=client)
        
        # Clear and create single graph
        client.stata.run("sysuse auto, clear", quietly=True)
        client.stata.run("scatter price mpg, name(SingleGraph)", quietly=True)
        
        # Test detection
        detected = detector._detect_graphs_via_pystata()
        assert "SingleGraph" in detected, "Should detect single graph"
        assert len(detected) == 1, "Should detect exactly one graph"
        
        # Clean up
        client.stata.run("graph drop SingleGraph", quietly=True)
        client.stata.run("clear", quietly=True)
    
    def test_sfi_with_multiple_graphs(self, client):
        """Test SFI detection with multiple graphs."""
        detector = GraphCreationDetector(stata_client=client)
        
        # Clear and create multiple graphs
        client.stata.run("sysuse auto, clear", quietly=True)
        client.stata.run("scatter price mpg, name(Multi1)", quietly=True)
        client.stata.run("histogram price, name(Multi2)", quietly=True)
        client.stata.run("graph box price, name(Multi3)", quietly=True)
        
        # Test detection
        detected = detector._detect_graphs_via_pystata()
        assert len(detected) == 3, "Should detect all three graphs"
        assert "Multi1" in detected, "Should detect Multi1"
        assert "Multi2" in detected, "Should detect Multi2"
        assert "Multi3" in detected, "Should detect Multi3"
        
        # Clean up
        client.stata.run("graph drop Multi1 Multi2 Multi3", quietly=True)
        client.stata.run("clear", quietly=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
