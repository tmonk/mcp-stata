import os
import shutil
import sys
import sysconfig
from pathlib import Path
import json
import anyio
import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

pytestmark = [pytest.mark.requires_stata, pytest.mark.integration]

def get_mcp_stata_cli():
    cli = shutil.which("mcp-stata")
    if not cli:
        candidates: list[Path] = []
        scripts_dir = sysconfig.get_path("scripts")
        if scripts_dir:
            scripts_path = Path(scripts_dir)
            if sys.platform == "win32":
                candidates.append(scripts_path / "mcp-stata.exe")
            candidates.append(scripts_path / "mcp-stata")
        exe_dir = Path(sys.executable).parent
        if sys.platform == "win32":
            candidates.append(exe_dir / "mcp-stata.exe")
        candidates.append(exe_dir / "mcp-stata")
        for candidate in candidates:
            if candidate.exists():
                cli = str(candidate)
                break
    return cli

@pytest.mark.asyncio
async def test_e2e_respects_mcp_stata_temp(tmp_path):
    cli = get_mcp_stata_cli()
    if not cli:
        pytest.skip("mcp-stata CLI not found")

    custom_temp = tmp_path / "e2e_stata_temp"
    custom_temp.mkdir()
    
    # We'll use absolute path for the env var
    custom_temp_str = str(custom_temp.resolve())
    
    log_path_holder = {}
    
    async def logging_callback(params):
        text = str(getattr(params, "data", ""))
        try:
            payload = json.loads(text)
            if payload.get("event") == "log_path":
                log_path_holder["path"] = payload["path"]
        except Exception:
            pass

    server_params = StdioServerParameters(
        command=cli, 
        args=[], 
        env={**os.environ, "MCP_STATA_TEMP": custom_temp_str}
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write, logging_callback=logging_callback) as session:
            await session.initialize()
            
            # Run a simple command to trigger log creation
            await session.call_tool("run_command", {"code": "display 123"})
            
            # Wait a bit for the log path notification
            for _ in range(20):
                if "path" in log_path_holder:
                    break
                await anyio.sleep(0.1)
                
            assert "path" in log_path_holder
            log_path = log_path_holder["path"]
            
            # verify that log_path is inside custom_temp
            # On macOS, /var can be /private/var, so we resolve both
            assert os.path.abspath(log_path).startswith(os.path.abspath(custom_temp_str))
            
            # Check for cleanup after disconnect if we can
            # But cleanup happens on process exit, which happens when the session closes.
    
# After session closes, the subprocess should exit.
        # We verify that the log path was indeed inside our custom temp dir
        assert os.path.abspath(log_path).startswith(os.path.abspath(custom_temp_str))
        
        # Cleanup verification in E2E is often flaky depending on how the supervisor 
        # terminates the process (SIGTERM vs SIGKILL). 
        # Robust cleanup is verified in unit tests (test_temp_utils_unit.py).
