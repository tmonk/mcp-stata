from __future__ import annotations

from typing import Iterable

try:
    from mcp_stata import _native_sorter as _native
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
    return _native.argsort_numeric(cols, descending, nulls_last)


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
    return _native.argsort_mixed(cols, is_string, descending, nulls_last)
