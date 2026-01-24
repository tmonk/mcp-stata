import os
import uuid
import pytest
from mcp_stata.stata_client import StataClient

pytestmark = pytest.mark.requires_stata

@pytest.mark.asyncio
async def test_session_persistence_and_chunk_extraction(stata_client):
    """
    Integration test to verify that persistent session logging allows 
    fast execution while still providing standalone log chunks.
    """
    # 1. First command
    id1 = str(uuid.uuid4())
    resp1 = stata_client._exec_with_capture(f"display \"CMD1_{id1}\"")
    assert resp1.success
    assert f"CMD1_{id1}" in resp1.stdout
    assert resp1.log_path is not None
    assert os.path.exists(resp1.log_path)
    
    with open(resp1.log_path, "r") as f:
        log1_content = f.read()
    assert f"CMD1_{id1}" in log1_content
    
    # 2. Second command - should be isolated in its log_path
    id2 = str(uuid.uuid4())
    resp2 = stata_client._exec_with_capture(f"display \"CMD2_{id2}\"")
    assert resp2.success
    assert f"CMD2_{id2}" in resp2.stdout
    assert resp2.log_path is not None
    assert os.path.exists(resp2.log_path)
    
    with open(resp2.log_path, "r") as f:
        log2_content = f.read()
    assert f"CMD2_{id2}" in log2_content
    # CRITICAL: CMD1 should NOT be in CMD2's standalone log
    assert f"CMD1_{id1}" not in log2_content
    
    # 3. Third command with many lines to verify chunking offset logic
    long_code = "\n".join([f"display \"LINE_{i}\"" for i in range(10)])
    resp3 = stata_client._exec_with_capture(long_code)
    assert resp3.success
    with open(resp3.log_path, "r") as f:
        log3_content = f.read()
    for i in range(10):
        assert f"LINE_{i}" in log3_content
    assert f"CMD2_{id2}" not in log3_content


@pytest.mark.asyncio
async def test_surgical_log_management(stata_client):
    """
    Verify that opening and closing a named log (e.g. for help)
    does not terminate the session-wide persistent log.
    """
    # Verify session log is active
    assert stata_client._persistent_log_path is not None
    assert os.path.exists(stata_client._persistent_log_path)
    
    # Trigger an operation that uses a temporary named log (like help/plain capture)
    # _run_plain_capture uses _smcl_log_capture which uses _open_smcl_log
    help_text = stata_client._run_plain_capture("help regress")
    assert "regress" in help_text.lower()
    
    # Now verify the persistent log still works for the NEXT command
    id3 = str(uuid.uuid4())
    resp = stata_client._exec_with_capture(f"display \"CMD_STILL_WORKS_{id3}\"")
    assert resp.success
    assert f"CMD_STILL_WORKS_{id3}" in resp.stdout
    
    # Check that it reached the persistent log
    with open(stata_client._persistent_log_path, "r") as f:
        session_log = f.read()
    assert f"CMD_STILL_WORKS_{id3}" in session_log


def test_preflight_bypass_env(monkeypatch):
    """Unit test for init behavior with skipping preflight."""
    instance = StataClient()
    monkeypatch.setenv("MCP_STATA_SKIP_PREFLIGHT", "1")
    
    from unittest.mock import patch, MagicMock
    
    # We mock out the actual init components to see if preflight is skipped
    with patch("subprocess.run") as mock_run, \
         patch("stata_setup.config") as mock_config, \
         patch("mcp_stata.stata_client._get_discovery_candidates", return_value=[("/mock/bin", "mp")]), \
         patch("sys.stderr.write") as mock_stderr:
        
        # We need to mock 'from pystata import stata' which happens inside init()
        mock_stata = MagicMock()
        with patch.dict("sys.modules", {"pystata": MagicMock(stata=mock_stata)}):
            # This is tricky because init() does 'from pystata import stata'
            # We will just verify subprocess.run (preflight) is NOT called
            try:
                # We expect it might fail later because we're not providing a real stata
                instance.init()
            except Exception:
                pass
                
            # verify preflight was NOT called because of SKIP_PREFLIGHT=1
            for call in mock_run.call_args_list:
                # preflight_code is a large string, so we check for PREFLIGHT_OK
                cmd = call.args[0]
                if isinstance(cmd, list) and "PREFLIGHT_OK" in cmd[2]:
                    pytest.fail("Pre-flight check was executed despite MCP_STATA_SKIP_PREFLIGHT=1")

@pytest.mark.asyncio
async def test_error_extraction_fidelity(stata_client):
    """
    Verify that error messages are still correctly extracted 
    even with persistent session logging.
    """
    # Run a command that definitely fails
    resp = stata_client._exec_with_capture("noisily summarize non_existent_variable")
    assert not resp.success
    assert resp.rc == 111
    assert resp.error is not None
    # Stata 111 can mean "no variables defined" or "variable not found"
    msg_lower = resp.error.message.lower()
    assert "no variables defined" in msg_lower or "not found" in msg_lower
    # verify we got context
    assert resp.error.context is not None
    assert "summarize" in resp.error.context
