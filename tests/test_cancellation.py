import sys
import types

import anyio
import pytest

from anyio import get_cancelled_exc_class

pytestmark = pytest.mark.requires_stata


def test_request_break_in_invokes_breakin(monkeypatch, client):
    called = {"break": 0}

    class FakeSFI:
        def breakIn(self):
            called["break"] += 1

    monkeypatch.setitem(sys.modules, "sfi", FakeSFI())

    client._request_break_in()

    assert called["break"] == 1


@pytest.mark.anyio
async def test_wait_for_stata_stop_uses_poll_and_detects_breakerror(monkeypatch, client):
    class BreakError(Exception):
        pass

    class Toolkit:
        def __init__(self):
            self.calls = 0

        def pollnow(self):
            self.calls += 1
            raise BreakError()

    toolkit = Toolkit()
    sfi_mod = types.SimpleNamespace(SFIToolkit=toolkit, BreakError=BreakError)
    monkeypatch.setitem(sys.modules, "sfi", sfi_mod)

    stopped = await client._wait_for_stata_stop(timeout=0.2)

    assert stopped is True
    assert toolkit.calls >= 1


@pytest.mark.anyio
async def test_run_command_streaming_cancellation_triggers_break(monkeypatch, client):
    cancelled_exc = get_cancelled_exc_class()

    async def fake_notify_log(_text: str) -> None:
        return

    # Force cancellation when the worker thread is scheduled
    def fake_run_sync(*_args, **_kwargs):
        raise cancelled_exc()

    # Track that we signaled Stata and waited for stop
    called = {"break": 0, "wait": 0}

    monkeypatch.setitem(sys.modules, "sfi", types.SimpleNamespace())
    monkeypatch.setattr(client, "_maybe_rewrite_graph_name_in_command", lambda c: c)
    monkeypatch.setattr(client, "_request_break_in", lambda: called.__setitem__("break", called["break"] + 1))
    monkeypatch.setattr(
        client,
        "_wait_for_stata_stop",
        lambda: called.__setitem__("wait", called["wait"] + 1) or anyio.sleep(0),
    )
    monkeypatch.setattr(anyio.to_thread, "run_sync", fake_run_sync)

    with pytest.raises(cancelled_exc):
        await client.run_command_streaming(
            "display 1",
            notify_log=fake_notify_log,
            notify_progress=None,
            echo=False,
            trace=False,
            max_output_lines=None,
            cwd=None,
        )

    assert called["break"] == 1
    assert called["wait"] == 1
