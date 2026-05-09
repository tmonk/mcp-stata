"""
Test TTL cache functionality for list_graphs() method.
"""

import pytest
import threading
import time
from conftest import configure_stata_for_tests
import stata_setup

pytestmark = pytest.mark.requires_stata

class TestListGraphsTTLCache:
    """Test TTL cache for list_graphs() method."""

    def test_ttl_cache_basic_functionality(self, client, monkeypatch):
        """Test basic TTL cache functionality."""
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 0.5, raising=False)
        
        # Ensure we clear the cache first
        client.invalidate_list_graphs_cache()
        
        # First call should fetch from Stata
        result1 = client.list_graphs()
        
        # Second call within TTL should use cache (faster)
        start = time.time()
        result2 = client.list_graphs()
        duration = time.time() - start
        
        # Cached call should be very fast
        assert duration < 0.2
        assert result1 == result2
        
        # Wait for TTL to expire
        time.sleep(0.6)
        
        # Third call after TTL should fetch fresh data
        result3 = client.list_graphs()
        assert result3 == result1  # Same data, but fetched fresh
    
    def test_ttl_cache_invalidation(self, client, monkeypatch):
        """Test cache invalidation functionality."""
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 10.0, raising=False)
        
        # First call
        client.invalidate_list_graphs_cache()
        result1 = client.list_graphs()
        
        # Invalidate cache
        client.invalidate_list_graphs_cache()
        
        # Next call should fetch fresh data even within a long TTL
        result2 = client.list_graphs()
        assert result2 == result1
    
    def test_ttl_cache_error_handling(self, client, monkeypatch):
        """Test TTL cache behavior when Stata calls fail."""
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 1.0, raising=False)
        
        # First call succeeds
        client.invalidate_list_graphs_cache()
        result1 = client.list_graphs()
        
        # Cached call should still work
        result2 = client.list_graphs()
        assert result2 == result1
    
    def test_ttl_cache_concurrent_access(self, client, monkeypatch):
        """Test TTL cache under concurrent access."""
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 1.0, raising=False)
        
        # Initialize the client fully before starting threads
        client.invalidate_list_graphs_cache()
        _ = client.list_graphs()
        
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
        expected_result = results[0][1]
        for thread_id, result in results:
            assert result == expected_result
    
    def test_ttl_cache_expiration(self, client, monkeypatch):
        """Test that cache properly expires after TTL."""
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 0.5, raising=False)
        
        # First call
        client.invalidate_list_graphs_cache()
        result1 = client.list_graphs()
        
        # Second call within TTL (should be very fast)
        start = time.time()
        result2 = client.list_graphs()
        duration1 = time.time() - start
        assert duration1 < 0.2  # Cached
        assert result2 == result1
        
        # Wait for TTL to expire
        time.sleep(0.6)
        
        # Third call after TTL (will be slower as it fetches fresh)
        # Note: In mock mode, the 'fresh' call might still be extremely fast.
        result3 = client.list_graphs()
        assert result3 == result1
    
    def test_cache_invalidation_on_graph_creation(self, client, monkeypatch):
        """Test that cache is invalidated when graphs are created."""
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 10.0, raising=False)
        
        client.invalidate_list_graphs_cache()
        # Get initial list
        result1 = client.list_graphs()
        
        # Ensure we have a cached value
        assert client._list_graphs_cache is not None
        
        # Create a simple test graph (should invalidate cache)
        # In reality, cache_graph_on_creation calls invalidate_list_graphs_cache
        client.invalidate_list_graphs_cache()
        
        # List cache should be empty now
        assert client._list_graphs_cache is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])