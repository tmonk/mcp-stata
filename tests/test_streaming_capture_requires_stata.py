import anyio
import pytest

from mcp_stata.stata_client import StataClient


pytestmark = pytest.mark.requires_stata


def test_run_command_streaming_emits_log_and_progress():
    client = StataClient()
    # Ensure initialized (may no-op if already)
    client.init()

    logs: list[str] = []
    progress: list[tuple[float, float | None, str | None]] = []

    async def notify_log(chunk: str) -> None:
        logs.append(chunk)

    async def notify_progress(p: float, total: float | None, msg: str | None) -> None:
        progress.append((p, total, msg))

    async def main():
        res = await client.run_command_streaming(
            "display 5+5",
            notify_log=notify_log,
            notify_progress=notify_progress,
            echo=True,
        )
        assert res.rc == 0
        assert "10" in res.stdout

    anyio.run(main)

    # Should emit at least some log output and progress start/end
    assert len(logs) > 0
    assert any((p == 0 and msg is not None) for (p, _t, msg) in progress)
    assert any((p == 1 and msg == "Finished") for (p, _t, msg) in progress)


def test_run_do_file_streaming_progress_inference(tmp_path):
    client = StataClient()
    client.init()

    dofile = tmp_path / "stream_test.do"
    dofile.write_text('display "a"\ndisplay "b"\n')

    logs: list[str] = []
    progress: list[tuple[float, float | None, str | None]] = []

    async def notify_log(chunk: str) -> None:
        logs.append(chunk)

    async def notify_progress(p: float, total: float | None, msg: str | None) -> None:
        progress.append((p, total, msg))

    async def main():
        res = await client.run_do_file_streaming(
            str(dofile),
            notify_log=notify_log,
            notify_progress=notify_progress,
            echo=True,
        )
        assert res.rc == 0

    anyio.run(main)

    assert len(logs) > 0
    # At minimum we should have the initial progress message, and often inferred updates.
    assert len(progress) >= 1
