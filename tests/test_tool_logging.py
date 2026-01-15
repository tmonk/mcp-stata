import logging

from mcp_stata.models import GraphListResponse
from mcp_stata.server import get_task_status, list_graphs_resource, client


def test_tool_logging_includes_tool_name(caplog):
    caplog.set_level(logging.INFO, logger="mcp_stata")

    get_task_status("missing")

    messages = [record.getMessage() for record in caplog.records]
    assert any("MCP tool call: get_task_status request_id=None" in msg for msg in messages)


def test_resource_logging_includes_resource_name(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="mcp_stata")

    monkeypatch.setattr(client, "list_graphs_structured", lambda: GraphListResponse(graphs=[], active=None))

    list_graphs_resource()

    messages = [record.getMessage() for record in caplog.records]
    assert any("MCP tool call: list_graphs_resource request_id=None" in msg for msg in messages)
