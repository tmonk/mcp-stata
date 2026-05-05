import pytest
import json
import asyncio
from mcp_stata.server import stata_run, stata_task_status

@pytest.mark.asyncio
async def test_stdout_truncation_e2e():
    """Test that massive outputs are truncated to stay within tool limits."""
    # Generate ~500KB of output. Each line is ~130 bytes. 4000 lines = 520KB.
    code = """
    forvalues i = 1/4000 {
        display "Line `i': This is a fairly long line of text intended to bloat the output buffer and trigger the truncation logic in server.py."
    }
    """
    res_json = await stata_run(code=code, as_json=True)
    res = json.loads(res_json)
    assert res["success"] is True, f"Command failed: {res.get('error_message')}"
    assert "stdout" in res
    stdout = res["stdout"]
    # Check for truncation marker
    assert "truncated" in stdout and "total characters" in stdout
    # Ensure it's not excessively large (limit is 100KB + markers)
    assert len(stdout) < 110000
    # Ensure we have the head and tail
    assert "Line 1:" in stdout
    assert "Line 4000:" in stdout

@pytest.mark.asyncio
async def test_error_visibility_sync_e2e():
    """Test that sync errors surface message and details clearly."""
    # Ensure a fresh state
    # Ensure a fresh state
    await stata_run(code="capture drop error_test", as_json=True)
    code = "gen error_test = 1\ngen error_test = 1"
    res_json = await stata_run(code=code, as_json=True)
    res = json.loads(res_json)
    
    assert res["success"] is False
    assert res["rc"] == 110
    # The message might contain slightly different text depending on Stata version
    assert "already defined" in res["error_message"]
    assert res["error"] is not None
    assert res["error"]["rc"] == 110
    assert "already defined" in res["error"]["message"]

@pytest.mark.asyncio
async def test_error_visibility_background_e2e():
    """Test that background failures surface details and tails in status."""
    await stata_run(code="capture drop back_error", as_json=True)
    
    code = "gen back_error = 1\ngen back_error = 1"
    start_json = await stata_run(code=code, background=True)
    start_res = json.loads(start_json)
    task_id = start_res["task_id"]
    
    # Wait for failure
    status_res = None
    for _ in range(20):
        res_json = await stata_task_status(task_id)
        status_res = json.loads(res_json)
        if status_res["status"] == "failed":
            break
        await asyncio.sleep(0.5)
    
    assert status_res["status"] == "failed"
    assert "already defined" in status_res["error"]
    assert "error_details" in status_res
    assert status_res["error_details"]["rc"] == 110
    assert "error_tail" in status_res
    assert "already defined" in status_res["error_tail"]
