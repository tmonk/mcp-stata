import pytest
import json
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from mcp_stata.server import (
    stata_task_status,
    stata_inspect_data,
    stata_manage_session,
)


def _unwrap(result):
    return result.model_dump() if hasattr(result, "model_dump") else json.loads(result)


@pytest.mark.asyncio
async def test_stata_wait_for_task_unit():
    """Test blocking wait logic with mocked status polling."""
    from mcp_stata.server import BackgroundTask, _background_tasks
    import datetime

    task_id = "wait_test_task"
    task_info = BackgroundTask(
        task_id=task_id,
        kind="command",
        task=None,
        log_path="/tmp/test.log",
        created_at=datetime.datetime.now(),
    )
    _background_tasks[task_id] = task_info

    async def _mark_done():
        await asyncio.sleep(0.02)
        task_info.done = True
        task_info.result = json.dumps({"ok": True})

    marker_task = asyncio.create_task(_mark_done())
    try:
        result = _unwrap(await stata_task_status(task_id, wait=True, timeout=2, poll_interval=0.01))
        assert result["data"]["status"] == "done"
    finally:
        marker_task.cancel()
        if task_id in _background_tasks:
            del _background_tasks[task_id]

@pytest.mark.asyncio
async def test_stata_list_variables_unit():
    """Test that list variables correctly calls session and returns JSON."""
    mock_session = MagicMock()
    mock_session.call = MagicMock()
    # mock_session.call returns a coroutine that resolves to the result
    future = asyncio.Future()
    future.set_result({"variables": [{"name": "price"}]})
    mock_session.call.return_value = future
    
    with patch("mcp_stata.server.session_manager.get_or_create_session", return_value=mock_session):
        res = _unwrap(await stata_inspect_data(action="list", session_id="test_id"))
        assert "variables" in res["data"]
        assert res["data"]["variables"][0]["name"] == "price"
        mock_session.call.assert_called_with("list_variables_structured", {})

@pytest.mark.asyncio
async def test_get_task_status_unit():
    """Test get_task_status tool returns correct JSON structure."""
    from mcp_stata.server import BackgroundTask, _background_tasks
    import datetime
    
    task_id = "unit_test_task"
    _background_tasks[task_id] = BackgroundTask(
        task_id=task_id,
        kind="command",
        task=None,
        log_path="/tmp/test.log",
        created_at=datetime.datetime.now()
    )
    
    try:
        res = _unwrap(await stata_task_status(task_id))
        assert res["data"]["task_id"] == task_id
        assert res["data"]["status"] == "running"
    finally:
        if task_id in _background_tasks:
            del _background_tasks[task_id]

@pytest.mark.asyncio
async def test_get_task_status_failed_unit():
    """Test get_task_status tool returns failed status and error details."""
    from mcp_stata.server import BackgroundTask, _background_tasks
    from mcp_stata.models import ErrorEnvelope
    import datetime
    
    task_id = "fail_test_task"
    error_env = ErrorEnvelope(message="test error", rc=1)
    _background_tasks[task_id] = BackgroundTask(
        task_id=task_id,
        kind="command",
        task=None,
        log_path="/tmp/test_fail.log",
        created_at=datetime.datetime.now(),
        error="test error",
        error_details=error_env,
        done=True
    )
    
    try:
        res = _unwrap(await stata_task_status(task_id))
        assert res["data"]["task_id"] == task_id
        assert res["data"]["status"] == "failed"
        assert res["data"]["error"] == "test error"
        assert res["data"]["error_details"]["message"] == "test error"
        assert res["data"]["error_details"]["rc"] == 1
    finally:
        if task_id in _background_tasks:
            del _background_tasks[task_id]


@pytest.mark.asyncio
async def test_manage_session_history_actions_unit():
    mock_session = MagicMock()
    mock_session.get_history_stats.return_value = {
        "command_count": 4,
        "history_size": 3,
        "max_history_entries": 200,
        "earliest_command": 1,
        "latest_command": 4,
    }
    mock_session.get_session_diff = AsyncMock(return_value={
        "command_count": 4,
        "since_command": 3,
        "new_variables": ["z"],
        "removed_variables": [],
        "modified_macros": {},
        "removed_macros": [],
        "n_obs": 10,
        "n_vars": 3,
        "captured_at": "t1",
    })

    with patch("mcp_stata.server.session_manager.get_or_create_session", new=AsyncMock(return_value=mock_session)):
        stats = _unwrap(await stata_manage_session(action="history_stats", session_id="s1"))
        assert stats["session_id"] == "s1"
        assert stats["data"]["history_size"] == 3

        diff = _unwrap(await stata_manage_session(action="history_diff", session_id="s1", since_command=3))
        assert diff["session_id"] == "s1"
        assert diff["data"]["new_variables"] == ["z"]
