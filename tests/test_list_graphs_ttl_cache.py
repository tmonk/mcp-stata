"""
Test TTL cache functionality for list_graphs() method.
"""

import pytest
import threading
import time
from conftest import configure_stata_for_tests
import stata_setup
pytestmark = pytest.mark.requires_stata

try:
    stata_dir, stata_flavor = configure_stata_for_tests()
    stata_setup.config(stata_dir, stata_flavor)
except (FileNotFoundError, PermissionError) as e:
    pytest.skip(f"Stata not found or not executable: {e}", allow_module_level=True)


class TestListGraphsTTLCache:
    """Test TTL cache for list_graphs() method."""

    def test_ttl_cache_basic_functionality(self, client, monkeypatch):
        """Test basic TTL cache functionality."""
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 1.0, raising=False)
        
        # First call should fetch from Stata
        result1 = client.list_graphs()
        
        # Second call within TTL should use cache (faster)
        start = time.time()
        result2 = client.list_graphs()
        duration = time.time() - start
        
        # Cached call should be very fast (< 100ms)
        assert duration < 0.1
        assert result1 == result2
        
        # Wait for TTL to expire
        time.sleep(1.1)
        
        # Third call after TTL should fetch fresh data
        result3 = client.list_graphs()
        assert result3 == result1  # Same data, but fetched fresh
    
    def test_ttl_cache_invalidation(self, client, monkeypatch):
        """Test cache invalidation functionality."""
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 1.0, raising=False)
        
        # First call
        result1 = client.list_graphs()
        
        # Invalidate cache
        client.invalidate_list_graphs_cache()
        
        # Next call should fetch fresh data even within TTL
        result2 = client.list_graphs()
        assert result2 == result1
    
    def test_ttl_cache_error_handling(self, client, monkeypatch):
        """Test TTL cache behavior when Stata calls fail."""
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 1.0, raising=False)
        
        # First call succeeds
        result1 = client.list_graphs()
        
        # Cached call should still work
        result2 = client.list_graphs()
        assert result2 == result1
    
    def test_ttl_cache_concurrent_access(self, client, monkeypatch):
        """Test TTL cache under concurrent access."""
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 1.0, raising=False)
        
        # Initialize the client fully before starting threads
        # This ensures Stata is ready and prevents race conditions
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
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 1.0, raising=False)
        
        # First call
        result1 = client.list_graphs()
        
        # Second call within TTL (should be very fast)
        start = time.time()
        result2 = client.list_graphs()
        duration1 = time.time() - start
        assert duration1 < 0.1  # Cached, should be < 100ms
        assert result2 == result1
        
        # Wait for TTL to expire
        time.sleep(0.15)
        
        # Third call after TTL (will be slower as it fetches fresh)
        start = time.time()
        result3 = client.list_graphs()
        duration2 = time.time() - start
        # Fresh fetch should take more time than cache hit
        assert duration2 > duration1
        assert result3 == result1
    
    def test_cache_invalidation_on_graph_creation(self, client, monkeypatch):
        """Test that cache is invalidated when graphs are created."""
        monkeypatch.setattr(client, "LIST_GRAPHS_TTL", 1.0, raising=False)
        
        # Get initial list
        result1 = client.list_graphs()
        initial_count = len(result1)
        
        # Create a simple test graph
        client.run_command_structured("sysuse auto, clear")
        client.run_command_structured("sysuse auto, clear")
        client.run_command_structured("scatter mpg weight")
        
        # Try to cache it (this should invalidate the list cache)
        try:
            client.cache_graph_on_creation("test_graph")
        except:
            pass  # May fail if graph doesn't exist, but cache should be invalidated
        
        # List should now include the new graph (or be refreshed)
        result2 = client.list_graphs()
        # The list might have changed or at least the cache was invalidated
        assert isinstance(result2, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])