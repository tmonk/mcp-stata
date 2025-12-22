import anyio
import pytest
import json
from pathlib import Path


pytestmark = pytest.mark.requires_stata


def test_run_command_streaming_emits_log_and_progress(client):

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
        assert res.stdout == ""
        assert res.log_path is not None
        assert Path(res.log_path).exists()

        # Output should be in the log file.
        text = Path(res.log_path).read_text(encoding="utf-8", errors="replace")
        assert "10" in text

    anyio.run(main)


def test_run_command_streaming_with_cwd_can_do_relative_file(tmp_path, client):
    project = tmp_path / "proj_cmd"
    project.mkdir()
    dofile = project / "rel.do"
    dofile.write_text('display "cmd-ok"\n')

    logs: list[str] = []

    async def notify_log(chunk: str) -> None:
        logs.append(chunk)

    async def main():
        res = await client.run_command_streaming(
            'do "rel.do"',
            notify_log=notify_log,
            notify_progress=None,
            echo=True,
            cwd=str(project),
        )
        assert res.success is True
        assert res.rc == 0
        assert res.log_path is not None
        text = Path(res.log_path).read_text(encoding="utf-8", errors="replace")
        assert "cmd-ok" in text

    anyio.run(main)

    # Should emit at least one log output event (log_path)
    assert len(logs) > 0
    payload = json.loads(logs[0])
    assert payload.get("event") == "log_path"
    assert Path(payload.get("path", "")).exists()


def test_run_do_file_streaming_progress_inference(tmp_path, client):
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
        assert res.stdout == ""
        assert res.log_path is not None
        assert Path(res.log_path).exists()

        text = Path(res.log_path).read_text(encoding="utf-8", errors="replace")
        assert "a" in text
        assert "b" in text

    anyio.run(main)

    assert len(logs) > 0
    payload = json.loads(logs[0])
    assert payload.get("event") == "log_path"
    assert Path(payload.get("path", "")).exists()
    # At minimum we should have the initial progress message, and often inferred updates.
    assert len(progress) >= 1


def test_run_do_file_streaming_with_cwd_and_relative_paths(tmp_path, client):
    project = tmp_path / "proj"
    project.mkdir()
    child = project / "child.do"
    child.write_text('display "child-ok"\n')
    parent = project / "parent.do"
    parent.write_text('do "child.do"\ndisplay "parent-ok"\n')

    logs: list[str] = []

    async def notify_log(chunk: str) -> None:
        logs.append(chunk)

    async def main():
        res = await client.run_do_file_streaming(
            "parent.do",
            notify_log=notify_log,
            notify_progress=None,
            echo=True,
            cwd=str(project),
        )
        assert res.success is True
        assert res.rc == 0
        assert res.log_path is not None
        text = Path(res.log_path).read_text(encoding="utf-8", errors="replace")
        assert "child-ok" in text
        assert "parent-ok" in text

    anyio.run(main)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])