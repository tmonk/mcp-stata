"""
Test TTL cache functionality for list_graphs() method.
"""

import pytest
import threading
import time
from unittest.mock import Mock, patch

from mcp_stata.stata_client import StataClient


class TestListGraphsTTLCache:
    """Test TTL cache for list_graphs() method."""
    
    @pytest.fixture
    def mock_stata_client(self):
        """Create a mock StataClient with TTL cache."""
        client = Mock(spec=StataClient)
        client._initialized = True
        client._list_graphs_cache = None
        client._list_graphs_cache_time = 0
        client._list_graphs_cache_lock = threading.Lock()
        client.LIST_GRAPHS_TTL = 0.075  # 75ms TTL for testing
        return client
    
    def test_ttl_cache_basic_functionality(self):
        """Test basic TTL cache functionality."""
        # Create a real StataClient instance for testing
        client = StataClient()
        client._initialized = True
        client.LIST_GRAPHS_TTL = 0.075  # 75ms TTL
        
        # Initialize cache attributes manually since we're bypassing full init
        client._list_graphs_cache = None
        client._list_graphs_cache_time = 0
        client._list_graphs_cache_lock = threading.Lock()
        
        # Mock the stata interface and set it as an attribute
        mock_stata = Mock()
        client.stata = mock_stata
        mock_macro = Mock()
        
        with patch('src.mcp_stata.stata_client.time.time') as mock_time:
            with patch('sfi.Macro', mock_macro):
                
                # Setup time progression
                time_values = [0.0, 0.05, 0.1, 0.15]  # 0ms, 50ms, 100ms, 150ms
                mock_time.side_effect = time_values
                
                # Setup mock responses
                mock_macro.getGlobal.return_value = "graph1 graph2 graph3"
                
                # First call should fetch from Stata
                result1 = client.list_graphs()
                assert result1 == ["graph1", "graph2", "graph3"]
                assert mock_stata.run.call_count == 2  # "quietly graph dir" + "global mcp_graph_list"
                
                # Second call within TTL should use cache
                result2 = client.list_graphs()
                assert result2 == ["graph1", "graph2", "graph3"]
                assert mock_stata.run.call_count == 2  # No additional calls
                
                # Third call after TTL should fetch fresh data
                result3 = client.list_graphs()
                assert result3 == ["graph1", "graph2", "graph3"]
                assert mock_stata.run.call_count == 4  # 2 additional calls
    
    def test_ttl_cache_invalidation(self):
        """Test cache invalidation functionality."""
        client = StataClient()
        client._initialized = True
        client.LIST_GRAPHS_TTL = 0.075
        
        # Initialize cache attributes manually since we're bypassing full init
        client._list_graphs_cache = None
        client._list_graphs_cache_time = 0
        client._list_graphs_cache_lock = threading.Lock()
        
        mock_stata = Mock()
        client.stata = mock_stata
        mock_macro = Mock()
        
        with patch('src.mcp_stata.stata_client.time.time') as mock_time:
            with patch('sfi.Macro', mock_macro):
                
                # Setup time progression
                time_values = [0.0, 0.05, 0.06, 0.07]
                mock_time.side_effect = time_values
                
                # Setup mock responses
                mock_macro.getGlobal.return_value = "graph1 graph2"
                
                # First call
                result1 = client.list_graphs()
                assert result1 == ["graph1", "graph2"]
                assert mock_stata.run.call_count == 2
                
                # Invalidate cache
                client.invalidate_list_graphs_cache()
                
                # Next call should fetch fresh data even within TTL
                result2 = client.list_graphs()
                assert result2 == ["graph1", "graph2"]
                assert mock_stata.run.call_count == 4  # 2 additional calls
    
    def test_ttl_cache_error_handling(self):
        """Test TTL cache behavior when Stata calls fail."""
        client = StataClient()
        client._initialized = True
        client.LIST_GRAPHS_TTL = 0.075
        
        # Initialize cache attributes manually since we're bypassing full init
        client._list_graphs_cache = None
        client._list_graphs_cache_time = 0
        client._list_graphs_cache_lock = threading.Lock()
        
        mock_stata = Mock()
        client.stata = mock_stata
        mock_macro = Mock()
        
        with patch('src.mcp_stata.stata_client.time.time') as mock_time:
            with patch('sfi.Macro', mock_macro):
                
                # Setup time progression
                time_values = [0.0, 0.05, 0.1]
                mock_time.side_effect = time_values
                
                # First call succeeds
                mock_macro.getGlobal.return_value = "graph1 graph2"
                result1 = client.list_graphs()
                assert result1 == ["graph1", "graph2"]
                
                # Second call fails, should return cached result
                mock_stata.run.side_effect = Exception("Stata error")
                result2 = client.list_graphs()
                assert result2 == ["graph1", "graph2"]  # Should return cached result
                
                # Third call with no cache should return empty list
                client.invalidate_list_graphs_cache()
                result3 = client.list_graphs()
                assert result3 == []  # No cache available
    
    def test_ttl_cache_concurrent_access(self):
        """Test TTL cache under concurrent access."""
        client = StataClient()
        client._initialized = True
        client.LIST_GRAPHS_TTL = 0.1  # 100ms TTL for concurrent test
        
        # Initialize cache attributes manually since we're bypassing full init
        client._list_graphs_cache = None
        client._list_graphs_cache_time = 0
        client._list_graphs_cache_lock = threading.Lock()
        
        mock_stata = Mock()
        client.stata = mock_stata
        mock_macro = Mock()
        
        with patch('src.mcp_stata.stata_client.time.time') as mock_time:
            with patch('sfi.Macro', mock_macro):
                
                # Setup time progression - all calls within same time window
                mock_time.return_value = 1.0
                
                # Setup mock response
                mock_macro.getGlobal.return_value = "graph1 graph2 graph3"
                
                results = []
                errors = []
                
                def concurrent_call(thread_id):
                    try:
                        result = client.list_graphs()
                        results.append((thread_id, result))
                    except Exception as e:
                        errors.append((thread_id, str(e)))
                
                # Start multiple threads
                threads = []
                for thread_id in range(10):
                    thread = threading.Thread(target=concurrent_call, args=(thread_id,))
                    threads.append(thread)
                    thread.start()
                
                # Wait for all threads
                for thread in threads:
                    thread.join()
                
                # Verify results
                assert len(errors) == 0
                assert len(results) == 10
                
                # All results should be identical
                expected_result = ["graph1", "graph2", "graph3"]
                for thread_id, result in results:
                    assert result == expected_result
                
                # Stata should only be called once (first thread populates cache)
                assert mock_stata.run.call_count == 2  # "quietly graph dir" + "global mcp_graph_list"
    
    def test_ttl_cache_expiration(self):
        """Test that cache properly expires after TTL."""
        client = StataClient()
        client._initialized = True
        client.LIST_GRAPHS_TTL = 0.05  # 50ms TTL
        
        # Initialize cache attributes manually since we're bypassing full init
        client._list_graphs_cache = None
        client._list_graphs_cache_time = 0
        client._list_graphs_cache_lock = threading.Lock()
        
        mock_stata = Mock()
        client.stata = mock_stata
        mock_macro = Mock()
        
        with patch('src.mcp_stata.stata_client.time.time') as mock_time:
            with patch('sfi.Macro', mock_macro):
                
                # Setup time progression with exact TTL boundary
                time_values = [0.0, 0.04, 0.11, 0.17]  # Before TTL, after TTL, well after TTL, very well after TTL
                mock_time.side_effect = time_values
                
                # Setup different responses for different calls
                responses = ["graph1 graph2", "graph3 graph4", "graph5 graph6"]
                call_count = 0
                def get_side_effect(*args):
                    nonlocal call_count
                    result = responses[call_count % len(responses)]
                    call_count += 1
                    return result
                
                mock_macro.getGlobal.side_effect = get_side_effect
                
                # First call (t=0.0)
                result1 = client.list_graphs()
                assert result1 == ["graph1", "graph2"]
                
                # Second call within TTL (t=0.04)
                result2 = client.list_graphs()
                assert result2 == ["graph1", "graph2"]  # Should use cache
                
                # Third call after TTL (t=0.11) - well after TTL boundary
                result3 = client.list_graphs()
                assert result3 == ["graph3", "graph4"]  # Should fetch fresh data
                
                # Fourth call very well after TTL (t=0.17) - should fetch fresh data again
                result4 = client.list_graphs()
                assert result4 == ["graph5", "graph6"]  # Should fetch fresh data again
                
                # Verify Stata was called appropriately
                assert mock_stata.run.call_count == 6  # 2 calls per fresh fetch
    
    def test_cache_invalidation_on_graph_creation(self):
        """Test that cache is invalidated when graphs are created."""
        client = StataClient()
        client._initialized = True
        client.LIST_GRAPHS_TTL = 0.075
        
        # Initialize cache attributes manually since we're bypassing full init
        client._list_graphs_cache = None
        client._list_graphs_cache_time = 0
        client._list_graphs_cache_lock = threading.Lock()
        
        mock_stata = Mock()
        client.stata = mock_stata
        mock_macro = Mock()
        
        with patch('src.mcp_stata.stata_client.time.time') as mock_time:
            with patch('sfi.Macro', mock_macro):
                
                # Setup time progression
                time_values = [0.0, 0.05, 0.06, 0.07]
                mock_time.side_effect = time_values
                
                # Setup mock responses
                mock_macro.getGlobal.return_value = "graph1 graph2"
                
                # First call
                result1 = client.list_graphs()
                assert result1 == ["graph1", "graph2"]
                assert mock_stata.run.call_count == 2
                
                # Mock successful graph caching
                with patch.object(client, '_initialize_cache'):
                    with patch.object(client, '_is_cache_valid', return_value=False):
                        with patch.object(client, '_sanitize_filename', return_value='test_graph'):
                            with patch('tempfile.mkdtemp', return_value='/tmp/test'):
                                with patch('builtins.open', create=True) as mock_open:
                                    mock_file = Mock()
                                    mock_open.return_value.__enter__.return_value = mock_file
                                    
                                    # Call cache_graph_on_creation which should invalidate cache
                                    try:
                                        client.cache_graph_on_creation("test_graph")
                                    except:
                                        pass  # Expected to fail due to mocking
                
                # Next call should fetch fresh data due to cache invalidation
                mock_macro.getGlobal.return_value = "graph1 graph2 test_graph"
                result2 = client.list_graphs()
                assert result2 == ["graph1", "graph2", "test_graph"]
                assert mock_stata.run.call_count == 4  # Should have called Stata again


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
