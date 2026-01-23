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
