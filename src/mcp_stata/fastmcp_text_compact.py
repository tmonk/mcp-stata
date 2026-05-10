"""Compact unstructured companion text for FastMCP structured tools."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import chain
from typing import Any

import pydantic_core
from mcp.server.fastmcp.utilities.types import Audio, Image
from mcp.types import ContentBlock, TextContent

_PATCH_ATTR = "_mcp_stata_compact_tool_text_patch"


def install_compact_fastmcp_tool_text() -> None:
    """Use compact JSON for FastMCP's unstructured `content` alongside structured tools.

    FastMCP's `_convert_to_content` uses `pydantic_core.to_json(..., indent=2)`. MCP hosts
    often render both `structuredContent` and this companion text, so the indented copy
    adds a large vertical footprint for every tool call.

    This replaces that serializer with the default compact JSON (`indent=None`).
    """
    from mcp.server.fastmcp.utilities import func_metadata as fm

    if getattr(fm, _PATCH_ATTR, False):
        return

    def _convert_to_content(result: Any) -> Sequence[ContentBlock]:
        if result is None:  # pragma: no cover
            return []

        if isinstance(result, ContentBlock):
            return [result]

        if isinstance(result, Image):
            return [result.to_image_content()]

        if isinstance(result, Audio):
            return [result.to_audio_content()]

        if isinstance(result, list | tuple):
            return list(
                chain.from_iterable(_convert_to_content(item) for item in result)  # type: ignore[arg-type]
            )

        if not isinstance(result, str):
            result = pydantic_core.to_json(result, fallback=str).decode()

        return [TextContent(type="text", text=result)]

    fm._convert_to_content = _convert_to_content
    setattr(fm, _PATCH_ATTR, True)
