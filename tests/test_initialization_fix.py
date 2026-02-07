
import os
import sys
import pytest
import subprocess
import asyncio
from unittest.mock import MagicMock, patch
from mcp_stata.stata_client import StataClient

@pytest.fixture
def mock_discovery():
    """Mock discovery candidates for initialization tests."""
    with patch("mcp_stata.stata_client._get_discovery_candidates") as mock:
        mock.return_value = [("/Applications/StataNow/stata-mp", "mp")]
        yield mock

def test_init_timeout_increased(mock_discovery):
    """
    Verify that subprocess.run is called with a 60s timeout.
    """
    client = StataClient()
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="PREFLIGHT_OK", stderr="")
        
        # Bypass the rest of init to focus on preflight
        with patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("sys.stderr.write"), \
             patch("sys.stderr.flush"), \
             patch("mcp_stata.stata_client._get_discovery_candidates", return_value=[("/Applications/StataNow/stata-mp", "mp")]), \
             patch("mcp_stata.stata_client.StataClient._create_smcl_log_path", return_value="/tmp/test.smcl"), \
             patch("mcp_stata.stata_client.StataClient._safe_redirect_fds"), \
             patch.dict("sys.modules", {"pystata": MagicMock(), "stata_setup": MagicMock()}):
            
            # Disable skip preflight if it was set in env
            with patch.dict(os.environ, {"MCP_STATA_SKIP_PREFLIGHT": "0"}):
                try:
                    client.init()
                except Exception:
                    pass
            
            # Check the first call to subprocess.run for preflight
            preflight_call = [call for call in mock_run.call_args_list if "-c" in call.args[0]]
            assert len(preflight_call) > 0
            # Verify timeout=60
            assert preflight_call[0].kwargs["timeout"] == 60

def test_preflight_diagnostics_present(mock_discovery):
    """
    Verify that preflight_code contains diagnostic log markers.
    """
    client = StataClient()
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="PREFLIGHT_OK", stderr="")
        
        with patch.dict(os.environ, {"MCP_STATA_SKIP_PREFLIGHT": "0"}), \
             patch("sys.stderr.write"):
            try:
                client.init()
            except Exception:
                pass
            
            preflight_call = [call for call in mock_run.call_args_list if "-c" in call.args[0]]
            payload = preflight_call[0].args[0][2]
            
            # Check for diagnostic strings
            assert "[preflight] Calling stata_setup.config" in payload
            assert "[preflight] Importing pystata.stata..." in payload
            assert "[preflight] Running diagnostic command..." in payload
            assert "PREFLIGHT_OK" in payload

def test_preflight_timeout_handling(mock_discovery):
    """
    Verify that TimeoutExpired is caught and logged.
    """
    client = StataClient()
    
    with patch("subprocess.run") as mock_run:
        # Simulate a timeout. TimeoutExpired(cmd, timeout, output=None, stderr=None)
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["python"], timeout=60, output="partial out", stderr="partial err")
        
        with patch.dict(os.environ, {"MCP_STATA_SKIP_PREFLIGHT": "0"}), \
             patch("sys.stderr.write") as mock_stderr:
            try:
                client.init()
            except RuntimeError as e:
                assert "stata_setup.config failed to initialize Stata" in str(e)
            
            # Verify timeout message was written to stderr
            calls = [c.args[0] for c in mock_stderr.call_args_list]
            assert any("Pre-flight timed out after 60s" in s for s in calls)
            assert any("--- Captured stdout ---" in s for s in calls)
            assert any("partial out" in s for s in calls)

def test_sys_path_reordering_in_preflight(mock_discovery):
    """
    Verify sys.path.insert(0, utils_path) happens BEFORE stata_setup.config(...) in preflight.
    """
    client = StataClient()
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="PREFLIGHT_OK", stderr="")
        
        with patch.dict(os.environ, {"MCP_STATA_SKIP_PREFLIGHT": "0"}), \
             patch("sys.stderr.write"):
            try:
                client.init()
            except Exception:
                pass
            
            preflight_call = [call for call in mock_run.call_args_list if "-c" in call.args[0]]
            payload = preflight_call[0].args[0][2]
            
            # Verify order using string index. 
            # Look for the actual function call, not the import.
            idx_insert = payload.find("sys.path.insert(0, utils_path)")
            idx_config = payload.find("stata_setup.config(") 
            
            assert idx_insert != -1
            assert idx_config != -1
            assert idx_insert < idx_config, "sys.path insertion should happen before stata_setup.config call"

@pytest.mark.asyncio
async def test_e2e_initialization_flow_mocked():
    """
    E2E-style test using a temporary session to verify full flow (minus real Stata).
    """
    from mcp_stata.sessions import StataSession
    
    # We'll mock the Worker/Process to avoid spawning real processes
    # but verify the signals and state.
    with patch("mcp_stata.sessions.Process"), \
         patch("mcp_stata.sessions.Pipe") as mock_pipe:
        
        parent_conn, child_conn = MagicMock(), MagicMock()
        mock_pipe.return_value = (parent_conn, child_conn)
        
        # Simulate successful worker startup
        parent_conn.poll.side_effect = [True, False, False, False, False, False, False, False, False, False]
        parent_conn.recv.return_value = {"event": "ready", "pid": 1234}
        
        session = StataSession(session_id="test-session")
        
        # Wait a bit for the listener task to process the message
        for _ in range(10):
            if session.status == "running":
                break
            await asyncio.sleep(0.01)
            
        assert session.status == "running"
        assert session.pid == 1234
        
        # Cleanup
        session._listener_running = False
        await session._listener_task
