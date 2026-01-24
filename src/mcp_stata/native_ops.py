from __future__ import annotations

import logging
from typing import Iterable, Any, Tuple

logger = logging.getLogger(__name__)

try:
    from mcp_stata import _native_ops as _native
except Exception:  # pragma: no cover - optional module
    _native = None


def argsort_numeric(
    columns: Iterable["numpy.ndarray"],
    descending: list[bool],
    nulls_last: list[bool],
) -> list[int] | None:
    if _native is None:
        return None
    cols = list(columns)
    if not cols:
        return []
    try:
        return _native.argsort_numeric(cols, descending, nulls_last)
    except Exception as e:
        logger.warning(f"Native numeric sort failed: {e}")
        return None


def argsort_mixed(
    columns: Iterable[object],
    is_string: list[bool],
    descending: list[bool],
    nulls_last: list[bool],
) -> list[int] | None:
    if _native is None:
        return None
    cols = list(columns)
    if not cols:
        return []
    try:
        return _native.argsort_mixed(cols, is_string, descending, nulls_last)
    except Exception as e:
        logger.warning(f"Native mixed sort failed: {e}")
        return None


def smcl_to_markdown(smcl_text: str) -> str | None:
    if _native is None:
        return None
    try:
        return _native.smcl_to_markdown(smcl_text)
    except Exception as e:
        logger.warning(f"Native SMCL conversion failed: {e}")
        return None


def fast_scan_log(smcl_content: str, rc_default: int) -> Tuple[str, str, int | None] | None:
    if _native is None:
        return None
    try:
        return _native.fast_scan_log(smcl_content, rc_default)
    except Exception as e:
        logger.warning(f"Native log scanning failed: {e}")
        return None


def compute_filter_indices(
    filter_expr: str,
    names: list[str],
    columns: list[Any],
    is_string: list[bool],
) -> list[int] | None:
    if _native is None:
        return None
    try:
        return _native.compute_filter_indices(
            filter_expr,
            names,
            columns,
            is_string
        )
    except Exception as e:
        logger.warning(f"Native filtering failed: {e}")
        return None

