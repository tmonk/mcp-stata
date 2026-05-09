import pytest
import json
import asyncio
from mcp_stata.server import stata_run, stata_task_status

pytestmark = [pytest.mark.requires_stata]


@pytest.mark.asyncio
async def test_stdout_truncation_e2e():
    """Test that massive outputs are truncated to stay within tool limits."""
    code = """
    forvalues i = 1/4000 {
        display "Line `i': This is a fairly long line of text intended to bloat the output buffer and trigger the truncation logic in server.py."
    }
    """
    res = json.loads(await stata_run(code=code, as_json=True))
    assert res["success"] is True, f"Command failed: {(res.get('error') or {}).get('message')}"
    data = res["data"]
    stdout = data.get("stdout") or ""
    assert "truncated" in stdout and "total characters" in stdout
    assert len(stdout) < 110000
    assert "Line 4000:" in stdout
    assert "Line 1:" not in stdout


@pytest.mark.asyncio
async def test_error_visibility_sync_e2e():
    """Test that sync errors surface message and details clearly."""
    await stata_run(code="capture drop error_test", as_json=True)
    code = "gen error_test = 1\ngen error_test = 1"
    res = json.loads(await stata_run(code=code, as_json=True))

    assert res["success"] is False
    assert res["data"]["rc"] == 110
    assert res["error"] is not None
    assert res["error"]["rc"] == 110
    assert "already defined" in res["error"]["message"]


@pytest.mark.asyncio
async def test_error_visibility_background_e2e():
    """Test that background failures surface details and tails in status."""
    await stata_run(code="capture drop back_error", as_json=True)

    code = "gen back_error = 1\ngen back_error = 1"
    start_res = json.loads(await stata_run(code=code, background=True, as_json=True))
    task_id = start_res["data"]["task_id"]

    status_res = None
    for _ in range(20):
        status_res = json.loads(await stata_task_status(task_id, as_json=True))
        if status_res["data"]["status"] == "failed":
            break
        await asyncio.sleep(0.5)

    status_data = status_res["data"]
    assert status_data["status"] == "failed"
    assert "already defined" in status_data["error"]
    assert status_data["error_details"]["rc"] == 110
    assert "error_tail" in status_data
    assert "already defined" in status_data["error_tail"]
