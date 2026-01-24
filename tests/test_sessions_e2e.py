import json
import pytest
import asyncio
from mcp_stata.server import (
    create_session,
    list_sessions,
    run_command,
    session_manager
)

# Mark as requiring Stata
pytestmark = pytest.mark.requires_stata

@pytest.mark.asyncio
async def test_mcp_session_tools():
    """Test session management tools via the server interface."""
    try:
        # Start default session
        await session_manager.start()
        
        # 1. List sessions (should have default)
        sessions_json = list_sessions()
        sessions = json.loads(sessions_json)
        assert any(s["id"] == "default" for s in sessions["sessions"])
        
        # 2. Create a new session
        create_res_json = await create_session("mcp_test")
        create_res = json.loads(create_res_json)
        assert create_res["status"] == "created"
        assert create_res["session_id"] == "mcp_test"
        
        # 3. List sessions again
        sessions_json = list_sessions()
        sessions = json.loads(sessions_json)
        assert any(s["id"] == "mcp_test" for s in sessions["sessions"])
        assert len(sessions["sessions"]) >= 2
        
    finally:
        await session_manager.stop_all()

@pytest.mark.asyncio
async def test_mcp_run_command_with_session_id():
    """Test that run_command respects session_id."""
    try:
        await session_manager.start()
        
        # Create session A and B
        await create_session("A")
        await create_session("B")
        
        # Run command in A
        await run_command("scalar val = 1", session_id="A")
        # Run command in B
        await run_command("scalar val = 2", session_id="B")
        
        # Check values
        res_a_json = await run_command("display val", session_id="A")
        res_a = json.loads(res_a_json)
        assert "1" in res_a.get("smcl_output", "")
        
        res_b_json = await run_command("display val", session_id="B")
        res_b = json.loads(res_b_json)
        assert "2" in res_b.get("smcl_output", "")
        
    finally:
        await session_manager.stop_all()

@pytest.mark.asyncio
async def test_mcp_auto_create_session():
    """Test that session is automatically created if it doesn't exist."""
    try:
        await session_manager.start()
        
        # Run command in a non-existent session
        res_json = await run_command("display 999", session_id="auto_session")
        res = json.loads(res_json)
        assert res["rc"] == 0
        
        # Verify it was created
        sessions_json = list_sessions()
        sessions = json.loads(sessions_json)
        assert any(s["id"] == "auto_session" for s in sessions["sessions"])
        
    finally:
        await session_manager.stop_all()
