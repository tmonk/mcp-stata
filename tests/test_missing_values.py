import pytest
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
import pyarrow as pa
import sys

# Unit tests for StataClient missing value detection
def test_is_stata_missing_unit():
    from mcp_stata.stata_client import StataClient
    client = StataClient()
    client._initialized = True # Skip real init
    
    # Test with standard None
    assert client._is_stata_missing(None) is True
    
    # Test with normal numbers
    assert client._is_stata_missing(0) is False
    assert client._is_stata_missing(1.5) is False
    assert client._is_stata_missing(-100) is False
    
    # Test with the large float representation
    stata_missing_val = 8.98846567431158e+307
    assert client._is_stata_missing(stata_missing_val) is True
    
    # Test with slightly smaller but still large float
    assert client._is_stata_missing(8.0e307) is False
    
    # Mock sfi.Missing to verify it's used
    with patch.dict(sys.modules, {'sfi': MagicMock()}):
        import sfi
        sfi.Missing.isMissing.return_value = True
        assert client._is_stata_missing(12345) is True
        sfi.Missing.isMissing.assert_called_with(12345)

@pytest.mark.requires_stata
def test_missing_values_integration(client):
    """
    Integration test that actually runs Stata (if available) to verify 
    that missing values are normalized to null in JSON and Arrow.
    """
    # 1. Prepare data with missing values
    client.run_command_structured("clear")
    client.run_command_structured("set obs 2")
    client.run_command_structured("gen num_var = 1 in 1")
    client.run_command_structured("gen str_var = \"hello\" in 1")
    # Row 2 now has numeric missing (.) and string missing ("")
    
    # 2. Test get_data (JSON normalization)
    data = client.get_data(start=0, count=2)
    assert len(data) == 2
    
    # First row should be normal
    assert data[0]["num_var"] == 1.0
    assert data[0]["str_var"] == "hello"
    
    # Second row should have null for numeric missing
    # (Stata missing strings are empty strings, not null)
    assert data[1]["num_var"] is None or np.isnan(data[1]["num_var"])
    # Note: depending on how pdataframe_from_data and to_dict work, 
    # it might be None or NaN. Our fix should have made it None.
    assert data[1]["num_var"] is None
    
    # 3. Test get_arrow_stream (Arrow normalization)
    arrow_bytes = client.get_arrow_stream(offset=0, limit=2, vars=["num_var", "str_var"], include_obs_no=True)
    import pyarrow.ipc as ipc
    with pa.BufferReader(arrow_bytes) as reader:
        with ipc.open_stream(reader) as stream:
            table = stream.read_all()
            
    assert table.num_rows == 2
    # Check num_var in second row
    col_num = table.column("num_var")
    assert col_num[0].as_py() == 1.0
    assert col_num[1].as_py() is None  # Should be null in Arrow

@pytest.mark.requires_stata
def test_missing_values_sorting_integration(client):
    """
    Verify that sorting handles missing values correctly using the dynamic threshold.
    In Stata, missing values are larger than any non-missing values, so they should 
    appear at the end when sorting ascending.
    """
    client.run_command_structured("clear")
    client.run_command_structured("set obs 3")
    client.run_command_structured("gen x = 3 in 1")
    client.run_command_structured("replace x = 1 in 2")
    # Row 3 is missing (.)
    
    # We'll use the UI HTTP layer's sorting logic (via a mock or direct call)
    from mcp_stata.ui_http import _get_sorted_indices_polars
    
    arrow_bytes = client.get_arrow_stream(offset=0, limit=3, vars=["x"], include_obs_no=True)
    with pa.BufferReader(arrow_bytes) as reader:
        table = pa.ipc.open_stream(reader).read_all()
    
    threshold = client.get_stata_missing_threshold()
    
    # Sort ascending: [1, 3, .]
    # Indices are 0-based: row 2 (x=1) is index 1, row 1 (x=3) is index 0, row 3 (x=.) is index 2
    indices = _get_sorted_indices_polars(
        table, 
        sort_cols=["x"], 
        descending=[False], 
        nulls_last=[True],
        missing_threshold=threshold
    )
    
    # Stata indices in _n are 1, 2, 3. 
    # Row with x=1 is _n=2. Row with x=3 is _n=1. Row with x=. is _n=3.
    # So sorted _n should be [2, 1, 3].
    # Our indices are 0-based based on _n-1, so [1, 0, 2].
    assert indices == [1, 0, 2]

def test_missing_threshold_fallback():
    """Verify that get_stata_missing_threshold falls back gracefully."""
    from mcp_stata.stata_client import StataClient
    with patch.dict(sys.modules, {'sfi': MagicMock()}):
        import sfi
        del sfi.Missing # Simulate missing Missing class
        
        c = StataClient()
        threshold = c.get_stata_missing_threshold()
        assert threshold == 8.98846567431158e+307
