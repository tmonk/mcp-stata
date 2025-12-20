"""
Comprehensive tests for concurrent access and error recovery in streaming graph caching.
"""

import pytest
import asyncio
import threading
import time
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor, as_completed

# Mock the Stata dependencies to avoid import errors
import sys
sys.modules['sfi'] = Mock()
sys.modules['pystata'] = Mock()
sys.modules['stata_setup'] = Mock()

# Add src to path for importing StataClient
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from mcp_stata.stata_client import StataClient
from mcp_stata.graph_detector import StreamingGraphCache


class TestConcurrentGraphCaching:
    """Test concurrent access to graph caching functionality."""
    
    @pytest.fixture
    def mock_stata_client(self):
        """Create a mock StataClient for testing."""
        client = Mock(spec=StataClient)
        client._exec_lock = threading.Lock()
        client._preemptive_cache = {}
        client._cache_lock = threading.Lock()
        client._cache_access_times = {}
        client._cache_sizes = {}
        client._total_cache_size = 0
        client._cache_initialized = True
        client._preemptive_cache_dir = tempfile.mkdtemp()
        return client
    
    @pytest.fixture
    def graph_cache(self, mock_stata_client):
        """Create a StreamingGraphCache with mock client."""
        cache = StreamingGraphCache(mock_stata_client)
        cache._cached_graphs = set()
        cache._removed_graphs = set()
        cache._lock = threading.Lock()
        return cache
    
    def test_concurrent_cache_access(self, mock_stata_client):
        """Test multiple threads accessing cache simultaneously."""
        num_threads = 10
        operations_per_thread = 50
        results = []
        errors = []
        
        def cache_worker(thread_id):
            """Worker function that performs cache operations."""
            try:
                for i in range(operations_per_thread):
                    graph_name = f"test_graph_{thread_id}_{i}"
                    
                    # Simulate cache operations
                    with mock_stata_client._cache_lock:
                        if graph_name not in mock_stata_client._preemptive_cache:
                            # Add to cache
                            mock_stata_client._preemptive_cache[graph_name] = f"/tmp/{graph_name}.svg"
                            mock_stata_client._cache_access_times[graph_name] = time.time()
                            mock_stata_client._cache_sizes[graph_name] = 1024
                            mock_stata_client._total_cache_size += 1024
                        else:
                            # Update access time
                            mock_stata_client._cache_access_times[graph_name] = time.time()
                    
                    results.append((thread_id, i))
                    
                    # Small delay to increase chance of race conditions
                    time.sleep(0.001)
                    
            except Exception as e:
                errors.append((thread_id, str(e)))
        
        # Start multiple threads
        threads = []
        start_time = time.time()
        
        for thread_id in range(num_threads):
            thread = threading.Thread(target=cache_worker, args=(thread_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        end_time = time.time()
        
        # Verify results
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == num_threads * operations_per_thread
        assert len(mock_stata_client._preemptive_cache) == num_threads * operations_per_thread
        assert mock_stata_client._total_cache_size == num_threads * operations_per_thread * 1024
        
        print(f"Concurrent cache test completed in {end_time - start_time:.2f}s")
    
    def test_concurrent_cache_eviction(self, mock_stata_client):
        """Test cache eviction under concurrent load."""
        # Set small cache limits to trigger eviction
        with patch.object(StataClient, 'MAX_CACHE_SIZE', 50):
            with patch.object(StataClient, 'MAX_CACHE_BYTES', 100 * 1024):
                
                num_threads = 20
                graphs_per_thread = 10
                results = []
                
                def eviction_worker(thread_id):
                    """Worker function that fills cache beyond limits."""
                    try:
                        for i in range(graphs_per_thread):
                            graph_name = f"evict_test_{thread_id}_{i}"
                            
                            # Simulate adding large items to cache
                            item_size = 10 * 1024  # 10KB per item
                            
                            # Call eviction logic
                            mock_stata_client._evict_cache_if_needed(item_size)
                            
                            with mock_stata_client._cache_lock:
                                mock_stata_client._preemptive_cache[graph_name] = f"/tmp/{graph_name}.svg"
                                mock_stata_client._cache_access_times[graph_name] = time.time()
                                mock_stata_client._cache_sizes[graph_name] = item_size
                                mock_stata_client._total_cache_size += item_size
                            
                            results.append(graph_name)
                            time.sleep(0.001)
                            
                    except Exception as e:
                        pytest.fail(f"Eviction worker {thread_id} failed: {e}")
                
                # Start threads
                threads = []
                for thread_id in range(num_threads):
                    thread = threading.Thread(target=eviction_worker, args=(thread_id,))
                    threads.append(thread)
                    thread.start()
                
                # Wait for completion
                for thread in threads:
                    thread.join()
                
                # Verify cache limits are respected
                assert len(mock_stata_client._preemptive_cache) <= StataClient.MAX_CACHE_SIZE
                assert mock_stata_client._total_cache_size <= StataClient.MAX_CACHE_BYTES
                
                print(f"Cache eviction test: {len(results)} items processed, cache size: {len(mock_stata_client._preemptive_cache)}")
    
    def test_concurrent_graph_detection(self, graph_cache):
        """Test concurrent graph detection and caching."""
        num_threads = 5
        detection_events = []
        
        def detection_worker(thread_id):
            """Worker function that simulates graph detection."""
            try:
                for i in range(20):
                    graph_name = f"detected_graph_{thread_id}_{i}"
                    
                    # Simulate graph detection
                    with graph_cache._lock:
                        if graph_name not in graph_cache._cached_graphs:
                            graph_cache._cached_graphs.add(graph_name)
                            detection_events.append((thread_id, graph_name, 'detected'))
                    
                    # Simulate caching delay
                    time.sleep(0.01)
                    
                    # Simulate cache completion
                    with graph_cache._lock:
                        if graph_name in graph_cache._cached_graphs:
                            detection_events.append((thread_id, graph_name, 'cached'))
                    
            except Exception as e:
                pytest.fail(f"Detection worker {thread_id} failed: {e}")
        
        # Start detection threads
        threads = []
        for thread_id in range(num_threads):
            thread = threading.Thread(target=detection_worker, args=(thread_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Verify all graphs were detected and cached
        detected_graphs = [event[1] for event in detection_events if event[2] == 'detected']
        cached_graphs = [event[1] for event in detection_events if event[2] == 'cached']
        
        assert len(detected_graphs) == num_threads * 20
        assert len(cached_graphs) == num_threads * 20
        assert len(graph_cache._cached_graphs) == num_threads * 20
        
        print(f"Graph detection test: {len(detection_events)} events processed")
    
    def test_error_recovery_concurrent_access(self, mock_stata_client):
        """Test error recovery during concurrent cache operations."""
        num_threads = 10
        operations = []
        errors = []
        
        def error_prone_worker(thread_id):
            """Worker that encounters and recovers from errors."""
            try:
                for i in range(30):
                    graph_name = f"error_test_{thread_id}_{i}"
                    
                    try:
                        # Simulate operations that might fail
                        if i % 10 == 0:
                            # Simulate a cache miss that requires file I/O
                            raise FileNotFoundError("Simulated cache miss")
                        
                        # Normal cache operation
                        with mock_stata_client._cache_lock:
                            mock_stata_client._preemptive_cache[graph_name] = f"/tmp/{graph_name}.svg"
                            mock_stata_client._cache_access_times[graph_name] = time.time()
                            mock_stata_client._cache_sizes[graph_name] = 1024
                            mock_stata_client._total_cache_size += 1024
                        
                        operations.append((thread_id, i, 'success'))
                        
                    except FileNotFoundError:
                        # Simulate error recovery
                        operations.append((thread_id, i, 'recovered'))
                        continue
                    
                    except Exception as e:
                        errors.append((thread_id, i, str(e)))
                        continue
                    
                    time.sleep(0.001)
                    
            except Exception as e:
                errors.append((thread_id, 'worker_failed', str(e)))
        
        # Start error-prone threads
        threads = []
        for thread_id in range(num_threads):
            thread = threading.Thread(target=error_prone_worker, args=(thread_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Verify error recovery
        successful_ops = [op for op in operations if op[2] == 'success']
        recovered_ops = [op for op in operations if op[2] == 'recovered']
        
        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(recovered_ops) == num_threads * 3  # Every 10th operation should recover
        assert len(successful_ops) == num_threads * 27  # Remaining operations should succeed
        
        print(f"Error recovery test: {len(successful_ops)} successful, {len(recovered_ops)} recovered")
    
    def test_cache_consistency_under_load(self, mock_stata_client):
        """Test cache data consistency under high concurrent load."""
        num_threads = 15
        iterations = 100
        consistency_checks = []
        
        def consistency_worker(thread_id):
            """Worker that performs consistency checks."""
            try:
                for i in range(iterations):
                    graph_name = f"consistency_{thread_id}_{i}"
                    
                    # Add item to cache
                    with mock_stata_client._cache_lock:
                        mock_stata_client._preemptive_cache[graph_name] = f"/tmp/{graph_name}.svg"
                        mock_stata_client._cache_access_times[graph_name] = time.time()
                        mock_stata_client._cache_sizes[graph_name] = 2048
                        mock_stata_client._total_cache_size += 2048
                        
                        # Check consistency
                        expected_size = len(mock_stata_client._preemptive_cache) * 2048
                        actual_size = mock_stata_client._total_cache_size
                        
                        if expected_size != actual_size:
                            consistency_checks.append((thread_id, i, 'size_mismatch', expected_size, actual_size))
                        
                        # Check data structure consistency
                        if graph_name not in mock_stata_client._cache_access_times:
                            consistency_checks.append((thread_id, i, 'missing_access_time'))
                        
                        if graph_name not in mock_stata_client._cache_sizes:
                            consistency_checks.append((thread_id, i, 'missing_size'))
                    
                    time.sleep(0.001)
                    
            except Exception as e:
                consistency_checks.append((thread_id, 'worker_error', str(e)))
        
        # Start consistency check threads
        threads = []
        for thread_id in range(num_threads):
            thread = threading.Thread(target=consistency_worker, args=(thread_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Verify no consistency issues
        assert len(consistency_checks) == 0, f"Consistency issues found: {consistency_checks}"
        
        # Final consistency check
        with mock_stata_client._cache_lock:
            expected_final_size = len(mock_stata_client._preemptive_cache) * 2048
            actual_final_size = mock_stata_client._total_cache_size
            assert expected_final_size == actual_final_size
        
        print(f"Consistency test: {num_threads * iterations} operations completed without issues")
    
    def test_async_concurrent_operations(self, graph_cache, mock_stata_client):
        """Test async concurrent operations with graph cache."""
        async def async_cache_worker(worker_id):
            """Async worker that performs cache operations."""
            try:
                for i in range(50):
                    graph_name = f"async_test_{worker_id}_{i}"
                    
                    # Simulate async cache operation
                    await asyncio.sleep(0.001)
                    
                    with graph_cache._lock:
                        graph_cache._cached_graphs.add(graph_name)
                    
                    with mock_stata_client._cache_lock:
                        mock_stata_client._preemptive_cache[graph_name] = f"/tmp/{graph_name}.svg"
                        mock_stata_client._cache_access_times[graph_name] = time.time()
                        mock_stata_client._cache_sizes[graph_name] = 1024
                        mock_stata_client._total_cache_size += 1024
                    
                    return (worker_id, i, graph_name)
                    
            except Exception as e:
                pytest.fail(f"Async worker {worker_id} failed: {e}")
        
        # Run async workers concurrently
        async def run_async_test():
            tasks = []
            for worker_id in range(8):
                task = asyncio.create_task(async_cache_worker(worker_id))
                tasks.append(task)
            
            results = await asyncio.gather(*tasks)
            return results
        
        # Run the async test
        results = asyncio.run(run_async_test())
        
        # Verify results
        assert len(results) == 8
        total_operations = sum(len(result) if isinstance(result, list) else 1 for result in results)
        assert total_operations == 8 * 50
        
        print(f"Async concurrent test: {total_operations} operations completed")


class TestErrorRecoveryScenarios:
    """Test various error recovery scenarios."""
    
    @pytest.fixture
    def mock_client_with_failures(self):
        """Create a mock client that simulates various failures."""
        client = Mock(spec=StataClient)
        client._exec_lock = threading.Lock()
        client._preemptive_cache = {}
        client._cache_lock = threading.Lock()
        client._cache_access_times = {}
        client._cache_sizes = {}
        client._total_cache_size = 0
        client._cache_initialized = True
        client._preemptive_cache_dir = tempfile.mkdtemp()
        
        # Simulate intermittent failures
        failure_count = 0
        def failing_cache_operation(*args, **kwargs):
            nonlocal failure_count
            failure_count += 1
            if failure_count % 7 == 0:  # Fail every 7th operation
                raise IOError("Simulated I/O failure")
            return True
        
        client.cache_graph_on_creation = failing_cache_operation
        return client
    
    def test_recovery_from_io_failures(self, mock_client_with_failures):
        """Test recovery from intermittent I/O failures."""
        num_operations = 50
        successful_operations = 0
        failed_operations = 0
        
        for i in range(num_operations):
            try:
                result = mock_client_with_failures.cache_graph_on_creation(f"test_graph_{i}")
                if result:
                    successful_operations += 1
                else:
                    failed_operations += 1
            except IOError:
                failed_operations += 1
                continue  # Recovery: continue with next operation
            except Exception as e:
                pytest.fail(f"Unexpected error: {e}")
        
        # Verify recovery worked
        assert successful_operations > 0
        assert failed_operations > 0
        assert successful_operations + failed_operations == num_operations
        
        # Expected approximately 1/7 of operations to fail
        expected_failures = num_operations // 7
        assert abs(failed_operations - expected_failures) <= 2  # Allow some variance
        
        print(f"IO failure recovery: {successful_operations} successful, {failed_operations} failed")
    
    def test_cache_corruption_recovery(self, mock_stata_client):
        """Test recovery from cache corruption scenarios."""
        # Simulate corrupted cache state
        mock_stata_client._preemptive_cache = {
            "graph1": "/nonexistent/path1.svg",
            "graph2": "/nonexistent/path2.svg",
            "graph3": "/valid/path3.svg"
        }
        mock_stata_client._cache_access_times = {
            "graph1": time.time(),
            "graph2": time.time(),
            "graph3": time.time()
        }
        mock_stata_client._cache_sizes = {
            "graph1": 1024,
            "graph2": 2048,
            "graph3": 1536
        }
        mock_stata_client._total_cache_size = 4608
        
        # Test corruption detection and cleanup
        corrupted_entries = []
        
        for graph_name, cache_path in mock_stata_client._preemptive_cache.items():
            if not os.path.exists(cache_path):
                corrupted_entries.append(graph_name)
        
        # Clean up corrupted entries
        for graph_name in corrupted_entries:
            with mock_stata_client._cache_lock:
                if graph_name in mock_stata_client._preemptive_cache:
                    del mock_stata_client._preemptive_cache[graph_name]
                if graph_name in mock_stata_client._cache_access_times:
                    del mock_stata_client._cache_access_times[graph_name]
                if graph_name in mock_stata_client._cache_sizes:
                    mock_stata_client._total_cache_size -= mock_stata_client._cache_sizes[graph_name]
                    del mock_stata_client._cache_sizes[graph_name]
        
        # Verify cleanup
        assert len(mock_stata_client._preemptive_cache) == 1
        assert "graph3" in mock_stata_client._preemptive_cache
        assert mock_stata_client._total_cache_size == 1536
        
        print(f"Corruption recovery: removed {len(corrupted_entries)} corrupted entries")
    
    def test_memory_pressure_handling(self, mock_stata_client):
        """Test handling of memory pressure scenarios."""
        # Fill cache to near capacity
        large_items = 80  # Close to MAX_CACHE_SIZE of 100
        item_size = 5 * 1024  # 5KB each
        
        for i in range(large_items):
            graph_name = f"large_graph_{i}"
            with mock_stata_client._cache_lock:
                mock_stata_client._preemptive_cache[graph_name] = f"/tmp/{graph_name}.svg"
                mock_stata_client._cache_access_times[graph_name] = time.time() - (i * 100)  # Staggered access times
                mock_stata_client._cache_sizes[graph_name] = item_size
                mock_stata_client._total_cache_size += item_size
        
        initial_cache_size = len(mock_stata_client._preemptive_cache)
        initial_total_size = mock_stata_client._total_cache_size
        
        # Add more items to trigger eviction
        additional_items = 30
        evicted_count = 0
        
        for i in range(additional_items):
            graph_name = f"pressure_test_{i}"
            
            # This should trigger eviction
            initial_length = len(mock_stata_client._preemptive_cache)
            mock_stata_client._evict_cache_if_needed(item_size)
            
            with mock_stata_client._cache_lock:
                mock_stata_client._preemptive_cache[graph_name] = f"/tmp/{graph_name}.svg"
                mock_stata_client._cache_access_times[graph_name] = time.time()
                mock_stata_client._cache_sizes[graph_name] = item_size
                mock_stata_client._total_cache_size += item_size
            
            if len(mock_stata_client._preemptive_cache) <= initial_length:
                evicted_count += 1
        
        # Verify memory pressure was handled
        assert len(mock_stata_client._preemptive_cache) <= StataClient.MAX_CACHE_SIZE
        assert mock_stata_client._total_cache_size <= StataClient.MAX_CACHE_BYTES
        assert evicted_count > 0  # Some items should have been evicted
        
        print(f"Memory pressure test: evicted {evicted_count} items, cache size: {len(mock_stata_client._preemptive_cache)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
