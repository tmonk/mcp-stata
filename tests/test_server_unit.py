import pytest
import json
import asyncio
from unittest.mock import MagicMock, patch
from mcp_stata.server import (
    stata_task_status,
    stata_inspect_data
)

@pytest.mark.asyncio
async def test_stata_wait_for_task_unit():
    """Test blocking wait logic with mocked status polling."""
    # Mock stata_task_status to return 'running' then 'done'
    with patch("mcp_stata.server.stata_task_status") as mock_status:
        mock_status.side_effect = [
            json.dumps({"status": "running"}),
            json.dumps({"status": "done", "log_path": "/tmp/test.log"})
        ]
        
        # Use a short poll interval for testing
        result_json = await stata_task_status("test_id", action="wait", timeout=2, poll_interval=0.01)
        result = json.loads(result_json)
        
        assert result["status"] == "done"
        assert mock_status.call_count == 2

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
        res_json = await stata_inspect_data(action="list", session_id="test_id")
        res = json.loads(res_json)
        
        assert "variables" in res
        assert res["variables"][0]["name"] == "price"
        mock_session.call.assert_called_with("list_variables_structured", {})

def test_get_task_status_unit():
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
        res_json = stata_task_status(task_id, allow_polling=True)
        res = json.loads(res_json)
        assert res["task_id"] == task_id
        assert res["status"] == "running"
    finally:
        if task_id in _background_tasks:
            del _background_tasks[task_id]
