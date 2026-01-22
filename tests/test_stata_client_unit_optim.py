import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
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

def test_exec_with_capture_persistent_logic_unit():
    """Verify the flow of _exec_with_capture when using persistent logs."""
    client = StataClient()
    client.stata = MagicMock()
    client._initialized = True
    
    # Setup persistent state
    client._persistent_log_path = "/tmp/fake_session.smcl"
    
    # Mock OS/file operations
    with patch("os.path.exists", return_value=True), \
         patch("os.path.getsize", return_value=100), \
         patch.object(client, "_read_persistent_log_chunk", return_value="COMMAND_OUTPUT"), \
         patch.object(client, "_create_smcl_log_path", return_value="/tmp/standalone.smcl"), \
         patch.dict("sys.modules", {"sfi": MagicMock()}), \
         patch("builtins.open", MagicMock()):
        
        # We don't want it to actually run Stata
        with patch.object(client, "get_stored_results", return_value={}):
            resp = client._exec_with_capture("display 123")
            
            # log_path should be the persistent log if use_p is True
            assert resp.log_path == "/tmp/fake_session.smcl"
            assert resp.smcl_output == "COMMAND_OUTPUT"
            # Verify it used the chunk reader
            client._read_persistent_log_chunk.assert_called_with(100)

def test_open_smcl_log_surgical_unit():
    """Verify that _open_smcl_log uses named closure instead of _all."""
    client = StataClient()
    client.stata = MagicMock()
    client._initialized = True
    
    # Mock log query to return success
    query_mock = MagicMock()
    query_mock.getvalue.return_value = "Log: ... ON ... SMCL"
    
    with patch("mcp_stata.stata_client.StringIO", return_value=query_mock), \
         patch("mcp_stata.stata_client.redirect_stdout"), \
         patch("mcp_stata.stata_client.redirect_stderr"):
        
        client._open_smcl_log("/path/to/log.smcl", "my_special_log")
        
        # Check that it tried to close ONLY the named log
        client.stata.run.assert_any_call("capture log close my_special_log", echo=False)
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
