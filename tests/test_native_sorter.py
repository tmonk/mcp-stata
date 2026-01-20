import numpy as np
import pyarrow as pa
import pytest

from mcp_stata.ui_http import _try_native_argsort


def _build_table():
    return pa.table(
        {
            "_n": [1, 2, 3, 4],
            "num": [3.0, 1.0, 2.0, np.nan],
            "txt": ["b", "a", None, "c"],
        }
    )


def test_native_argsort_mixed_fallback():
    table = _build_table()
    res = _try_native_argsort(
        table,
        ["num", "txt"],
        descending=[False, False],
        nulls_last=[True, True],
    )
    if res is None:
        return
    assert isinstance(res, list)
    assert all(isinstance(i, int) for i in res)
    assert res == [1, 2, 0, 3]


def test_native_sorter_numeric_direct():
    native = pytest.importorskip("mcp_stata._native_sorter")
    cols = [np.array([3.0, 1.0, np.nan, 2.0], dtype=np.float64)]
    res = native.argsort_numeric(cols, [False], [True])
    assert res == [1, 3, 0, 2]


def test_native_sorter_mixed_direct():
    native = pytest.importorskip("mcp_stata._native_sorter")
    cols = [
        np.array([2.0, 1.0, np.nan, 1.0], dtype=np.float64),
        ["b", "a", None, "c"],
    ]
    res = native.argsort_mixed(cols, [False, True], [False, False], [True, True])
    assert res == [1, 3, 0, 2]
