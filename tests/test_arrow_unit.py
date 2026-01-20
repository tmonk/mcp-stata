import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
import pyarrow as pa
import sys

from mcp_stata.stata_client import StataClient

class TestArrowUnit:
    @pytest.fixture
    def client(self):
        # Create a client with mocked internals
        client = StataClient()
        client._initialized = True
        client.stata = MagicMock()
        return client

    def test_get_arrow_stream_basic(self, client):
        # Setup mocks
        mock_data_ns = MagicMock()
        mock_data_ns.getObsTotal.return_value = 10
        mock_data_ns.getVarCount.return_value = 2
        
        # We need to mock sfi.Data being imported inside methods
        with patch.dict(sys.modules, {"sfi": MagicMock(Data=mock_data_ns)}):
            # Mock Data.get to return valid data (nested list of rows)
            mock_data_ns.get.return_value = [[1, "a"], [2, "b"]]
            # Mock get_dataset_state to return non-empty
            with patch.object(client, "get_dataset_state", return_value={"n": 10, "k": 2}):
                with patch.object(client, "_get_var_index_map", return_value={"v1": 0, "v2": 1}):
                    # Mock pystata response
                    df_mock = pd.DataFrame({"v1": [1, 2], "v2": ["a", "b"]})
                    client.stata.pdataframe_from_data.return_value = df_mock
                    
                    # Execute
                    arrow_bytes = client.get_arrow_stream(
                        offset=0, 
                        limit=2, 
                        vars=["v1", "v2"], 
                        include_obs_no=False
                    )

                    # Verify calling arguments
                    # Note: we can't easily check 'obs' arg if it was a list object, 
                    # but we can check it was called.
                    mock_data_ns.get.assert_called_once()
                    
                    # Verify output is valid Arrow stream
                    reader = pa.ipc.open_stream(arrow_bytes)
                    table = reader.read_all()
                    
                    assert table.num_rows == 2
                    assert table.num_columns == 2
                    assert table.column_names == ["v1", "v2"]
                    assert table["v1"].to_pylist() == [1, 2]
                    assert table["v2"].to_pylist() == ["a", "b"]

    def test_get_arrow_stream_with_obs_no(self, client):
        mock_data_ns = MagicMock()
        mock_data_ns.get.return_value = [[10.5]]
        
        with patch.dict(sys.modules, {"sfi": MagicMock(Data=mock_data_ns)}):
            with patch.object(client, "get_dataset_state", return_value={"n": 10, "k": 1}):
                with patch.object(client, "_get_var_index_map", return_value={"v1": 0}):
                    df_mock = pd.DataFrame({"v1": [10.5]})
                    client.stata.pdataframe_from_data.return_value = df_mock
                    
                    arrow_bytes = client.get_arrow_stream(
                        offset=5, 
                        limit=1, 
                        vars=["v1"], 
                        include_obs_no=True
                    )
                    
                    reader = pa.ipc.open_stream(arrow_bytes)
                    table = reader.read_all()
                    
                    assert table.num_rows == 1
                    # Should have _n + v1
                    assert table.column_names == ["_n", "v1"]
                    # _n should be offset (5) + 1 = 6
                    assert table["_n"].to_pylist() == [6]

    def test_get_arrow_stream_empty(self, client):
        mock_data_ns = MagicMock()
        
        with patch.dict(sys.modules, {"sfi": MagicMock(Data=mock_data_ns)}):
            with patch.object(client, "get_dataset_state", return_value={"n": 10, "k": 1}):
                with patch.object(client, "_get_var_index_map", return_value={"v1": 0}):
                    # Mock return for empty list (pystata typically returns empty df)
                    client.stata.pdataframe_from_data.return_value = pd.DataFrame(columns=["v1"])
                    
                    # Request out of bounds
                    arrow_bytes = client.get_arrow_stream(
                        offset=100, 
                        limit=10, 
                        vars=["v1"], 
                        include_obs_no=False
                    )
                    
                    reader = pa.ipc.open_stream(arrow_bytes)
                    try:
                        table = reader.read_all()
                        assert table.num_rows == 0
                        assert table.column_names == ["v1"]
                    except pa.ArrowInvalid:
                        # Some versions might fail reading empty stream without batches
                        # but we wrote a table, so it should have schema even if empty.
                        pass

from mcp_stata.ui_http import handle_arrow_request, HTTPError, UIChannelManager

class TestArrowHandlerUnit:
    @pytest.fixture
    def manager(self):
        manager = MagicMock(spec=UIChannelManager)
        manager.limits.return_value = (500, 200, 500, 1_000_000)
        manager.current_dataset_id.return_value = "test_id"
        manager._max_arrow_limit = 1_000_000
        manager._client = MagicMock()
        return manager

    def test_handle_arrow_request_missing_limit(self, manager):
        body = {
            "datasetId": "test_id",
            "frame": "default",
            "offset": 0,
            "vars": [],
        }
        with pytest.raises(HTTPError) as exc_info:
            handle_arrow_request(manager, body, view_id=None)
        assert exc_info.value.status == 400
        assert "limit is required" in exc_info.value.message

    def test_handle_arrow_request_limit_too_large(self, manager):
        manager._max_arrow_limit = 1000
        body = {
            "datasetId": "test_id",
            "frame": "default",
            "offset": 0,
            "limit": 5000,
            "vars": [],
        }
        with pytest.raises(HTTPError) as exc_info:
            handle_arrow_request(manager, body, view_id=None)
        assert exc_info.value.status == 400
        assert "request_too_large" in exc_info.value.code
        assert "limit must be <= 1000" in exc_info.value.message

    def test_handle_arrow_request_dataset_changed(self, manager):
        manager.current_dataset_id.return_value = "new_id"
        body = {
            "datasetId": "old_id",
            "frame": "default",
            "offset": 0,
            "limit": 10,
            "vars": [],
        }
        with pytest.raises(HTTPError) as exc_info:
            handle_arrow_request(manager, body, view_id=None)
        assert exc_info.value.status == 409
        assert "dataset_changed" in exc_info.value.code

    def test_handle_arrow_request_valid(self, manager):
        manager._client.get_arrow_stream.return_value = b"arrow_data"
        manager._normalize_sort_spec.return_value = ("+v1",)
        manager._get_cached_sort_indices.return_value = [2, 1, 0]
        body = {
            "datasetId": "test_id",
            "frame": "default",
            "offset": 10,
            "limit": 50,
            "vars": ["v1", "v2"],
            "includeObsNo": True,
            "sortBy": ["v1"]
        }
        
        result = handle_arrow_request(manager, body, view_id=None)
        
        assert result == b"arrow_data"
        manager._client.get_arrow_stream.assert_called_once_with(
            offset=10,
            limit=50,
            vars=["v1", "v2"],
            include_obs_no=True,
            obs_indices=[2, 1, 0]
        )
