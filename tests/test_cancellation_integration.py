import asyncio
from pathlib import Path

import anyio
import pytest
import stata_setup
from anyio import get_cancelled_exc_class

from conftest import configure_stata_for_tests

# Configure real Stata; skip if not available
try:
    stata_dir, stata_flavor = configure_stata_for_tests()
    stata_setup.config(stata_dir, stata_flavor)
except (FileNotFoundError, PermissionError) as e:
    pytest.skip(f"Stata not found or not executable: {e}", allow_module_level=True)

pytestmark = pytest.mark.requires_stata


@pytest.mark.anyio
async def test_run_do_file_streaming_cancellation_long(monkeypatch, tmp_path: Path, client):
    """
    Integration test: run a long do-file, cancel it, and ensure the Stata break-in path is exercised.
    """
    # Create a long-running do file (sleep 10 seconds)
    do_file = tmp_path / "long_running.do"
    do_file.write_text(
        "\n".join(
            [
                "set more off",
                "capture noisily di \"starting long run\"",
                "sleep 10000",
                "capture noisily di \"should not reach here if cancelled\"",
            ]
        ),
        encoding="utf-8",
    )

    calls = {"break": 0, "wait": 0}

    async def notify_log(_text: str) -> None:
        return

    async def notify_progress(_p, _t, _m) -> None:
        return

    # Wrap break_in and wait helpers to observe they were invoked while still calling real behavior.
    orig_break = client._request_break_in
    orig_wait = client._wait_for_stata_stop

    def wrapped_break():
        calls["break"] += 1
        orig_break()

    async def wrapped_wait():
        calls["wait"] += 1
        return await orig_wait()

    monkeypatch.setattr(client, "_request_break_in", wrapped_break)
    monkeypatch.setattr(client, "_wait_for_stata_stop", wrapped_wait)

    cancelled_exc = get_cancelled_exc_class()

    async def runner():
        await client.run_do_file_streaming(
            str(do_file),
            notify_log=notify_log,
            notify_progress=notify_progress,
            echo=False,
            trace=False,
            max_output_lines=None,
            cwd=None,
        )

    # Use asyncio task cancellation to propagate CancelledError and trigger break handling.
    task = asyncio.create_task(runner())
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(cancelled_exc):
        await task

    assert calls["break"] >= 1
    assert calls["wait"] >= 1
