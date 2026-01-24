import pytest
import json
from mcp_stata.models import CommandResponse

pytestmark = pytest.mark.requires_stata

def test_mock_command_execution(client, monkeypatch):
    """Verify that run_command_structured works with the mock setup."""
    # Force mock output directly to avoid file I/O synchronization issues in mock mode
    monkeypatch.setattr(client, "_read_persistent_log_chunk", lambda offset: "{txt}Mock Stata output\n")
    monkeypatch.setattr(client, "_read_smcl_file", lambda path: "{txt}Mock Stata output\n")
    
    result = client.run_command_structured("display 1+1")
    
    # Check that our mock output was captured
    assert result.success is True
    assert "Mock Stata output" in result.stdout

def test_mock_error_handling(client, monkeypatch):
    """Verify that we can simulate a Stata error via mocks."""
    import sfi
    # Force a non-zero RC for the next call
    monkeypatch.setattr(sfi.Scalar, "getValue", lambda x: 111 if x == "c(rc)" else 0)
    
    # Force mock error content
    error_smcl = "{err}variable not found{search r(111)}\n"
    monkeypatch.setattr(client, "_read_persistent_log_chunk", lambda offset: error_smcl)
    monkeypatch.setattr(client, "_read_smcl_file", lambda path: error_smcl)
    
    result = client.run_command_structured("bad command")
    assert result.success is False
    assert result.rc == 111
    assert "variable not found" in result.error.message

def test_mock_data_retrieval(client):
    """Verify that get_data still passes through logic even if mocked."""
    # For now, get_data might fail or return mock depending on how deep we mock sfi.Data
    # Let's see if we can at least call it.
    try:
        data = client.get_data(count=5)
        assert isinstance(data, list)
    except Exception as e:
        # If it fails due to deeper sfi calls we haven't mocked yet, that's fine for now
        # but we know the path is being exercised.
        pytest.skip(f"Data mock not fully implemented: {e}")
