import logging
import os

from mcp.server.fastmcp.utilities import logging as fastmcp_logging

import pytest
from mcp_stata.models import GraphListResponse
from mcp_stata.server import get_task_status, list_graphs_resource, logger, setup_logging, payload_logger
import mcp_stata.server as server


def test_tool_logging_includes_tool_name(caplog):
    caplog.set_level(logging.INFO, logger="mcp_stata")

    get_task_status("missing", allow_polling=True)

    messages = [record.getMessage() for record in caplog.records]
    assert any("MCP tool call: get_task_status request_id=None" in msg for msg in messages)


@pytest.mark.asyncio
async def test_resource_logging_includes_resource_name(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="mcp_stata")

    async def mock_list_graphs(*args, **kwargs):
        return GraphListResponse(graphs=[], active=None).model_dump_json()

    monkeypatch.setattr(server, "list_graphs", mock_list_graphs)

    await list_graphs_resource()

    messages = [record.getMessage() for record in caplog.records]
    assert any("MCP tool call: list_graphs_resource request_id=None" in msg for msg in messages)


def test_setup_logging_single_handler(monkeypatch):
    monkeypatch.delenv("MCP_STATA_CONFIGURE_LOGGING", raising=False)

    server._LOGGING_CONFIGURED = False
    logger.handlers = []
    payload_logger.handlers = []

    root_logger = logging.getLogger()
    mcp_logger = logging.getLogger("mcp.server.lowlevel.server")

    setup_logging()
    setup_logging()

    assert len(logger.handlers) == 1
    assert logger.propagate is False
    assert len(payload_logger.handlers) == 1
    assert payload_logger.propagate is False
    assert len(mcp_logger.handlers) == 1
    assert mcp_logger.propagate is False
    assert len(root_logger.handlers) == 0


def test_logging_uses_fastmcp_root_handlers(monkeypatch):
    monkeypatch.delenv("MCP_STATA_CONFIGURE_LOGGING", raising=False)
    server._LOGGING_CONFIGURED = False

    root_logger = logging.getLogger()
    root_logger.handlers = []

    fastmcp_logging.configure_logging("DEBUG")
    setup_logging()

    assert len(root_logger.handlers) == 0
    assert len(logger.handlers) == 1
    assert logger.propagate is False
    assert len(payload_logger.handlers) == 1
    assert payload_logger.propagate is False
