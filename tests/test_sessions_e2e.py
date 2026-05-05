import json
import pytest
import asyncio
from mcp_stata.server import (
    stata_manage_session,
    stata_run,
    session_manager
)

# Mark as requiring Stata; group together so xdist doesn't run them in parallel
pytestmark = [pytest.mark.requires_stata, pytest.mark.xdist_group("stata_heavy")]

@pytest.mark.asyncio
async def test_mcp_session_tools():
    """Test session management tools via the server interface."""
    try:
        # Start default session
        await session_manager.start()
        
        # 1. List sessions (should have default)
        sessions_json = await stata_manage_session(action="list")
        sessions = json.loads(sessions_json)
        assert any(s["id"] == "default" for s in sessions["sessions"])
        
        # 2. Create a new session
        create_res_json = await stata_manage_session(action="create", session_id="mcp_test")
        create_res = json.loads(create_res_json)
        assert create_res["status"] == "created"
        assert create_res["session_id"] == "mcp_test"
        
        # 3. List sessions again
        sessions_json = await stata_manage_session(action="list")
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
        await stata_manage_session(action="create", session_id="A")
        await stata_manage_session(action="create", session_id="B")
                # Run a simple command to trigger log creation
        await stata_run("display 123", session_id="A")
        # Run command in B
        await stata_run("scalar val = 2", session_id="B")
        
        # Check values
        res_a_json = await stata_run("display val", session_id="A")
        res_a = json.loads(res_a_json)
        assert "1" in res_a.get("smcl_output", "") or "1" in res_a.get("stdout", "")
        
        res_b_json = await stata_run("display val", session_id="B")
        res_b = json.loads(res_b_json)
        assert "2" in res_b.get("smcl_output", "") or "2" in res_b.get("stdout", "")
        
    finally:
        await session_manager.stop_all()

@pytest.mark.asyncio
async def test_mcp_auto_create_session():
    """Test that session is automatically created if it doesn't exist."""
    try:
        await session_manager.start()
        
        # Run command in a non-existent session
        res_json = await stata_run("display 999", session_id="auto_session")
        res = json.loads(res_json)
        assert res.get("rc") == 0 or res.get("success") is True
        
        # Verify it was created
        sessions_json = await stata_manage_session(action="list")
        sessions = json.loads(sessions_json)
        assert any(s["id"] == "auto_session" for s in sessions["sessions"])
        
    finally:
        await session_manager.stop_all()


@pytest.mark.asyncio
async def test_session_profile():
    """Test that session profile runs before every command."""
    try:
        await session_manager.start()
        
        # Set profile to define a global
        await stata_manage_session(action="set_profile", code='global my_test_var "hello profile"', session_id="profile_test")
        
        # Run command that uses the global
        res_json = await stata_run('display "$my_test_var"', session_id="profile_test")
        res = json.loads(res_json)
        assert "hello profile" in res.get("stdout", "")
        
        # Clear profile and verify (it shouldn't run anymore, but the global might persist in the session)
        await stata_manage_session(action="set_profile", code='global my_test_var "updated profile"', session_id="profile_test")
        res2_json = await stata_run('display "$my_test_var"', session_id="profile_test")
        res2 = json.loads(res2_json)
        assert "updated profile" in res2.get("stdout", "")
        
    finally:
        await session_manager.stop_all()
