"""Unit tests for ui_http module (no Stata required)"""

import pytest
from unittest.mock import MagicMock

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
