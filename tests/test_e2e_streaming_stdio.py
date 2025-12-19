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


def test_e2e_streaming_run_do_file_stream_emits_log_before_completion(tmp_path):
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

    if not cli:
        pytest.skip("mcp-stata CLI not found on PATH or next to the active Python interpreter")

    dofile = tmp_path / "mcp_streaming_e2e.do"
    dofile.write_text('display "streaming_start"\n' 'sleep 1000\n' 'display "streaming_end"\n')

    logs: list[str] = []
    progress_events: list[tuple[float, float | None, str | None]] = []

    log_path_holder: dict[str, str] = {}

    async def logging_callback(params):
        # params is LoggingMessageNotificationParams
        text = str(getattr(params, "data", ""))
        logs.append(text)

        # Expect a single log_path event.
        try:
            payload = json.loads(text)
        except Exception:
            return
        if payload.get("event") == "log_path" and isinstance(payload.get("path"), str):
            log_path_holder["path"] = payload["path"]

    async def progress_callback(progress: float, total: float | None, message: str | None):
        progress_events.append((progress, total, message))

    async def main() -> None:
        server_params = StdioServerParameters(command=cli, args=[], cwd=os.getcwd())

        async with AsyncExitStack() as stack:
            read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream, logging_callback=logging_callback)
            )
            await session.initialize()

            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            if "run_do_file" not in tool_names:
                pytest.skip("Server does not expose run_do_file")

            saw_start = anyio.Event()
            done = anyio.Event()
            result_holder: dict[str, object] = {}

            saw_log_path = anyio.Event()

            async def watch_for_log_path() -> None:
                while True:
                    if "path" in log_path_holder:
                        saw_log_path.set()
                        return
                    await anyio.sleep(0.05)

            async def watch_log_file_for_start() -> None:
                await saw_log_path.wait()
                p = Path(log_path_holder["path"])
                # Wait until the file exists and contains our marker.
                while True:
                    if p.exists():
                        try:
                            txt = p.read_text(encoding="utf-8", errors="replace")
                            if "streaming_start" in txt:
                                saw_start.set()
                                return
                        except Exception:
                            pass
                    await anyio.sleep(0.05)

            async def call_tool() -> None:
                try:
                    result = await session.call_tool(
                        "run_do_file",
                        {
                            "path": str(dofile),
                            "echo": True,
                            "as_json": True,
                            "trace": False,
                            "raw": False,
                        },
                        progress_callback=progress_callback,
                    )
                    result_holder["result"] = result
                finally:
                    done.set()

            async with anyio.create_task_group() as tg:
                tg.start_soon(watch_for_log_path)
                tg.start_soon(watch_log_file_for_start)
                tg.start_soon(call_tool)

                with anyio.fail_after(5):
                    await saw_start.wait()

                # Critical assertion: we saw streamed output while the tool is still running.
                assert not done.is_set()

                with anyio.fail_after(30):
                    await done.wait()

            # Basic sanity checks.
            assert logs, "Expected to receive at least one log message notification"
            # End marker should be present in the log file.
            p = Path(log_path_holder["path"])
            assert p.exists()
            txt = p.read_text(encoding="utf-8", errors="replace")
            assert "streaming_end" in txt, "Expected to see end marker in log file"
            assert progress_events, "Expected to receive at least one progress notification"

    anyio.run(main)
