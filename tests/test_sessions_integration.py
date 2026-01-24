import pytest
import asyncio
from mcp_stata.sessions import SessionManager

pytestmark = pytest.mark.requires_stata

@pytest.mark.asyncio
async def test_session_process_isolation():
    """Verify that different sessions run in different processes."""
    manager = SessionManager()
    try:
        await manager.start() # default
        s2 = await manager.get_or_create_session("s2")
        
        default_session = manager.get_session("default")
        
        assert default_session.pid is not None
        assert s2.pid is not None
        assert default_session.pid != s2.pid
        
    finally:
        await manager.stop_all()

@pytest.mark.asyncio
async def test_session_memory_isolation():
    """Verify that scalars defined in one session are not visible in another."""
    manager = SessionManager()
    try:
        await manager.start()
        s2 = await manager.get_or_create_session("s2")
        s1 = manager.get_session("default")
        
        # Define different values for x
        await s1.call("run_command", {"code": "scalar x = 123", "options": {"echo": False}})
        await s2.call("run_command", {"code": "scalar x = 456", "options": {"echo": False}})
        
        # Verify isolation
        res1 = await s1.call("run_command", {"code": "display x", "options": {"echo": False}})
        res2 = await s2.call("run_command", {"code": "display x", "options": {"echo": False}})
        
        # Stata output usually has some padding, check if value in stdout
        assert "123" in res1.get("smcl_output", "")
        assert "456" in res2.get("smcl_output", "")
        assert "456" not in res1.get("smcl_output", "")
        assert "123" not in res2.get("smcl_output", "")
        
    finally:
        await manager.stop_all()

@pytest.mark.asyncio
async def test_session_dataset_isolation():
    """Verify that loading data in one session doesn't affect another."""
    manager = SessionManager()
    try:
        await manager.start()
        s1 = manager.get_session("default")
        s2 = await manager.get_or_create_session("s2")
        
        # Load auto in s1
        await s1.call("run_command", {"code": "sysuse auto, clear", "options": {"echo": False}})
        
        # Check in s1
        res1 = await s1.call("get_data", {"count": 1})
        assert len(res1) == 1
        assert "make" in res1[0]
        
        # Check in s2 (should be empty/error)
        res = await s2.call("get_data", {"count": 1})
        # If there's no data, pdataframe_from_data might return empty or error
        # StataClient.get_data catches exceptions and returns [{"error": "..."}]
        assert len(res) > 0
        err_msg = res[0].get("error", "")
        assert "No data in memory" in err_msg or "NoneType" in err_msg
            
    finally:
        await manager.stop_all()
