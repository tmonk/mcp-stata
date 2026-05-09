import anyio
import pytest
import time


pytestmark = [pytest.mark.requires_stata, pytest.mark.perf]


def _run_perf(label: str, fn) -> float:
    start = time.perf_counter()
    fn()
    duration = time.perf_counter() - start
    print(f"PERF {label}: {duration:.3f}s")
    return duration


def test_perf_user_journey_basic_streaming(client):
    commands = [
        "sysuse auto, clear",
        "summarize price mpg weight",
        "display 2+2",
    ]

    async def main() -> None:
        async def notify_log(_msg: str) -> None:
            return None

        for cmd in commands:
            resp = await client.run_command_streaming(
                cmd,
                notify_log=notify_log,
                emit_graph_ready=False,
                auto_cache_graphs=False,
            )
            assert resp.rc == 0

    _run_perf("basic_streaming", lambda: anyio.run(main))


def test_perf_user_journey_graph_ready(client):
    commands = [
        "sysuse auto, clear",
        "twoway scatter price mpg, name(perf_scatter1, replace)",
        "twoway scatter mpg price",
    ]

    async def main() -> None:
        async def notify_log(_msg: str) -> None:
            return None

        for cmd in commands:
            resp = await client.run_command_streaming(
                cmd,
                notify_log=notify_log,
                emit_graph_ready=True,
                auto_cache_graphs=True,
            )
            assert resp.rc == 0

    _run_perf("graph_ready", lambda: anyio.run(main))


def test_perf_user_journey_exec_lightweight(client):
    def main() -> None:
        resp = client.exec_lightweight("display 10+32")
        assert resp.rc == 0

    _run_perf("exec_lightweight", main)


def test_perf_session_history_diff_tool_path():
    """Benchmark the managed-session history path with real commands."""
    from mcp_stata.server import stata_manage_session, stata_run, session_manager

    async def main() -> None:
        sid = "perf_hist"
        await session_manager.start()
        try:
            await stata_manage_session(action="create", session_id=sid)
            await stata_run("clear", session_id=sid)
            for idx in range(1, 11):
                await stata_run(f"gen v{idx} = {idx}", session_id=sid)

            stats = (await stata_manage_session(action="history_stats", session_id=sid)).data
            assert "history_size" in stats
            baseline = stats["latest_command"]

            await stata_run("gen v11 = 11", session_id=sid)
            diff = (await stata_manage_session(action="history_diff", session_id=sid, since_command=baseline)).data
            assert "new_variables" in diff
        finally:
            await session_manager.stop_all()

    _run_perf("session_history_diff_tool_path", lambda: anyio.run(main))
