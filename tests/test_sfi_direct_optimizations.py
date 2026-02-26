"""Regression tests for the sfi-direct optimisation pass.

Every test here verifies that a hot-path method goes straight to the C-level
sfi.Data / sfi.Macro calls instead of the expensive stata.run() IPC
round-trips that ``get_dataset_state()`` performs internally.

Invariant: ``get_dataset_state`` must NOT be called by any of the methods
covered in this module.  If a test detects such a call it means a regression
has been introduced.
"""

from __future__ import annotations

import sys
import io
from unittest.mock import MagicMock, patch, call

import pyarrow as pa
import pytest

from mcp_stata.stata_client import StataClient
from mcp_stata.ui_http import UIChannelManager, handle_page_request


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_client() -> StataClient:
    client = StataClient()
    client._initialized = True
    client.stata = MagicMock()
    return client


def _make_sfi_mock(*, n: int = 5, k: int = 2, frame: str = "default") -> MagicMock:
    """Build a synthetic sfi module mock with the most common attributes."""
    mock_sfi = MagicMock()
    mock_sfi.Data.getObsTotal.return_value = n
    mock_sfi.Data.getVarCount.return_value = k
    mock_sfi.Macro.getGlobal.return_value = frame
    return mock_sfi


# ---------------------------------------------------------------------------
# 1. _require_data_in_memory – must not call get_dataset_state
# ---------------------------------------------------------------------------

class TestRequireDataInMemory:
    def test_does_not_call_get_dataset_state(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=10, k=3)
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with patch.object(client, "get_dataset_state", side_effect=AssertionError("get_dataset_state must not be called")) as mock_gds:
                client._require_data_in_memory()  # should not raise
                mock_gds.assert_not_called()

    def test_uses_sfi_data_directly(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=10, k=3)
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            client._require_data_in_memory()
        mock_sfi.Data.getObsTotal.assert_called_once()
        mock_sfi.Data.getVarCount.assert_called_once()

    def test_raises_when_empty(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=0, k=0)
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with pytest.raises(RuntimeError, match="No data in memory"):
                client._require_data_in_memory()

    def test_ok_when_k_positive_n_zero(self):
        """Dataset with vars but no obs is considered valid (e.g. after clear obs)."""
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=0, k=2)
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            client._require_data_in_memory()  # should not raise


# ---------------------------------------------------------------------------
# 2. validate_filter_expr – must not call get_dataset_state
# ---------------------------------------------------------------------------

class TestValidateFilterExpr:
    def test_does_not_call_get_dataset_state(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=10, k=2)
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with patch.object(client, "get_dataset_state", side_effect=AssertionError("get_dataset_state must not be called")) as mock_gds:
                # A filter with no variable references is validated without sfi variable lookup
                client.validate_filter_expr("1 == 1")
                mock_gds.assert_not_called()

    def test_uses_sfi_data_for_n_k(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=10, k=2)
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            client.validate_filter_expr("True")
        mock_sfi.Data.getObsTotal.assert_called()
        mock_sfi.Data.getVarCount.assert_called()

    def test_raises_on_no_data(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=0, k=0)
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with pytest.raises(RuntimeError, match="No data in memory"):
                client.validate_filter_expr("price > 0")


# ---------------------------------------------------------------------------
# 3. compute_view_indices – must not call get_dataset_state
# ---------------------------------------------------------------------------

class TestComputeViewIndices:
    def test_does_not_call_get_dataset_state(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=3, k=1)
        mock_sfi.Data.getVarName.side_effect = lambda i: "price"
        mock_sfi.Data.get.return_value = [[10.0], [20.0], [30.0]]
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with patch.object(client, "get_dataset_state", side_effect=AssertionError("get_dataset_state must not be called")) as mock_gds:
                indices = client.compute_view_indices("price > 15")
                mock_gds.assert_not_called()
        assert 0 not in indices  # row 0: price=10 fails
        assert 1 in indices      # row 1: price=20 passes
        assert 2 in indices      # row 2: price=30 passes

    def test_raises_on_no_data(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=0, k=0)
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with pytest.raises(RuntimeError, match="No data in memory"):
                client.compute_view_indices("price > 0")


# ---------------------------------------------------------------------------
# 4. apply_sort – must not call get_dataset_state for empty guard
# ---------------------------------------------------------------------------

class TestApplySort:
    def test_does_not_call_get_dataset_state(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=5, k=2)
        mock_sfi.Data.getVarName.side_effect = lambda i: ["price", "make"][i]
        client.stata.run = MagicMock()  # absorb the actual gsort call
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with patch.object(client, "get_dataset_state", side_effect=AssertionError("get_dataset_state must not be called")) as mock_gds:
                client.apply_sort(["+price"])
                mock_gds.assert_not_called()

    def test_raises_on_no_data(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=0, k=0)
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with pytest.raises(RuntimeError, match="No data in memory"):
                client.apply_sort(["+price"])


# ---------------------------------------------------------------------------
# 5. _get_var_index_map – cache hit on 2nd call, invalidated by command
# ---------------------------------------------------------------------------

class TestGetVarIndexMap:
    def test_caches_on_second_call(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=5, k=2)
        mock_sfi.Data.getVarName.side_effect = lambda i: ["price", "make"][i]
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            result1 = client._get_var_index_map()
            result2 = client._get_var_index_map()

        # sfi.Data should only have been queried once (second call hits cache)
        assert mock_sfi.Data.getVarName.call_count == 2  # once per var in first call
        assert result1 == result2 == {"price": 0, "make": 1}

    def test_cache_invalidated_by_command_idx(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=5, k=2)
        mock_sfi.Data.getVarName.side_effect = lambda i: ["price", "make"][i]
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            client._get_var_index_map()
            first_call_count = mock_sfi.Data.getVarName.call_count

            # Simulate user command
            client._increment_command_idx()

            # Update stub for new schema
            mock_sfi.Data.getObsTotal.return_value = 5
            mock_sfi.Data.getVarCount.return_value = 3
            mock_sfi.Data.getVarName.side_effect = lambda i: ["price", "make", "mpg"][i]

            result2 = client._get_var_index_map()

        # Second query should re-hit sfi
        assert mock_sfi.Data.getVarName.call_count > first_call_count
        assert "mpg" in result2

    def test_does_not_call_get_dataset_state(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=5, k=1)
        mock_sfi.Data.getVarName.return_value = "x"
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with patch.object(client, "get_dataset_state", side_effect=AssertionError("must not be called")) as mock_gds:
                client._get_var_index_map()
                mock_gds.assert_not_called()


# ---------------------------------------------------------------------------
# 6. list_variables_rich – cache hit on 2nd call, invalidated by command
# ---------------------------------------------------------------------------

class TestListVariablesRich:
    def test_caches_on_second_call(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=5, k=2)
        mock_sfi.Data.getVarName.side_effect = lambda i: ["price", "make"][i]
        mock_sfi.Data.getVarLabel.side_effect = lambda i: ""
        mock_sfi.Data.getVarFormat.side_effect = lambda i: "%9.0g"
        mock_sfi.Data.getVarType.side_effect = lambda i: "float"
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            result1 = client.list_variables_rich()
            result2 = client.list_variables_rich()

        # sfi.Data.getVarName should only be called during the first call
        assert mock_sfi.Data.getVarName.call_count == 2  # 2 vars in first call only
        assert result1 == result2

    def test_cache_invalidated_by_command_idx(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=5, k=1)
        mock_sfi.Data.getVarName.return_value = "price"
        mock_sfi.Data.getVarLabel.return_value = ""
        mock_sfi.Data.getVarFormat.return_value = "%9.0g"
        mock_sfi.Data.getVarType.return_value = "float"
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            client.list_variables_rich()
            first_count = mock_sfi.Data.getVarName.call_count

            client._increment_command_idx()

            # New variable added
            mock_sfi.Data.getVarCount.return_value = 2
            mock_sfi.Data.getVarName.side_effect = lambda i: ["price", "mpg"][i]

            result2 = client.list_variables_rich()

        assert mock_sfi.Data.getVarName.call_count > first_count
        names = [v["name"] for v in result2]
        assert "mpg" in names

    def test_does_not_call_get_dataset_state(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=5, k=1)
        mock_sfi.Data.getVarName.return_value = "x"
        mock_sfi.Data.getVarLabel.return_value = ""
        mock_sfi.Data.getVarFormat.return_value = "%9.0g"
        mock_sfi.Data.getVarType.return_value = "float"
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with patch.object(client, "get_dataset_state", side_effect=AssertionError("must not be called")) as mock_gds:
                client.list_variables_rich()
                mock_gds.assert_not_called()


# ---------------------------------------------------------------------------
# 7. get_page – returns frame/n/k; must not call get_dataset_state
# ---------------------------------------------------------------------------

class TestGetPageOptimizations:
    def test_includes_frame_n_k_in_result(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=3, k=2, frame="myframe")
        mock_sfi.Data.getVarName.side_effect = lambda i: ["price", "make"][i]
        mock_sfi.Data.get.return_value = [[100.0, "Toyota"], [200.0, "Honda"]]
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            result = client.get_page(
                offset=0,
                limit=2,
                vars=["price", "make"],
                include_obs_no=False,
                max_chars=100,
                obs_indices=None,
            )

        assert result["n"] == 3
        assert result["k"] == 2
        assert result["frame"] == "myframe"

    def test_does_not_call_get_dataset_state(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=3, k=2, frame="default")
        mock_sfi.Data.getVarName.side_effect = lambda i: ["price", "make"][i]
        mock_sfi.Data.get.return_value = [[100.0, "Toyota"]]
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with patch.object(client, "get_dataset_state", side_effect=AssertionError("get_dataset_state must not be called")) as mock_gds:
                client.get_page(
                    offset=0,
                    limit=1,
                    vars=["price", "make"],
                    include_obs_no=False,
                    max_chars=100,
                )
                mock_gds.assert_not_called()

    def test_frame_uses_sfi_macro(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=2, k=1, frame="myspecialframe")
        mock_sfi.Data.getVarName.return_value = "x"
        mock_sfi.Data.get.return_value = [[1.0], [2.0]]
        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            result = client.get_page(
                offset=0,
                limit=2,
                vars=["x"],
                include_obs_no=False,
                max_chars=100,
            )

        assert result["frame"] == "myspecialframe"
        mock_sfi.Macro.getGlobal.assert_called_with("c(frame)")


# ---------------------------------------------------------------------------
# 8. get_arrow_stream – must not call get_dataset_state (Phase-1 invariant)
# ---------------------------------------------------------------------------

class TestGetArrowStreamNoDatasetState:
    def test_does_not_call_get_dataset_state(self):
        client = _make_client()
        mock_sfi = _make_sfi_mock(n=2, k=2)
        mock_sfi.Data.getVarName.side_effect = lambda i: ["v1", "v2"][i]
        mock_sfi.Data.get.return_value = [[1, "a"], [2, "b"]]

        with patch.dict(sys.modules, {"sfi": mock_sfi}):
            with patch.object(client, "get_dataset_state", side_effect=AssertionError("get_dataset_state must not be called")) as mock_gds:
                client.get_arrow_stream(
                    offset=0,
                    limit=2,
                    vars=["v1", "v2"],
                    include_obs_no=False,
                    obs_indices=None,
                )
                mock_gds.assert_not_called()


# ---------------------------------------------------------------------------
# 9. UIChannelManager._dataset_id_from_state – new helper
# ---------------------------------------------------------------------------

class TestDatasetIdFromState:
    def _make_manager(self) -> UIChannelManager:
        # Minimal UIChannelManager with mocked proxy infrastructure
        proxy = MagicMock()
        proxy.get_dataset_state.return_value = {
            "frame": "default",
            "n": 100,
            "k": 5,
            "sortlist": "",
        }
        mgr = UIChannelManager.__new__(UIChannelManager)
        import threading
        mgr._lock = threading.Lock()
        mgr._dataset_version = 0
        mgr._dataset_id_caches = {}
        mgr._sessions = {"default": MagicMock()}
        mgr._sessions["default"].proxy = proxy
        return mgr

    def test_returns_string_digest(self):
        mgr = self._make_manager()
        state = {"frame": "default", "n": 100, "k": 5, "sortlist": ""}
        digest = mgr._dataset_id_from_state("default", state)
        assert isinstance(digest, str)
        assert len(digest) > 0

    def test_caches_result(self):
        mgr = self._make_manager()
        state = {"frame": "default", "n": 100, "k": 5, "sortlist": ""}
        digest1 = mgr._dataset_id_from_state("default", state)
        digest2 = mgr._dataset_id_from_state("default", state)
        assert digest1 == digest2

    def test_different_state_different_digest(self):
        mgr = self._make_manager()
        state_a = {"frame": "default", "n": 100, "k": 5, "sortlist": ""}
        state_b = {"frame": "other", "n": 50, "k": 3, "sortlist": ""}
        # Reset version cache between calls so we don't get a stale hit
        mgr._dataset_id_caches = {}
        mgr._dataset_version = 1
        digest_a = mgr._dataset_id_from_state("default", state_a)
        mgr._dataset_id_caches = {}
        mgr._dataset_version = 2
        digest_b = mgr._dataset_id_from_state("default", state_b)
        assert digest_a != digest_b


# ---------------------------------------------------------------------------
# 10. handle_page_request – must not call proxy.get_dataset_state
# ---------------------------------------------------------------------------

class TestHandlePageRequestNoDatasetState:
    def _make_manager_with_proxy(self, proxy: MagicMock) -> MagicMock:
        manager = MagicMock(spec=UIChannelManager)
        manager.limits.return_value = (500, 200, 500, 1_000_000)
        manager.current_dataset_id.return_value = "tid"
        manager._client = proxy
        return manager

    def test_does_not_call_get_dataset_state(self):
        proxy = MagicMock()
        proxy.get_page.return_value = {
            "returned": 2,
            "vars": ["price"],
            "rows": [[100], [200]],
            "truncated_cells": 0,
            "frame": "default",
            "n": 10,
            "k": 1,
        }
        proxy.get_dataset_state.side_effect = AssertionError("get_dataset_state must not be called")
        manager = self._make_manager_with_proxy(proxy)

        body = {
            "datasetId": "tid",
            "frame": "default",
            "offset": 0,
            "limit": 2,
            "vars": ["price"],
        }

        result = handle_page_request(manager, body, view_id=None)
        proxy.get_dataset_state.assert_not_called()

    def test_response_contains_frame_n_k_from_page(self):
        proxy = MagicMock()
        proxy.get_page.return_value = {
            "returned": 1,
            "vars": ["price"],
            "rows": [[999]],
            "truncated_cells": 0,
            "frame": "specialframe",
            "n": 42,
            "k": 7,
        }
        manager = self._make_manager_with_proxy(proxy)

        body = {
            "datasetId": "tid",
            "frame": "specialframe",
            "offset": 0,
            "limit": 1,
            "vars": ["price"],
        }

        result = handle_page_request(manager, body, view_id=None)
        assert result["dataset"]["frame"] == "specialframe"
        assert result["dataset"]["n"] == 42
        assert result["dataset"]["k"] == 7


# ---------------------------------------------------------------------------
# 11. _get_sort_table – must not call proxy.get_dataset_state
# ---------------------------------------------------------------------------

class TestGetSortTableNoDatasetState:
    def _make_manager(self) -> UIChannelManager:
        mgr = UIChannelManager.__new__(UIChannelManager)
        import threading
        mgr._lock = threading.Lock()
        mgr._sort_table_cache = {}
        mgr._sort_table_order = []
        mgr._sort_table_max_entries = 4
        return mgr

    def test_does_not_call_proxy_get_dataset_state(self):
        mgr = self._make_manager()

        proxy = MagicMock()
        proxy.get_dataset_state.side_effect = AssertionError("get_dataset_state must not be called")

        # Return a minimal Arrow table as bytes
        table = pa.table({"_n": [1, 2, 3], "price": [30.0, 10.0, 20.0]})
        sink = io.BytesIO()
        with pa.ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)
        proxy.get_arrow_stream.return_value = sink.getvalue()

        with patch.object(mgr, "_get_proxy_for_session", return_value=proxy):
            with patch.object(mgr, "_get_cached_sort_table", return_value=None):
                with patch.object(mgr, "_set_cached_sort_table"):
                    result = mgr._get_sort_table("default", "ds1", ["price"])

        proxy.get_dataset_state.assert_not_called()
        assert result is not None
        assert result.num_rows == 3

    def test_returns_none_for_empty_dataset(self):
        mgr = self._make_manager()

        proxy = MagicMock()
        empty_table = pa.table({"_n": pa.array([], type=pa.int64()), "price": pa.array([], type=pa.float64())})
        sink = io.BytesIO()
        with pa.ipc.new_stream(sink, empty_table.schema) as writer:
            writer.write_table(empty_table)
        proxy.get_arrow_stream.return_value = sink.getvalue()

        with patch.object(mgr, "_get_proxy_for_session", return_value=proxy):
            with patch.object(mgr, "_get_cached_sort_table", return_value=None):
                with patch.object(mgr, "_set_cached_sort_table"):
                    result = mgr._get_sort_table("default", "ds1", ["price"])

        assert result is None
