
import os
import shutil
from contextlib import AsyncExitStack
import sys
from pathlib import Path
import sysconfig
import anyio
import pytest
import json
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

def test_cancel_task_tool_works():
    cli = find_mcp_stata_cli()
    if not cli:
        pytest.skip("mcp-stata CLI not found")

    logs: list[str] = []
    async def logging_callback(params):
        text = str(getattr(params, "data", ""))
        logs.append(text)

    async def main() -> None:
        server_params = StdioServerParameters(command=cli, args=[], cwd=os.getcwd())

        async with AsyncExitStack() as stack:
            read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream, logging_callback=logging_callback)
            )
            await session.initialize()

            # Start a long-running background command
            # Use a loop that is long but doesn't print too much
            code = "forvalues i = 1/1000000 { \n if mod(`i', 10000) == 0 { \n display `i' \n } \n }"
            result = await session.call_tool(
                "run_command_background",
                {"code": code}
            )
            
            payload = json.loads(result.content[0].text)
            task_id = payload.get("task_id")
            assert task_id, "Expected task_id in response"
            
            # Wait a bit for it to start
            await anyio.sleep(1.0)
            
            # Cancel it
            cancel_res = await session.call_tool(
                "cancel_task",
                {"task_id": task_id}
            )
            cancel_payload = json.loads(cancel_res.content[0].text)
            assert cancel_payload.get("status") == "cancelling"
            
            # Wait for it to finish (it should finish with an error/cancelled status)
            # Give it some time to cleanup
            await anyio.sleep(1.0)
            
            # Check result
            status_res = await session.call_tool(
                "get_task_result",
                {"task_id": task_id, "allow_polling": True}
            )
            status_payload = json.loads(status_res.content[0].text)
            
            # With our new architecture, a cancelled task should be 'done'
            assert status_payload.get("status") == "done"
            # It might have an error if we set it, or just be done.
            # In server.py _run(), it catches Exception but might not catch CancelledError explicitly 
            # and just let it happen.
            
            # The session should be responsive
            check_res = await session.call_tool("run_command", {"code": "display 999", "raw": False})
            assert "999" in check_res.content[0].text

    anyio.run(main)
