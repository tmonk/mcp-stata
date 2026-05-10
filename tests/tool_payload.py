"""Decode MCP ``CallToolResult`` payloads for mcp-stata structured tools."""

from __future__ import annotations

import json
from typing import Any

from mcp.types import CallToolResult, TextContent


def tool_payload_dict(result: CallToolResult) -> dict[str, Any]:
    """Return the ToolEnvelope-style dict from a ``tools/call`` result.

    Prefers unstructured ``content`` text when present (``compact`` companion mode). When
    ``content`` is empty, reads ``structuredContent`` — including FastMCP's union wrapper
    shape ``{\"result\": \"<json string>\"}``.
    """
    blocks = result.content
    if blocks:
        block = blocks[0]
        if not isinstance(block, TextContent):
            raise TypeError(f"Unsupported content block type: {type(block)!r}")
        return json.loads(block.text)

    structured = result.structuredContent
    if structured is None:
        raise ValueError("CallToolResult has no text content and no structuredContent")

    inner = structured.get("result")
    if isinstance(inner, str):
        return json.loads(inner)
    if isinstance(inner, dict):
        return inner

    return dict(structured)


def tool_payload_text(result: CallToolResult) -> str:
    """Raw JSON text for helpers that previously read ``content[0].text``."""
    blocks = result.content
    if blocks:
        block = blocks[0]
        if not isinstance(block, TextContent):
            raise TypeError(f"Unsupported content block type: {type(block)!r}")
        return block.text

    structured = result.structuredContent
    if structured is None:
        raise ValueError("CallToolResult has no text content and no structuredContent")

    inner = structured.get("result")
    if isinstance(inner, str):
        return inner

    return json.dumps(structured if inner is None else inner, ensure_ascii=False)


def tool_result_has_payload(result: CallToolResult) -> bool:
    return bool(result.content) or result.structuredContent is not None
