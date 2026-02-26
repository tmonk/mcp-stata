"""
Unit tests for the fallback mechanisms in cache_graph_on_creation.
"""

import pytest
from unittest.mock import patch, MagicMock
import os
import hashlib

from mcp_stata.stata_client import StataClient
from mcp_stata.models import CommandResponse


@pytest.fixture
def mock_client(tmp_path):
    """Fixture that provides a minimal StataClient with mocked internals."""
    # Create an uninitialized client
    client = StataClient()
    client._initialized = True  # Pretend we initialized
    client.stata = MagicMock()
    from unittest.mock import mock_open
    m = mock_open(read_data=b"<svg>fake</svg>")
    with patch("os.path.getsize", return_value=100), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", m), \
         patch.object(client, "_get_graph_signature", return_value="mockedsig"):
        client._initialize_cache()
        yield client
def test_cache_graph_unquoted_name_success(mock_client: StataClient):
    """Test when the first attempt (unquoted name) succeeds."""
    def mock_exec(cmd, **kwargs):
        if "name(Graph)" in cmd and "replace as(svg)" in cmd:
            return CommandResponse(command=cmd, rc=0, stdout="", success=True)
        return CommandResponse(command=cmd, rc=1, stdout="", success=False)
        
    with patch.object(mock_client, "_exec_no_capture_silent", side_effect=mock_exec) as mock_method:
        success = mock_client.cache_graph_on_creation("Graph")
        
        assert success is True
        # Verify it was only called once or twice (maintenance setup might have display)
        # We mainly care that the fallback commands were NOT called.
        calls = [call.args[0] for call in mock_method.call_args_list]
        assert any('name(Graph)' in c for c in calls)
        assert not any('name("Graph")' in c for c in calls)
        assert not any('quietly graph display Graph' in c for c in calls)


@pytest.mark.requires_stata
def test_cache_graph_quoted_name_fallback_success(mock_client: StataClient):
    """Test when unquoted fails with non-r(1), and quoted name succeeds."""
    def mock_exec(cmd, **kwargs):
        # Fail the unquoted attempt with rc=111 error
        if "name(Graph)" in cmd and "replace as(svg)" in cmd:
            return CommandResponse(command=cmd, rc=111, stdout="", success=False)
        # Succeed the quoted attempt
        if 'name("Graph")' in cmd and "replace as(svg)" in cmd:
            return CommandResponse(command=cmd, rc=0, stdout="", success=True)
        return CommandResponse(command=cmd, rc=1, stdout="", success=False)
        
    with patch.object(mock_client, "_exec_no_capture_silent", side_effect=mock_exec) as mock_method:
        success = mock_client.cache_graph_on_creation("Graph")
        
        assert success is True
        calls = [call.args[0] for call in mock_method.call_args_list]
        assert sum('name(Graph)' in c for c in calls) == 1
        assert sum('name("Graph")' in c for c in calls) == 1
        assert not any('quietly graph display Graph' in c for c in calls)


@pytest.mark.requires_stata
def test_cache_graph_display_fallback_success(mock_client: StataClient):
    """Test when both unquoted and quoted explicit names fail (e.g. r(693)), and display fallback succeeds."""
    def mock_exec(cmd, **kwargs):
        if "name(Graph)" in cmd and "replace as(svg)" in cmd:
            return CommandResponse(command=cmd, rc=693, stdout="", success=False)
        if 'name("Graph")' in cmd and "replace as(svg)" in cmd:
            return CommandResponse(command=cmd, rc=693, stdout="", success=False)
        if 'quietly graph display Graph' in cmd:
            return CommandResponse(command=cmd, rc=0, stdout="", success=True)
        # The implicit export that happens after display
        if 'replace as(svg)' in cmd and 'name(' not in cmd:
            return CommandResponse(command=cmd, rc=0, stdout="", success=True)
            
        return CommandResponse(command=cmd, rc=1, stdout="", success=False)
        
    with patch.object(mock_client, "_exec_no_capture_silent", side_effect=mock_exec) as mock_method:
        success = mock_client.cache_graph_on_creation("Graph")
        
        assert success is True
        calls = [call.args[0] for call in mock_method.call_args_list]
        assert sum('name(Graph)' in c for c in calls) == 1
        assert sum('name("Graph")' in c for c in calls) == 1
        assert sum('quietly graph display Graph' in c for c in calls) == 1
        assert sum('replace as(svg)' in c and 'name(' not in c for c in calls) == 1


@pytest.mark.requires_stata
def test_cache_graph_all_fallbacks_fail(mock_client: StataClient):
    """Test when all attempts to export the graph fail."""
    def mock_exec(cmd, **kwargs):
        return CommandResponse(command=cmd, rc=198, stdout="", success=False)
        
    with patch.object(mock_client, "_exec_no_capture_silent", side_effect=mock_exec) as mock_method:
        success = mock_client.cache_graph_on_creation("Graph")
        
        assert success is False
        calls = [call.args[0] for call in mock_method.call_args_list]
        assert sum('name(Graph)' in c for c in calls) == 1
        assert sum('name("Graph")' in c for c in calls) == 1
        assert sum('quietly graph display Graph' in c for c in calls) == 1
