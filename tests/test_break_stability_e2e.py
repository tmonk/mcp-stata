
import os
import shutil
import json
import time
import re
from contextlib import AsyncExitStack
import sys
from pathlib import Path
import sysconfig
import anyio
import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

pytestmark = [pytest.mark.requires_stata, pytest.mark.integration]

def find_mcp_stata_cli():
    cli = shutil.which("mcp-stata")
    if cli:
        return cli
    
    candidates: list[Path] = []
    scripts_dir = sysconfig.get_path("scripts")
    if scripts_dir:
        scripts_path = Path(scripts_dir)
        candidates.append(scripts_path / "mcp-stata")
    
    exe_dir = Path(sys.executable).parent
    candidates.append(exe_dir / "mcp-stata")
    
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None

def normalize_describe(text: str) -> str:
    # If it looks like a JSON response string (because raw=False returns the JSON string in content[0].text)
    # try to parse it and get only the 'stdout'
    try:
        data = json.loads(text)
        text = data.get("stdout", text)
    except:
        pass

    # Remove the . desc echo if present
    text = re.sub(r"^\. desc.*?\n", "", text, flags=re.MULTILINE)
    # Remove the "Contains data from ..." line which has paths
    text = re.sub(r"Contains data from.*?\n", "", text)
    # Remove the timestamp in the Variables line if it exists
    # e.g. "Variables:            74                  1 Feb 2026 12:00"
    text = re.sub(r"(\d+)\s+\d+\s+[A-Z][a-z]{2}\s+\d{4}\s+\d{2}:\d{2}", r"\1", text)
    # Strip SMCL tags
    text = re.sub(r"\{[^}]+\}", "", text)
    # Normalize whitespace
    lines = [line.strip() for line in text.strip().splitlines()]
    return "\n".join([l for l in lines if l])

@pytest.mark.anyio
async def test_session_stability_after_break():
    cli = find_mcp_stata_cli()
    if not cli:
        pytest.skip("mcp-stata CLI not found")

    server_params = StdioServerParameters(command=cli, args=[], cwd=os.getcwd())

    async with AsyncExitStack() as stack:
        read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        # 1. sysuse auto, clear
        await session.call_tool("run_command", {"code": "sysuse auto, clear"})

        # 2. desc' DESC OUTPUT long running code' (Save baseline)
        desc_res1 = await session.call_tool("run_command", {"code": "desc", "raw": False})
        baseline = normalize_describe(desc_res1.content[0].text)
        print(f"\n[DEBUG] Baseline describe length: {len(baseline)}")

        # 3. long running background code
        # We use a display in a loop but with mod to keep output manageable
        code = "forvalues i = 1/1000000 { if mod(`i', 1000) == 0 { display `i' } }"
        bg_res = await session.call_tool("run_command_background", {"code": code})
        task_id = json.loads(bg_res.content[0].text)["task_id"]

        # 4. Wait a bit for it to be mid-flight
        await anyio.sleep(1.0)

        # 5. BREAK
        print("[DEBUG] Sending cancel_task...")
        cancel_start = time.perf_counter()
        await session.call_tool("cancel_task", {"task_id": task_id})
        
        # 6. Immediately call desc
        print("[DEBUG] Calling describe immediately...")
        desc_res2 = await session.call_tool("run_command", {"code": "desc", "raw": False})
        immediacy_duration = time.perf_counter() - cancel_start
        print(f"[DEBUG] Immediate desc call took: {immediacy_duration:.4f}s")

        after_break = normalize_describe(desc_res2.content[0].text)

        # ASSERTIONS
        
        # Immediacy: Should be very fast. Setting 3s as a safe boundary for CI, 
        # but locally it should be < 0.5s after the break signal is acknowledged.
        assert immediacy_duration < 3.0, f"Describe call after break was slow: {immediacy_duration:.4f}s"

        # Consistency: State must be identical
        if baseline != after_break:
            print("\nBASELINE:\n" + baseline)
            print("\nAFTER BREAK:\n" + after_break)
        
        assert baseline == after_break, "Dataset state changed or describe output mismatched after break"

        # Final check on task state
        status_res = await session.call_tool("get_task_result", {"task_id": task_id, "allow_polling": True})
        status_payload = json.loads(status_res.content[0].text)
        assert status_payload["status"] == "done", "Interrupted task should be marked as done"

@pytest.mark.anyio
async def test_session_stability_after_break_session_tool():
    """
    Test break_session tool specifically. 
    This sends an out-of-band break to the session regardless of which command is running.
    """
    cli = find_mcp_stata_cli()
    if not cli:
        pytest.skip("mcp-stata CLI not found")

    server_params = StdioServerParameters(command=cli, args=[], cwd=os.getcwd())

    async with AsyncExitStack() as stack:
        read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        # 1. Setup
        await session.call_tool("run_command", {"code": "sysuse auto, clear"})
        desc_res1 = await session.call_tool("run_command", {"code": "desc", "raw": False})
        baseline = normalize_describe(desc_res1.content[0].text)

        # 2. Run background command
        code = "forvalues i = 1/1000000 { if mod(`i', 1000) == 0 { display `i' } }"
        bg_res = await session.call_tool("run_command_background", {"code": code})
        task_id = json.loads(bg_res.content[0].text)["task_id"]

        await anyio.sleep(1.0)

        # 3. Use break_session tool instead of cancel_task
        print("[DEBUG] Sending break_session...")
        cancel_start = time.perf_counter()
        await session.call_tool("break_session", {"session_id": "default"})
        
        # 4. Immediately call desc
        print("[DEBUG] Calling describe immediately...")
        desc_res2 = await session.call_tool("run_command", {"code": "desc", "raw": False})
        immediacy_duration = time.perf_counter() - cancel_start
        print(f"[DEBUG] Immediate desc call after break_session took: {immediacy_duration:.4f}s")

        after_break = normalize_describe(desc_res2.content[0].text)

        # ASSERTIONS
        assert immediacy_duration < 3.0
        assert baseline == after_break
        
        # Check background task also finished
        status_res = await session.call_tool("get_task_result", {"task_id": task_id, "allow_polling": True})
        status_payload = json.loads(status_res.content[0].text)
        assert status_payload["status"] == "done"

@pytest.mark.anyio
async def test_foreground_break_session_immediacy():
    """
    Test that break_session can interrupt a foreground run_command call.
    This requires concurrent execution in the test.
    """
    cli = find_mcp_stata_cli()
    if not cli:
        pytest.skip("mcp-stata CLI not found")

    server_params = StdioServerParameters(command=cli, args=[], cwd=os.getcwd())

    async with AsyncExitStack() as stack:
        read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        await session.call_tool("run_command", {"code": "sysuse auto, clear"})

        # Large loop in foreground - this WILL block the tool call
        code = "forvalues i = 1/10000000 { if mod(`i', 10000) == 0 { display `i' } }"
        
        start_time = time.perf_counter()
        
        async with anyio.create_task_group() as tg:
            # Task 1: Run blocking foreground command
            foreground_results = []
            async def run_foreground():
                print("[DEBUG] Starting foreground blocking command...")
                res = await session.call_tool("run_command", {"code": code})
                foreground_results.append(res)
                print(f"[DEBUG] Foreground command finished after {time.perf_counter() - start_time:.4f}s")

            tg.start_soon(run_foreground)
            
            # Wait for it to start producing output
            await anyio.sleep(1.5)
            
            # Task 2: Break it
            print("[DEBUG] Sending out-of-band break_session...")
            break_res = await session.call_tool("break_session", {"session_id": "default"})
            print(f"[DEBUG] break_session response: {break_res.content[0].text}")

        # After the task group exits, the foreground command should have returned
        assert len(foreground_results) == 1
        duration = time.perf_counter() - start_time
        
        # If it wasn't broken, a 10M iteration loop with display would take much longer than 5-10s
        # Typically it should finish within 2-3 seconds of the break signal.
        print(f"[DEBUG] Total test duration: {duration:.4f}s")
        assert duration < 10.0, f"Foreground command took too long to break: {duration:.4f}s"
        
        # Verify state is still OK
        desc_res = await session.call_tool("run_command", {"code": "desc", "raw": False})
        assert "Variable label" in desc_res.content[0].text
