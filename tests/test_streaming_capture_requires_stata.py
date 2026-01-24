import anyio
import pytest
import json
import os
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
        assert "{com}. display 5+5" in res.stdout
        assert "{res}10" in res.stdout
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
        assert "{com}. do" in res.stdout
        assert "{res}a" in res.stdout
        assert "{res}b" in res.stdout
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


def test_streaming_graph_ready_dedup_no_log_pollution(client):
    commands = [
        "sysuse auto, clear",
        "reg price mpg",
        "twoway scatter price mpg, name(scatter1, replace)",
        "twoway scatter mpg price",
    ]

    graph_ready_events: list[dict] = []
    log_pollution: list[str] = []

    async def notify_log(msg: str) -> None:
        if "mcp_" in msg and ("saved" in msg or "found" in msg or "opened" in msg):
            if '"event": "graph_ready"' not in msg:
                log_pollution.append(msg)
        try:
            data = json.loads(msg)
            if data.get("event") == "graph_ready":
                graph_ready_events.append(data)
        except Exception:
            pass

    async def main() -> None:
        client._last_emitted_graph_signatures = {}
        prev_log_path = client._persistent_log_path
        prev_log_name = client._persistent_log_name
        client._run_internal("capture log close _all", echo=False)
        log_path = client._create_smcl_log_path()
        client._persistent_log_path = log_path
        client._persistent_log_name = "_mcp_session"
        client._run_internal(f'log using "{log_path}", name(_mcp_session) smcl replace', echo=False)

        try:
            for cmd in commands:
                resp = await client.run_command_streaming(
                    cmd,
                    notify_log=notify_log,
                    emit_graph_ready=True,
                    auto_cache_graphs=True,
                )
                assert resp.rc == 0
                smcl_output = resp.smcl_output or ""
                if "mcp_" in smcl_output and ("saved" in smcl_output or "found" in smcl_output or "opened" in smcl_output):
                    log_pollution.append(smcl_output)
        finally:
            client._run_internal("capture log close _mcp_session", echo=False)
            client._persistent_log_path = prev_log_path
            client._persistent_log_name = prev_log_name
            if prev_log_path and prev_log_name:
                try:
                    restored_path = prev_log_path.replace("\\", "/")
                    if os.path.exists(prev_log_path):
                        client._run_internal(
                            f'log using "{restored_path}", append smcl name({prev_log_name})',
                            echo=False,
                        )
                    else:
                        client._run_internal(
                            f'log using "{restored_path}", replace smcl name({prev_log_name})',
                            echo=False,
                        )
                except Exception:
                    pass
            if os.path.exists(log_path):
                try:
                    os.remove(log_path)
                except Exception:
                    pass

    anyio.run(main)

    assert len(graph_ready_events) == 2
    assert not log_pollution


def test_streaming_graph_bar_emits_graph_ready(client):
    graph_ready_events: list[dict] = []

    async def notify_log(msg: str) -> None:
        try:
            data = json.loads(msg)
        except Exception:
            return
        if data.get("event") == "graph_ready":
            graph_ready_events.append(data)

    async def main() -> None:
        client._last_emitted_graph_signatures = {}
        client._run_internal("capture graph drop _all", echo=False)
        try:
            await client.run_command_streaming(
                "sysuse auto, clear",
                notify_log=notify_log,
                emit_graph_ready=True,
                auto_cache_graphs=True,
            )
            await client.run_command_streaming(
                "graph bar price",
                notify_log=notify_log,
                emit_graph_ready=True,
                auto_cache_graphs=True,
            )
        finally:
            client._run_internal("capture graph drop _all", echo=False)

    anyio.run(main)

    assert len(graph_ready_events) >= 1
    assert graph_ready_events[-1]["graph"]["path"]

if __name__ == "__main__":
    pytest.main([__file__, "-v"])