"""FastMCP structured-tool wire shaping: compact or omit duplicate unstructured JSON."""

from __future__ import annotations

import os
from collections.abc import Sequence
from itertools import chain
from typing import Any

import pydantic_core
from mcp.server.fastmcp.utilities.types import Audio, Image
from mcp.types import ContentBlock, TextContent

_PATCH_ATTR = "_mcp_stata_compact_tool_text_patch"
_PATCH_CONVERT_RESULT_ATTR = "_mcp_stata_convert_result_patch"

STRUCTURED_COMPANION_ENV = "MCP_STATA_STRUCTURED_COMPANION_TEXT"


def _structured_companion_mode() -> str:
    """Return ``compact`` (default) or ``omit`` for duplicate unstructured JSON."""

    return os.environ.get(STRUCTURED_COMPANION_ENV, "compact").strip().lower()


def install_compact_fastmcp_tool_text() -> None:
    """Adjust FastMCP tool results so duplicate JSON beside ``structuredContent`` is minimal.

    FastMCP's ``FuncMetadata.convert_result`` returns ``(unstructured, structured)`` for
    structured tools. The unstructured half uses ``_convert_to_content``, which historically
    serialized the same payload as pretty-printed JSON. MCP hosts often surface both channels,
    wasting tokens and vertical space.

    This module:

    - Replaces ``_convert_to_content`` with compact JSON (``indent=None``) by default
      (``MCP_STATA_STRUCTURED_COMPANION_TEXT=compact``).
    - Wraps ``FuncMetadata.convert_result`` so that the unstructured companion is retained
      unless explicitly suppressed via ``MCP_STATA_STRUCTURED_COMPANION_TEXT=omit``.

    Set ``MCP_STATA_STRUCTURED_COMPANION_TEXT=omit`` to return an empty ``content`` list while
    keeping ``structuredContent`` unchanged (for hosts that only use structured data).
    """
    from mcp.server.fastmcp.utilities import func_metadata as fm
    from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata

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

    if getattr(FuncMetadata, _PATCH_CONVERT_RESULT_ATTR, False):
        return

    _original_convert_result = FuncMetadata.convert_result

    def convert_result(self: FuncMetadata, result: Any) -> Any:
        converted = _original_convert_result(self, result)
        if _structured_companion_mode() == "compact":
            return converted
        if isinstance(converted, tuple) and len(converted) == 2:
            _unstructured, structured = converted
            return ([], structured)
        return converted

    FuncMetadata.convert_result = convert_result  # type: ignore[method-assign]
    setattr(FuncMetadata, _PATCH_CONVERT_RESULT_ATTR, True)
