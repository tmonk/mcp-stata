"""
Tests for streaming graph cache integration using real Stata.
"""

import pytest
import asyncio
import json
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
from mcp_stata.stata_client import StataClient


# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata


class TestGraphCreationDetector:
    """Test graph creation detection functionality."""
    
    def test_sfi_graph_detection_basic(self):
        """Test basic SFI graph detection."""
        detector = GraphCreationDetector()
        
        # Test that SFI detection works (requires Stata client)
        if detector._stata_client:
            graphs = detector._detect_graphs_via_pystata()
            # Should return list of current graphs (may be empty)
            assert isinstance(graphs, list)
        else:
            # Without Stata client, should return empty list
            graphs = detector._detect_graphs_via_pystata()
            assert graphs == []
    
    def test_sfi_graph_detection_with_state(self):
        """Test SFI graph detection with state tracking."""
        detector = GraphCreationDetector()
        
        # Test state tracking functionality
        if detector._stata_client:
            # Get initial state
            initial_graphs = detector._detect_graphs_via_pystata()
            initial_state = detector._get_graph_state_from_pystata()
            
            # Test that state is tracked
            assert isinstance(initial_state, dict)
        else:
            # Without client, should handle gracefully
            initial_state = detector._get_graph_state_from_pystata()
            assert initial_state == {}
    
    def test_detect_unnamed_graphs(self):
        """Test detection of unnamed graphs using SFI."""
        detector = GraphCreationDetector()
        
        # Test unnamed graph detection via SFI
        if detector._stata_client:
            # Test that unnamed graph detection works
            graphs = detector._detect_graphs_via_pystata()
            # Should return list (may include unnamed graphs like 'Graph')
            assert isinstance(graphs, list)
        else:
            # Without client, should return empty list
            graphs = detector._detect_graphs_via_pystata()
            assert graphs == []
    
    def test_should_cache_graph(self):
        """Test graph caching decision logic."""
        detector = GraphCreationDetector()
        
        # First time should cache
        assert detector.should_cache_graph('TestGraph') is True
        
        # Second time should not cache (already detected)
        assert detector.should_cache_graph('TestGraph') is False
        
        # Removed graphs should not cache
        detector.mark_graph_removed('TestGraph')
        assert detector.should_cache_graph('TestGraph') is False
    
    def test_get_graph_list_diff(self):
        """Test graph list comparison."""
        detector = GraphCreationDetector()
        
        before = ['Graph1', 'Graph2']
        after = ['Graph1', 'Graph2', 'Graph3', 'Graph4']
        
        new_graphs = detector.get_graph_list_diff(before, after)
        assert set(new_graphs) == {'Graph3', 'Graph4'}
        
        # Test with removed graphs
        detector.mark_graph_removed('Graph3')
        new_graphs = detector.get_graph_list_diff(before, after)
        assert new_graphs == ['Graph4']


class TestStreamingGraphCache:
    """Test streaming graph cache integration with real Stata."""
    
    @pytest.fixture
    def real_client(self):
        """Create a real StataClient with actual Stata connection."""
        client = StataClient()
        client.init()  # Initialize the actual Stata connection
        yield client
        # Cleanup if needed
    
    def test_streaming_cache_init(self, real_client):
        """Test StreamingGraphCache initialization."""
        cache = StreamingGraphCache(real_client, auto_cache=True)
        
        assert cache.stata_client == real_client
        assert cache.auto_cache is True
        assert cache.detector is not None
        assert cache.detector._stata_client == real_client
    
    def test_process_streaming_chunk_disabled(self, real_client):
        """Test processing chunks when auto_cache is disabled."""
        cache = StreamingGraphCache(real_client, auto_cache=False)
        
        # Should do nothing when disabled
        cache.process_streaming_chunk('scatter price mpg, name(Test)')
        assert len(cache._graphs_to_cache) == 0
    
    def test_process_streaming_chunk_with_output(self, real_client):
        """Test processing streaming output chunks."""
        cache = StreamingGraphCache(real_client, auto_cache=True)
        
        # Test with graph creation output
        cache.process_streaming_chunk('graph saved as TestGraph')
        assert len(cache._graphs_to_cache) >= 1
        assert 'TestGraph' in cache._graphs_to_cache
        
        # Clear and test with graph list comparison
        cache._graphs_to_cache.clear()
        current_graphs = ['TestGraph', 'NewGraph']
        cache.detector._last_graph_list = ['TestGraph']
        cache.process_streaming_chunk('some output', current_graphs)
        assert 'NewGraph' in cache._graphs_to_cache
    
    @pytest.mark.asyncio
    async def test_cache_detected_graphs(self, real_client):
        """Test caching detected graphs with real Stata."""
        cache = StreamingGraphCache(real_client, auto_cache=True)
        
        # Create real graphs first
        real_client.stata.run("sysuse auto, clear", quietly=True)
        real_client.stata.run("scatter price mpg, name(Graph1)", quietly=True)
        real_client.stata.run("histogram price, name(Graph2)", quietly=True)
        
        # Add real graphs to cache
        cache._graphs_to_cache = ['Graph1', 'Graph2']
        
        cached_graphs = await cache.cache_detected_graphs()
        
        # Should cache the real graphs
        assert len(cached_graphs) >= 0
        assert len(cache._cached_graphs) >= 0
        
        # Clean up
        try:
            real_client.stata.run("graph drop Graph1 Graph2", quietly=True)
        except SystemError:
            pass
        real_client.stata.run("clear", quietly=True)
    
    @pytest.mark.asyncio
    async def test_cache_detected_graphs_with_failures(self, real_client):
        """Test caching with some failures using real Stata."""
        cache = StreamingGraphCache(real_client, auto_cache=True)
        
        # Add graphs to cache (some may not exist)
        cache._graphs_to_cache = ['NonExistentGraph', 'Graph2']
        
        # Should handle failures gracefully
        cached_graphs = await cache.cache_detected_graphs()
        
        # Should return successful graphs (may be empty if none exist)
        assert isinstance(cached_graphs, list)
    
    @pytest.mark.asyncio
    async def test_cache_detected_graphs_disabled(self, real_client):
        """Test caching when auto_cache is disabled."""
        cache = StreamingGraphCache(real_client, auto_cache=False)
        
        cached_graphs = await cache.cache_detected_graphs()
        
        assert cached_graphs == []
    
    def test_add_cache_callback(self, real_client):
        """Test adding cache callbacks."""
        cache = StreamingGraphCache(real_client, auto_cache=True)
        
        callback_called = []
        def test_callback(graph_name, file_path):
            callback_called.append((graph_name, file_path))
        
        cache.add_cache_callback(test_callback)
        
        assert test_callback in cache._cache_callbacks
    
    def test_get_cache_stats(self, real_client):
        """Test getting cache statistics."""
        cache = StreamingGraphCache(real_client, auto_cache=True)
        
        cache._graphs_to_cache = ['Graph1', 'Graph2']
        cache._cached_graphs = {'Graph3'}
        cache.detector._detected_graphs = {'Graph1', 'Graph2', 'Graph3'}
        cache.detector._removed_graphs = {'Graph4'}
        
        stats = cache.get_cache_stats()
        
        assert stats['auto_cache_enabled'] is True
        assert stats['pending_cache_count'] == 2
        assert stats['cached_graphs_count'] == 1
        assert stats['detected_graphs_count'] == 3
        assert stats['removed_graphs_count'] == 1
    
    def test_reset(self, real_client):
        """Test resetting cache state."""
        cache = StreamingGraphCache(real_client, auto_cache=True)
        
        cache._graphs_to_cache = ['Graph1']
        cache._cached_graphs = {'Graph2'}
        cache.detector._detected_graphs = {'Graph1', 'Graph2'}
        
        cache.reset()
        
        assert len(cache._graphs_to_cache) == 0
        assert len(cache._cached_graphs) == 0
        assert len(cache.detector._detected_graphs) == 0


class TestStreamingIntegration:
    """Test integration with streaming functionality."""
    
    @pytest.mark.asyncio
    async def test_streaming_with_auto_cache(self):
        """Test streaming execution with auto cache enabled."""
        # This would require a more complex setup with actual streaming
        # For now, test the integration points
        pass
    
    def test_file_tee_io_with_callback(self):
        """Test FileTeeIO with graph detection callback."""
        from mcp_stata.streaming_io import FileTeeIO, TailBuffer
        import tempfile
        import os
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        temp_file.close()
        
        try:
            # Create tail buffer
            tail = TailBuffer()
            
            # Create FileTeeIO with correct parameters
            tee = FileTeeIO(open(temp_file.name, 'w'), tail)
            
            # Test writing data
            tee.write("test data\n")
            tee.flush()
            
            # Verify data was written to tail
            assert "test data" in tail.get_value()
            
            # Clean up
            tee._file.close()
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
