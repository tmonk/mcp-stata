"""Unit tests for ui_http module (no Stata required)"""

import pytest
from unittest.mock import MagicMock

import pyarrow as pa

from mcp_stata.ui_http import UIChannelManager, handle_page_request, HTTPError


def test_handle_page_request_missing_limit():
    """Test that missing limit parameter raises appropriate error"""
    manager = MagicMock(spec=UIChannelManager)
    manager.limits.return_value = (500, 200, 500, 1_000_000)
    manager.current_dataset_id.return_value = "test_id"

    body = {
        "datasetId": "test_id",
        "frame": "default",
        "offset": 0,
        # limit is missing
        "vars": [],
    }

    with pytest.raises(HTTPError) as exc_info:
        handle_page_request(manager, body, view_id=None)

    assert exc_info.value.status == 400
    assert exc_info.value.code == "invalid_request"
    assert "limit is required" in exc_info.value.message


def test_handle_page_request_limit_zero():
    """Test that limit=0 raises appropriate error"""
    manager = MagicMock(spec=UIChannelManager)
    manager.limits.return_value = (500, 200, 500, 1_000_000)
    manager.current_dataset_id.return_value = "test_id"

    body = {
        "datasetId": "test_id",
        "frame": "default",
        "offset": 0,
        "limit": 0,
        "vars": [],
    }

    with pytest.raises(HTTPError) as exc_info:
        handle_page_request(manager, body, view_id=None)

    assert exc_info.value.status == 400
    assert exc_info.value.code == "invalid_request"
    assert "limit must be > 0" in exc_info.value.message
    assert "got: 0" in exc_info.value.message


def test_handle_page_request_limit_negative():
    """Test that negative limit raises appropriate error"""
    manager = MagicMock(spec=UIChannelManager)
    manager.limits.return_value = (500, 200, 500, 1_000_000)
    manager.current_dataset_id.return_value = "test_id"

    body = {
        "datasetId": "test_id",
        "frame": "default",
        "offset": 0,
        "limit": -5,
        "vars": [],
    }

    with pytest.raises(HTTPError) as exc_info:
        handle_page_request(manager, body, view_id=None)

    assert exc_info.value.status == 400
    assert "limit must be > 0" in exc_info.value.message


def test_handle_page_request_limit_null():
    """Test that limit=null raises appropriate error"""
    manager = MagicMock(spec=UIChannelManager)
    manager.limits.return_value = (500, 200, 500, 1_000_000)
    manager.current_dataset_id.return_value = "test_id"

    body = {
        "datasetId": "test_id",
        "frame": "default",
        "offset": 0,
        "limit": None,
        "vars": [],
    }

    with pytest.raises(HTTPError) as exc_info:
        handle_page_request(manager, body, view_id=None)

    assert exc_info.value.status == 400
    assert "limit is required" in exc_info.value.message


def test_handle_page_request_limit_invalid_string():
    """Test that invalid string limit raises appropriate error"""
    manager = MagicMock(spec=UIChannelManager)
    manager.limits.return_value = (500, 200, 500, 1_000_000)
    manager.current_dataset_id.return_value = "test_id"

    body = {
        "datasetId": "test_id",
        "frame": "default",
        "offset": 0,
        "limit": "not a number",
        "vars": [],
    }

    with pytest.raises(HTTPError) as exc_info:
        handle_page_request(manager, body, view_id=None)

    assert exc_info.value.status == 400
    assert "must be a valid integer" in exc_info.value.message


def test_handle_page_request_limit_too_large():
    """Test that limit exceeding max_limit raises appropriate error"""
    manager = MagicMock(spec=UIChannelManager)
    manager.limits.return_value = (500, 200, 500, 1_000_000)
    manager.current_dataset_id.return_value = "test_id"

    body = {
        "datasetId": "test_id",
        "frame": "default",
        "offset": 0,
        "limit": 1000,  # exceeds max_limit of 500
        "vars": [],
    }

    with pytest.raises(HTTPError) as exc_info:
        handle_page_request(manager, body, view_id=None)

    assert exc_info.value.status == 400
    assert exc_info.value.code == "request_too_large"
    assert "limit must be <=" in exc_info.value.message


def test_handle_page_request_offset_negative():
    """Test that negative offset raises appropriate error"""
    manager = MagicMock(spec=UIChannelManager)
    manager.limits.return_value = (500, 200, 500, 1_000_000)
    manager.current_dataset_id.return_value = "test_id"

    body = {
        "datasetId": "test_id",
        "frame": "default",
        "offset": -1,
        "limit": 10,
        "vars": [],
    }

    with pytest.raises(HTTPError) as exc_info:
        handle_page_request(manager, body, view_id=None)

    assert exc_info.value.status == 400
    assert "offset must be >=" in exc_info.value.message


def test_handle_page_request_offset_invalid_string():
    """Test that invalid string offset raises appropriate error"""
    manager = MagicMock(spec=UIChannelManager)
    manager.limits.return_value = (500, 200, 500, 1_000_000)
    manager.current_dataset_id.return_value = "test_id"

    body = {
        "datasetId": "test_id",
        "frame": "default",
        "offset": "not a number",
        "limit": 10,
        "vars": [],
    }

    with pytest.raises(HTTPError) as exc_info:
        handle_page_request(manager, body, view_id=None)

    assert exc_info.value.status == 400
    assert "offset must be a valid integer" in exc_info.value.message


def test_handle_page_request_offset_missing_defaults_to_zero():
    """Test that missing offset defaults to 0"""
    manager = MagicMock(spec=UIChannelManager)
    manager.limits.return_value = (500, 200, 500, 1_000_000)
    manager.current_dataset_id.return_value = "test_id"
    manager._client = MagicMock()
    manager._client.get_dataset_state.return_value = {
        "frame": "default",
        "n": 100,
        "k": 5,
    }
    manager._client.get_page.return_value = {
        "returned": 10,
        "vars": ["var1"],
        "rows": [[1], [2]],
        "truncated_cells": [],
    }

    body = {
        "datasetId": "test_id",
        "frame": "default",
        # offset is missing - should default to 0
        "limit": 10,
        "vars": ["var1"],
    }

    result = handle_page_request(manager, body, view_id=None)

    # Verify that offset was passed as 0 to get_page
    manager._client.get_page.assert_called_once()
    call_kwargs = manager._client.get_page.call_args[1]
    assert call_kwargs["offset"] == 0


def test_handle_page_request_valid_parameters():
    """Test that valid parameters work correctly"""
    manager = MagicMock(spec=UIChannelManager)
    manager.limits.return_value = (500, 200, 500, 1_000_000)
    manager.current_dataset_id.return_value = "test_id"
    manager._client = MagicMock()
    manager._client.get_dataset_state.return_value = {
        "frame": "default",
        "n": 100,
        "k": 5,
    }
    manager._client.get_page.return_value = {
        "returned": 10,
        "vars": ["var1"],
        "rows": [[1], [2]],
        "truncated_cells": [],
    }

    body = {
        "datasetId": "test_id",
        "frame": "default",
        "offset": 5,
        "limit": 10,
        "vars": ["var1"],
    }

    result = handle_page_request(manager, body, view_id=None)

    # Verify that parameters were passed correctly
    manager._client.get_page.assert_called_once()
    call_kwargs = manager._client.get_page.call_args[1]
    assert call_kwargs["offset"] == 5
    assert call_kwargs["limit"] == 10
    assert call_kwargs["vars"] == ["var1"]


def test_handle_page_request_sort_polars_fallback(monkeypatch):
    """Test that sorting falls back to Polars when native sorter is unavailable."""
    try:
        import polars  # noqa: F401
    except ImportError:
        pytest.skip("polars not available")

    import mcp_stata.ui_http as ui_http

    manager = MagicMock(spec=UIChannelManager)
    manager.limits.return_value = (500, 200, 500, 1_000_000)
    manager.current_dataset_id.return_value = "test_id"
    manager._normalize_sort_spec.return_value = ("+price",)
    manager._get_cached_sort_indices.return_value = None
    manager._set_cached_sort_indices = MagicMock()
    manager._client = MagicMock()
    manager._client.get_dataset_state.return_value = {
        "frame": "default",
        "n": 3,
        "k": 2,
    }
    manager._client.get_page.return_value = {
        "returned": 3,
        "vars": ["price"],
        "rows": [[1], [2], [3]],
        "truncated_cells": [],
    }

    table = pa.table(
        {
            "_n": [1, 2, 3],
            "price": [3.0, 1.0, 2.0],
            "make": ["c", "a", "b"],
        }
    )
    manager._get_sort_table.return_value = table

    monkeypatch.setattr(ui_http, "_native_argsort_numeric", None)
    monkeypatch.setattr(ui_http, "_native_argsort_mixed", None)

    body = {
        "datasetId": "test_id",
        "frame": "default",
        "offset": 0,
        "limit": 3,
        "vars": ["price"],
        "sortBy": ["price"],
    }

    handle_page_request(manager, body, view_id=None)

    call_kwargs = manager._client.get_page.call_args[1]
    assert call_kwargs["obs_indices"] == [1, 2, 0]
    manager._set_cached_sort_indices.assert_called_once()
