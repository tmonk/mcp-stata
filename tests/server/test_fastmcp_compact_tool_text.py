"""Regression tests for compact FastMCP unstructured companion text."""

from mcp.server.fastmcp.utilities import func_metadata as func_metadata_module

import mcp_stata.server  # noqa: F401 - side effect: installs FastMCP companion-text patch
from mcp_stata.models import ToolEnvelope


def test_structured_tool_companion_text_is_single_line_json():
    env = ToolEnvelope(
        tool="stata_run",
        success=True,
        session_id="default",
        data={"command": "sysuse auto", "rc": 0},
    )
    blocks = func_metadata_module._convert_to_content(env)
    text = blocks[0].text
    assert isinstance(text, str)
    assert "\n" not in text
    assert "stata_run" in text
