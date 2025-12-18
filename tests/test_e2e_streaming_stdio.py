import os
import shutil
from contextlib import AsyncExitStack
import sys
from pathlib import Path

import anyio
import pytest

from mcp import ClientSession, StdioServerParameters, stdio_client


pytestmark = [pytest.mark.requires_stata, pytest.mark.integration]


def test_e2e_streaming_run_do_file_stream_emits_log_before_completion(tmp_path):
    cli = shutil.which("mcp-stata")
    if not cli:
        exe_dir = Path(sys.executable).resolve().parent
        candidates = [exe_dir / "mcp-stata"]
        if sys.platform == "win32":
            candidates.insert(0, exe_dir / "mcp-stata.exe")

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

    async def logging_callback(params):
        # params is LoggingMessageNotificationParams
        text = str(getattr(params, "data", ""))
        logs.append(text)

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
            if "run_do_file_stream" not in tool_names:
                pytest.skip("Server does not expose run_do_file_stream")

            saw_start = anyio.Event()
            done = anyio.Event()
            result_holder: dict[str, object] = {}

            async def watch_for_start() -> None:
                # Wait until a log message contains our marker.
                while True:
                    for entry in logs:
                        if "streaming_start" in entry:
                            saw_start.set()
                            return
                    await anyio.sleep(0.05)

            async def call_tool() -> None:
                try:
                    result = await session.call_tool(
                        "run_do_file_stream",
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
                tg.start_soon(watch_for_start)
                tg.start_soon(call_tool)

                with anyio.fail_after(5):
                    await saw_start.wait()

                # Critical assertion: we saw streamed output while the tool is still running.
                assert not done.is_set()

                with anyio.fail_after(30):
                    await done.wait()

            # Basic sanity checks.
            assert logs, "Expected to receive at least one log message notification"
            assert any("streaming_end" in e for e in logs), "Expected to see end marker in logs"
            assert progress_events, "Expected to receive at least one progress notification"

    anyio.run(main)
