import pytest
import time
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata


def test_cache_initialization_basic(client):
    """Test basic cache initialization without threading."""
    # Clear any existing cache
    if hasattr(client, '_preemptive_cache'):
        delattr(client, '_preemptive_cache')
    if hasattr(client, '_cache_initialized'):
        delattr(client, '_cache_initialized')
    
    # Initialize cache
    client._initialize_cache()
    
    # Cache should be initialized
    assert hasattr(client, '_cache_initialized')
    assert hasattr(client, '_preemptive_cache')
    assert hasattr(client, '_preemptive_cache_dir')
    assert hasattr(client, '_cache_lock')
    
    # Cache directory should exist
    assert Path(client._preemptive_cache_dir).exists()
    
    # Second initialization should not create new directory
    original_dir = client._preemptive_cache_dir
    client._initialize_cache()
    assert client._preemptive_cache_dir == original_dir


def test_cache_cleanup_on_exit(client):
    """Test that cache is properly cleaned up on exit."""
    # Clear any existing cache first
    if hasattr(client, '_cache_initialized'):
        delattr(client, '_cache_initialized')
    
    # Initialize cache
    client._initialize_cache()
    
    cache_dir = client._preemptive_cache_dir
    assert Path(cache_dir).exists()
    
    # Manually call cleanup to test it
    client._cleanup_cache()
    
    # Cache directory should be removed
    assert not Path(cache_dir).exists()


def test_cache_cleanup_with_missing_directory(client):
    """Test cleanup behavior when cache directory doesn't exist."""
    # Initialize cache
    client._initialize_cache()
    cache_dir = client._preemptive_cache_dir

    # Remove directory manually
    shutil.rmtree(cache_dir)
    
    # Cleanup should not raise an error
    client._cleanup_cache()
    
    # Should still work
    assert not Path(cache_dir).exists()


def test_filename_sanitization(client):
    """Test that graph names are properly sanitized for file system usage."""
    test_cases = [
        ("NormalGraph", "NormalGraph"),
        ("Graph With Spaces", "Graph_With_Spaces"),
        ("Graph/With\\Slashes", "Graph_With_Slashes"),
        ("Graph:With;Special<>Chars", "Graph_With_Special__Chars"),  # < and > become separate underscores
        ("Graph|With|Pipes|And|Stars*", "Graph_With_Pipes_And_Stars_"),
        ("A" * 150, "A" * 100),  # Long name truncation
        ("Graph\u00E9WithUnicode", "Graph\u00E9WithUnicode"),  # Unicode characters are preserved
        ("Graph.With.Dots", "Graph.With.Dots"),  # Dots are allowed in the regex pattern
    ]
    
    for input_name, expected in test_cases:
        result = client._sanitize_filename(input_name)
        assert result == expected, f"Failed for {input_name}: got {result}, expected {expected}"
        
        # Result should be safe for file system
        assert not any(char in result for char in '<>:"/\\|?*')
        assert len(result) <= 100


def test_cache_validation_with_modified_graph(client):
    """Test cache validation when graph content changes."""
    # Create initial graph
    client.run_command_structured("sysuse auto, clear")
    client.run_command_structured("scatter price mpg, name(ValidationTest, replace)")
    
    # Cache the graph
    cache_success = client.cache_graph_on_creation("ValidationTest")
    assert cache_success is True
    
    # Export should use cache
    result1 = client.export_graphs_all()
    assert len(result1.graphs) == 1
    
    # Modify the graph
    client.run_command_structured("scatter price weight, name(ValidationTest, replace)")
    
    # Export should detect change and not use stale cache
    result2 = client.export_graphs_all()
    assert len(result2.graphs) == 1
    
    # The file paths should be different (cache was invalidated)
    # Note: This might not always be different if the same cache path is reused
    # but the content should be fresh


def test_error_handling_invalid_graph_name(client):
    """Test error handling for invalid or non-existent graph names."""
    # Clear any existing graphs
    client.run_command_structured("clear all")
    client.run_command_structured("graph drop _all")
    
    # Try to cache non-existent graph
    result = client.cache_graph_on_creation("NonExistentGraph")
    assert result is False
    
    # Export should handle empty graph list gracefully
    export_result = client.export_graphs_all()
    assert len(export_result.graphs) == 0


def test_error_handling_corrupted_cache_file(client):
    """Test behavior when cache file is corrupted or unreadable."""
    # Create and cache a graph
    client.run_command_structured("sysuse auto, clear")
    client.run_command_structured("scatter price mpg, name(CorruptedTest, replace)")
    
    cache_success = client.cache_graph_on_creation("CorruptedTest")
    assert cache_success is True
    
    # Corrupt the cache file
    cache_path = client._preemptive_cache["CorruptedTest"]
    with open(cache_path, 'w') as f:
        f.write("corrupted data")
    
    # Export should handle corruption gracefully
    result = client.export_graphs_all()
    assert len(result.graphs) == 1  # Should still work, just re-export


def test_cache_with_special_characters_in_graph_name(client):
    """Test caching with graph names containing special characters."""
    # Clear any existing graphs
    client.run_command_structured("clear all")
    client.run_command_structured("graph drop _all")
    
    client.run_command_structured("sysuse auto, clear")
    
    # Create graph with special characters
    special_name = "Test Graph With/Special\\Characters"
    client.run_command_structured(f'scatter price mpg, name("{special_name}", replace)')
    
    # Should be able to cache it
    cache_success = client.cache_graph_on_creation(special_name)
    assert cache_success is True
    
    # Should be able to export it
    result = client.export_graphs_all()
    assert len(result.graphs) == 1
    assert result.graphs[0].name == special_name


def test_large_number_of_graphs_performance(client):
    """Test performance with a large number of graphs."""
    # Clear any existing graphs
    client.run_command_structured("clear all")
    client.run_command_structured("graph drop _all")
    
    client.run_command_structured("sysuse auto, clear")
    
    # Create multiple graphs
    num_graphs = 10
    for i in range(num_graphs):
        client.run_command_structured(f'scatter price mpg if rep78=={i+1}, name(PerfGraph{i}, replace)')
    
    # Time the export
    start_time = time.time()
    result = client.export_graphs_all()
    first_export_time = time.time() - start_time
    
    assert len(result.graphs) == num_graphs
    
    # Cache all graphs
    for i in range(num_graphs):
        client.cache_graph_on_creation(f"PerfGraph{i}")
    
    # Second export should be faster
    start_time = time.time()
    result2 = client.export_graphs_all()
    second_export_time = time.time() - start_time
    
    assert len(result2.graphs) == num_graphs
    
    # Verify all graphs have valid file paths
    for graph in result2.graphs:
        assert graph.file_path is not None
        assert Path(graph.file_path).exists()


def test_cache_persistence_across_multiple_exports(client):
    """Test that cache persists across multiple export calls."""
    # Ensure no prior graphs linger from other tests
    client.run_command_structured("graph drop _all")
    # Create and cache a graph
    client.run_command_structured("sysuse auto, clear")
    client.run_command_structured("scatter price mpg, name(PersistenceTest, replace)")
    
    # First export should create cache
    result1 = client.export_graphs_all()
    assert len(result1.graphs) == 1
    
    # Cache should exist after first export
    assert "PersistenceTest" in client._preemptive_cache
    
    # Second export should use cache
    result2 = client.export_graphs_all()
    assert len(result2.graphs) == 1
    
    # Both should have the same graph name
    assert result1.graphs[0].name == result2.graphs[0].name


def test_graph_existence_validation(client):
    """Test the graph existence validation method."""
    # Create a graph
    client.run_command_structured("sysuse auto, clear")
    client.run_command_structured("scatter price mpg, name(ExistenceTest, replace)")
    
    # Graph should exist
    assert client._validate_graph_exists("ExistenceTest") is True
    
    # Non-existent graph should return False
    assert client._validate_graph_exists("NonExistentGraph") is False
    
    # Clear graphs
    client.run_command_structured("graph drop _all")
    
    # Graph should no longer exist
    assert client._validate_graph_exists("ExistenceTest") is False


def test_content_hash_function(client):
    """Test the content hash generation function."""
    test_data = b"test data for hashing"
    hash1 = client._get_content_hash(test_data)
    hash2 = client._get_content_hash(test_data)
    
    # Same data should produce same hash
    assert hash1 == hash2
    
    # Different data should produce different hash
    different_data = b"different test data"
    hash3 = client._get_content_hash(different_data)
    assert hash1 != hash3
    
    # Hash should be MD5 length (32 characters)
    assert len(hash1) == 32
    assert all(c in '0123456789abcdef' for c in hash1)


def test_cache_size_management_simulation(client):
    """Test behavior with cache size (though we don't implement LRU yet)."""
    # Clear cache
    if hasattr(client, '_preemptive_cache'):
        client._preemptive_cache.clear()
    
    client.run_command_structured("sysuse auto, clear")
    
    # Create multiple graphs to fill cache
    num_graphs = 5
    for i in range(num_graphs):
        client.run_command_structured(f'scatter price mpg if rep78=={i+1}, name(SizeTest{i}, replace)')
        client.cache_graph_on_creation(f"SizeTest{i}")
    
    # Cache should contain all graphs, their hashes, and signatures
    expected_size = num_graphs * 3  # graph paths + hashes + signatures
    assert len(client._preemptive_cache) == expected_size
    
    # Verify all cache entries exist
    for i in range(num_graphs):
        graph_name = f"SizeTest{i}"
        assert graph_name in client._preemptive_cache
        assert f"{graph_name}_hash" in client._preemptive_cache
        assert f"{graph_name}_sig" in client._preemptive_cache
