import pytest
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
        await session_manager.start()

        sessions_env = await stata_manage_session(action="list")
        sessions = sessions_env.data
        assert any(s["id"] == "default" for s in sessions["sessions"])

        create_env = await stata_manage_session(action="create", session_id="mcp_test")
        create_res = create_env.data
        assert create_res["status"] == "created"
        assert create_res["session_id"] == "mcp_test"

        sessions_env = await stata_manage_session(action="list")
        sessions = sessions_env.data
        assert any(s["id"] == "mcp_test" for s in sessions["sessions"])
        assert len(sessions["sessions"]) >= 2

    finally:
        await session_manager.stop_all()


@pytest.mark.asyncio
async def test_mcp_run_command_with_session_id():
    """Test that run_command respects session_id."""
    try:
        await session_manager.start()

        await stata_manage_session(action="create", session_id="A")
        await stata_manage_session(action="create", session_id="B")
        await stata_run("display 123", session_id="A")
        await stata_run("scalar val = 2", session_id="B")

        res_a = (await stata_run("display val", session_id="A")).data
        assert "1" in (res_a.get("smcl_output") or "") or "1" in (res_a.get("stdout") or "")

        res_b = (await stata_run("display val", session_id="B")).data
        assert "2" in (res_b.get("smcl_output") or "") or "2" in (res_b.get("stdout") or "")

    finally:
        await session_manager.stop_all()


@pytest.mark.asyncio
async def test_mcp_auto_create_session():
    """Test that session is automatically created if it doesn't exist."""
    try:
        await session_manager.start()

        env = await stata_run("display 999", session_id="auto_session")
        assert env.success is True
        assert env.data.get("rc") == 0

        sessions_env = await stata_manage_session(action="list")
        sessions = sessions_env.data
        assert any(s["id"] == "auto_session" for s in sessions["sessions"])

    finally:
        await session_manager.stop_all()


@pytest.mark.asyncio
async def test_session_profile():
    """Test that session profile runs before every command."""
    try:
        await session_manager.start()

        await stata_manage_session(
            action="set_profile",
            code='global my_test_var "hello profile"',
            session_id="profile_test",
        )

        env = await stata_run('display "$my_test_var"', session_id="profile_test")
        assert "hello profile" in (env.data.get("stdout") or "")

        await stata_manage_session(
            action="set_profile",
            code='global my_test_var "updated profile"',
            session_id="profile_test",
        )
        env2 = await stata_run('display "$my_test_var"', session_id="profile_test")
        assert "updated profile" in (env2.data.get("stdout") or "")

    finally:
        await session_manager.stop_all()


@pytest.mark.asyncio
async def test_mcp_session_history_actions():
    """Exercise history_diff/history_stats through the existing manage-session tool."""
    try:
        await session_manager.start()
        sid = "hist_e2e"
        await stata_manage_session(action="create", session_id=sid)
        await stata_run("clear", session_id=sid)
        await stata_run("set obs 5", session_id=sid)
        await stata_run("gen x = _n", session_id=sid)

        stats = (await stata_manage_session(action="history_stats", session_id=sid)).data
        assert stats["session_id"] == sid
        assert stats["latest_command"] is not None
        baseline = stats["latest_command"]

        await stata_run("gen z = x^2", session_id=sid)
        diff = (
            await stata_manage_session(
                action="history_diff", session_id=sid, since_command=baseline
            )
        ).data
        assert diff["session_id"] == sid
        assert "z" in diff["new_variables"]
        assert diff["command_count"] >= baseline + 1
    finally:
        await session_manager.stop_all()
