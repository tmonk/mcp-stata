"""Regression tests for FastMCP structured-tool companion text shaping."""

from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities import func_metadata as func_metadata_module

import mcp_stata.server  # noqa: F401 - side effect: installs FastMCP companion-text patch
from mcp_stata.fastmcp_text_compact import STRUCTURED_COMPANION_ENV
from mcp_stata.models import ToolEnvelope


async def _structured_fixture_tool() -> ToolEnvelope:
    """Minimal structured tool for exercising FuncMetadata.convert_result."""

    raise RuntimeError("not invoked in these tests")


def test_convert_result_omits_duplicate_unstructured_json_by_default(monkeypatch):
    monkeypatch.delenv(STRUCTURED_COMPANION_ENV, raising=False)
    env = ToolEnvelope(
        tool="stata_run",
        success=True,
        session_id="default",
        data={"command": "sysuse auto", "rc": 0},
    )
    tool = Tool.from_function(_structured_fixture_tool, structured_output=True)
    converted = tool.fn_metadata.convert_result(env.model_dump())
    assert isinstance(converted, tuple)
    unstructured, structured = converted
    assert unstructured == []
    assert structured["tool"] == "stata_run"


def test_convert_result_compact_retains_single_line_json_duplicate(monkeypatch):
    monkeypatch.setenv(STRUCTURED_COMPANION_ENV, "compact")
    env = ToolEnvelope(
        tool="stata_run",
        success=True,
        session_id="default",
        data={"command": "sysuse auto", "rc": 0},
    )
    tool = Tool.from_function(_structured_fixture_tool, structured_output=True)
    converted = tool.fn_metadata.convert_result(env.model_dump())
    assert isinstance(converted, tuple)
    unstructured, structured = converted
    assert structured["tool"] == "stata_run"
    text = unstructured[0].text
    assert isinstance(text, str)
    assert "\n" not in text
    assert "stata_run" in text


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
