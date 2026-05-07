"""Tests for graph_ready emission: single UI artifact per graph per command."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from mcp_stata.stata_client import StataClient


@pytest.mark.asyncio
async def test_emit_graph_ready_dedupes_duplicate_names():
    client = StataClient.__new__(StataClient)
    client._command_idx = 42
    client._last_emitted_graph_signatures = {}
    client._current_command_code = 'scatter mpg weight, name(g1, replace)'
    client._get_cached_graph_path = MagicMock(return_value=None)
    client._get_graph_signature = MagicMock(return_value="sig1")
    client.export_graph = MagicMock(return_value="/tmp/test.svg")

    payloads: list[dict] = []

    async def notify_log(text: str) -> None:
        payloads.append(json.loads(text))

    await client._emit_graph_ready_for_graphs(
        ["g1", "g1"],
        notify_log=notify_log,
        task_id="t1",
        export_format="svg",
        graph_ready_initial={},
        restrict_to_command_text=False,
    )

    graph_ready = [p for p in payloads if p.get("event") == "graph_ready"]
    assert len(graph_ready) == 1
    assert graph_ready[0]["graph"]["name"] == "g1"


@pytest.mark.asyncio
async def test_emit_graph_ready_skips_repeat_signature_in_same_command():
    """Within the same _command_idx, a graph with an unchanged emit_key must not re-emit."""
    client = StataClient.__new__(StataClient)
    client._command_idx = 7
    client._last_emitted_graph_signatures = {}
    client._current_command_code = 'scatter mpg weight, name(g1, replace)'
    client._get_cached_graph_path = MagicMock(return_value=None)
    client._get_graph_signature = MagicMock(return_value="sig-stable")
    client.export_graph = MagicMock(return_value="/tmp/test.svg")

    payloads: list[dict] = []

    async def notify_log(text: str) -> None:
        payloads.append(json.loads(text))

    for _ in range(3):
        await client._emit_graph_ready_for_graphs(
            ["g1"],
            notify_log=notify_log,
            task_id="t1",
            export_format="svg",
            graph_ready_initial={},
            restrict_to_command_text=False,
        )

    graph_ready = [p for p in payloads if p.get("event") == "graph_ready"]
    assert len(graph_ready) == 1


@pytest.mark.asyncio
async def test_emit_graph_ready_re_emits_across_commands():
    """A new _command_idx with the same graph name should re-emit (covers identical repeat command)."""
    client = StataClient.__new__(StataClient)
    client._command_idx = 1
    client._last_emitted_graph_signatures = {}
    client._current_command_code = 'twoway scatter mpg price'
    client._get_cached_graph_path = MagicMock(return_value=None)
    client._get_graph_signature = MagicMock(return_value="sig-stable")
    client.export_graph = MagicMock(return_value="/tmp/test.svg")

    payloads: list[dict] = []

    async def notify_log(text: str) -> None:
        payloads.append(json.loads(text))

    await client._emit_graph_ready_for_graphs(
        ["Graph"],
        notify_log=notify_log,
        task_id="t1",
        export_format="svg",
        graph_ready_initial={},
        restrict_to_command_text=False,
    )
    client._command_idx = 2
    await client._emit_graph_ready_for_graphs(
        ["Graph"],
        notify_log=notify_log,
        task_id="t2",
        export_format="svg",
        graph_ready_initial={},
        restrict_to_command_text=False,
    )

    graph_ready = [p for p in payloads if p.get("event") == "graph_ready"]
    assert len(graph_ready) == 2


@pytest.mark.asyncio
async def test_graph_cache_callback_skips_log_when_disabled():
    sent: list[str] = []

    async def notify_log(text: str) -> None:
        sent.append(text)

    cb = StataClient._create_graph_cache_callback(
        None,
        notify_log,
        task_id="x",
        notify_graph_cached_log=False,
    )
    await cb("G", True)
    assert sent == []
