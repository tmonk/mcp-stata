import pytest
import asyncio
from mcp_stata.sessions import SessionManager

pytestmark = pytest.mark.requires_stata

@pytest.mark.asyncio
async def test_session_cancellation_data_preservation():
    """Verify that cancelling a task interrupts Stata but preserves data."""
    manager = SessionManager()
    try:
        await manager.start()
        session = manager.get_session("default")
        
        # Set a value
        await session.call("run_command", {"code": "scalar myval = 987", "options": {"echo": False}})
        
        # Run a long loop
        code = "forvalues i = 1/1000000 { \n scalar iter = `i' \n }"
        task = asyncio.create_task(session.call("run_command", {"code": code, "options": {"echo": True}}))
        
        # Let it start
        await asyncio.sleep(0.2)
        
        # Cancel the task
        task.cancel()
        
        with pytest.raises(asyncio.CancelledError):
            await task
            
        # Verify myval is still there
        res = await session.call("run_command", {"code": "display myval", "options": {"echo": False}})
        assert "987" in res.get("stdout", "")
        
    finally:
        await manager.stop_all()

@pytest.mark.asyncio
async def test_break_session_tool_logic():
    """Verify that send_break() works via the session manager."""
    manager = SessionManager()
    try:
        await manager.start()
        session = manager.get_session("default")
        
        # Start a long run (loop is better than sleep for testing interrupts)
        task = asyncio.create_task(session.call("run_command", {"code": "forvalues i=1/1000000 { \n di `i' \n }", "options": {"echo": True}}))
        
        await asyncio.sleep(0.5)
        
        start_time = asyncio.get_running_loop().time()
        # Send break out-of-band
        await session.send_break()
        
        # The task should finish quickly after break
        result = await task
        duration = asyncio.get_running_loop().time() - start_time
        
        print(f"Task result: {result}")
        print(f"Interruption took {duration:.2f}s")
        
        # Interruption should be fast
        assert duration < 5.0
        
        # Session should be ready for next command
        res = await session.call("run_command", {"code": "display 123", "options": {"echo": False}})
        assert "123" in res.get("stdout", "")
        
    finally:
        await manager.stop_all()
