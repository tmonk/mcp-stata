import os
import shutil
import json
import sys
import anyio
import pytest
from pathlib import Path
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters, stdio_client

from tool_payload import tool_payload_dict

pytestmark = [pytest.mark.requires_stata, pytest.mark.integration, pytest.mark.xdist_group("stata_heavy")]

def find_mcp_stata_cli():
    # Prefer local source execution for testing current changes
    src_dir = Path(__file__).parent.parent.parent / "src"
    if src_dir.exists():
        return f"{sys.executable} -m mcp_stata.server"
    
    cli = shutil.which("mcp-stata")
    if cli: return cli
    # Search common locations
    exe_dir = Path(sys.executable).parent
    candidates = [exe_dir / "mcp-stata", exe_dir / "mcp-stata.exe"]
    for c in candidates:
        if c.exists(): return str(c)
    return None

@pytest.mark.asyncio
async def test_e2e_command_isolation_and_log_path():
    """Verify that multiple command calls through the server return correct, isolated logs."""
    
    # Use direct python -m call to ensure we use local source code
    server_params = StdioServerParameters(
        command=sys.executable, 
        args=["-m", "mcp_stata.server"], 
        cwd=os.getcwd(),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent.parent / "src")}
    )

    async with AsyncExitStack() as stack:
        read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()

        def _log_path(env: dict) -> str | None:
            log_block = env.get("log") or {}
            return log_block.get("path") or (env.get("data") or {}).get("log_path")

        # Command 1
        res1 = await session.call_tool("stata_run", {"code": "display \"E2E_TOKEN_1\""})
        out1 = tool_payload_dict(res1)
        path1 = _log_path(out1)
        assert path1 and os.path.exists(path1)

        with open(path1, "r") as f:
            content1 = f.read()
        assert "E2E_TOKEN_1" in content1
        assert "E2E_TOKEN_2" not in content1

        # Command 2
        res2 = await session.call_tool("stata_run", {"code": "display \"E2E_TOKEN_2\""})
        out2 = tool_payload_dict(res2)
        path2 = _log_path(out2)
        assert path2 and os.path.exists(path2)
        assert path1 != path2

        with open(path2, "r") as f:
            content2 = f.read()
        assert "E2E_TOKEN_2" in content2
        # Isolation check: Command 1 should NOT be in Command 2's log path
        assert "E2E_TOKEN_1" not in content2

@pytest.mark.asyncio
async def test_e2e_preflight_bypass():
    """Verify that the server starts even if STATA_PATH is set but bypass enabled (lightweight check)."""
    
    server_params = StdioServerParameters(
        command=sys.executable, 
        args=["-m", "mcp_stata.server"], 
        cwd=os.getcwd(),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent.parent / "src")}
    )
    
    # Just verify we can initialize the session
    async with AsyncExitStack() as stack:
        read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        # This will time out if the server hangs during a long pre-flight
        with anyio.fail_after(60):
            await session.initialize()
        
        # Verify it responds
        tools = await session.list_tools()
        assert len(tools.tools) > 0
