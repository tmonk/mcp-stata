
import os
import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from mcp_stata.sessions import SessionManager

@pytest.mark.skipif(os.getenv("STATA_BIN") is None and shutil.which("stata") is None, reason="Stata not found")
@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_startup_do_file_e2e():
    """Verify that a startup .do file is executed when a session starts."""
    
    # Create a temporary .do file
    with tempfile.NamedTemporaryFile(suffix=".do", mode="w", delete=False) as tf:
        tf.write('global STARTUP_TEST "LOADED SUCCESS"\n')
        tf.write('scalar startup_val = 999\n')
        startup_file_path = tf.name

    # Set the environment variable for the server process (SessionManager spawns worker processes)
    # SessionManager doesn't take env vars easily but it inherits from current process
    os.environ["MCP_STATA_STARTUP_DO_FILE"] = startup_file_path
    
    manager = SessionManager()
    try:
        await manager.start() # Starts default session
        session = manager.get_session("default")
        
        # Verify global macro
        res_macro = await session.call("run_command", {"code": "display \"$STARTUP_TEST\"", "options": {"echo": False}})
        assert "LOADED SUCCESS" in res_macro.get("smcl_output", "")
        
        # Verify scalar
        res_scalar = await session.call("run_command", {"code": "display startup_val", "options": {"echo": False}})
        assert "999" in res_scalar.get("smcl_output", "")
        
    finally:
        await manager.stop_all()
        if os.path.exists(startup_file_path):
            os.unlink(startup_file_path)
        if "MCP_STATA_STARTUP_DO_FILE" in os.environ:
            del os.environ["MCP_STATA_STARTUP_DO_FILE"]

@pytest.mark.skipif(os.getenv("STATA_BIN") is None and shutil.which("stata") is None, reason="Stata not found")
@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_startup_do_file_error_resilience():
    """Verify that a broken startup .do file doesn't prevent session from starting."""
    
    # Create a broken .do file
    with tempfile.NamedTemporaryFile(suffix=".do", mode="w", delete=False) as tf:
        tf.write('this is not a stata command\n')
        startup_file_path = tf.name

    os.environ["MCP_STATA_STARTUP_DO_FILE"] = startup_file_path
    
    manager = SessionManager()
    try:
        await manager.start()
        session = manager.get_session("default")
        
        # Session should still be usable
        res = await session.call("run_command", {"code": "display 2+2", "options": {"echo": False}})
        assert "4" in res.get("smcl_output", "")
        
    finally:
        await manager.stop_all()
        if os.path.exists(startup_file_path):
            os.unlink(startup_file_path)
        if "MCP_STATA_STARTUP_DO_FILE" in os.environ:
            del os.environ["MCP_STATA_STARTUP_DO_FILE"]
