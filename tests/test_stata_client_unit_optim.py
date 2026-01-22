import os
import tempfile
import sys
import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture(autouse=True)
def mock_sfi_manager():
    """Surgical SFI mock that cleans up after each test."""
    mock = MagicMock()
    # Save original if it exists
    old_sfi = sys.modules.get("sfi")
    sys.modules["sfi"] = mock
    
    # We also need to mock mcp_stata.stata_client.Scalar/Macro if they were already imported
    # but since they are imported inside methods, sys.modules is enough.
    
    yield mock
    
    # Restore
    if old_sfi:
        sys.modules["sfi"] = old_sfi
    else:
        sys.modules.pop("sfi", None)

from mcp_stata.stata_client import StataClient

def test_read_persistent_log_chunk_unit():
    """Unit test for chunk reading logic with mocks."""
    client = StataClient()
    
    with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as tmp:
        tmp.write("PREVIOUS_CONTENT\n")
        start_offset = tmp.tell()
        tmp.write("NEW_CONTENT_123")
        log_path = tmp.name
        
    try:
        client._persistent_log_path = log_path
        chunk = client._read_persistent_log_chunk(start_offset)
        assert chunk == "NEW_CONTENT_123"
        
        # Test offset 0
        chunk_all = client._read_persistent_log_chunk(0)
        assert "PREVIOUS_CONTENT" in chunk_all
        assert "NEW_CONTENT_123" in chunk_all
    finally:
        if os.path.exists(log_path):
            os.unlink(log_path)

def test_exec_with_capture_persistent_logic_unit(mock_sfi_manager):
    """Verify the flow of _exec_with_capture when using persistent logs."""
    client = StataClient()
    client.stata = MagicMock()
    client._initialized = True
    
    # Setup persistent state
    client._persistent_log_path = "/tmp/fake_session.smcl"
    client._persistent_log_name = "_mcp_session"
    
    # Mock OS/file operations
    with patch("os.path.exists", return_value=True), \
         patch("os.path.getsize", return_value=100), \
         patch.object(client, "_read_persistent_log_chunk", return_value="COMMAND_OUTPUT"), \
         patch.object(client, "_create_smcl_log_path", side_effect=["/tmp/mcp_chunk_123.smcl", "/tmp/standalone.smcl"]), \
         patch("builtins.open", MagicMock()):
        
        mock_sfi_manager.Scalar.getValue.return_value = 0
        
        # We don't want it to actually run Stata
        with patch.object(client, "get_stored_results", return_value={}):
            resp = client._exec_with_capture("display 123")
            
            # log_path should be the chunk log (isolated) if use_p is True
            assert "/tmp/mcp_chunk_" in resp.log_path
            assert resp.smcl_output == "COMMAND_OUTPUT"
            # Verify it used the chunk reader
            client._read_persistent_log_chunk.assert_called_with(100)
            
            # Verify bundle had log off/on for flushing
            found_flush = False
            for call in client.stata.run.call_args_list:
                if "log off _mcp_session" in call.args[0] and "log on _mcp_session" in call.args[0]:
                    found_flush = True
            assert found_flush

def test_open_smcl_log_surgical_unit(mock_sfi_manager):
    """Verify that _open_smcl_log uses named closure instead of _all."""
    client = StataClient()
    client.stata = MagicMock()
    client._initialized = True
    
    # Mock Scalar to return success (rc=0)
    mock_sfi_manager.Scalar.getValue.return_value = 0
    
    client._open_smcl_log("/path/to/log.smcl", "my_special_log")
    
    # Check that it tried to close the named log (part of the bundle)
    found_close = False
    for call in client.stata.run.call_args_list:
        if "capture quietly log close my_special_log" in call.args[0]:
            found_close = True
    assert found_close
    
    # Verify it DID NOT call close _all
    for call in client.stata.run.call_args_list:
        assert "close _all" not in call.args[0]

def test_init_persistent_log_setup_unit():
    """Verify that init() sets up the persistent log correctly."""
    client = StataClient()
    client.stata = MagicMock()
    
    with patch("mcp_stata.stata_client._get_discovery_candidates", return_value=[("/bin/stata", "mp")]), \
         patch("stata_setup.config"), \
          patch.dict("sys.modules", {"pystata": MagicMock()}), \
         patch.object(client, "_create_smcl_log_path", return_value="/tmp/session.smcl"), \
         patch("sys.stderr.write"):
        
        # Force skip preflight for unit speed
        os.environ["MCP_STATA_SKIP_PREFLIGHT"] = "1"
        
        # We need to mock the import of pystata.stata inside init
        with patch("mcp_stata.stata_client.redirect_stdout"), \
             patch("mcp_stata.stata_client.redirect_stderr"), \
             patch("mcp_stata.stata_client.StataClient._safe_redirect_fds"):
            
             # Mocking the actual module import is hard, let's just test the logic 
             # if we can get past the imports. 
             # Actually, I'll just check if the session log commands are issued.
             client.stata = MagicMock()
             client.init()
             
             assert client._persistent_log_path == "/tmp/session.smcl"
             assert client._persistent_log_name == "_mcp_session"
             client.stata.run.assert_any_call('log using "/tmp/session.smcl", replace smcl name(_mcp_session)', echo=False)
