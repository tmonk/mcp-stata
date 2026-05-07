import json
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_stata.models import ToolEnvelope
from mcp_stata.server import (
    BackgroundTask,
    project_manifest_resource,
    research_checklist_resource,
    session_logs_resource,
    stata_estimation_plan,
    stata_project_reproducibility_report,
    _background_tasks,
)


def _unwrap(result):
    return result.model_dump() if hasattr(result, "model_dump") else json.loads(result)


@pytest.mark.asyncio
async def test_project_manifest_resource_shape():
    payload = json.loads(await project_manifest_resource())
    assert payload["name"] == "mcp-stata"
    assert payload["skills_count"] >= 1
    assert "codex" in payload["supported_agents"]


@pytest.mark.asyncio
async def test_research_checklist_resource_reads_packaged_reference():
    text = await research_checklist_resource("data-audit")
    assert "audit" in text.lower()
    assert "missing" in text.lower()


@pytest.mark.asyncio
async def test_session_logs_resource_filters_by_session():
    _background_tasks.clear()
    _background_tasks["a"] = BackgroundTask(task_id="a", kind="command", task=None, session_id="s1", created_at=datetime.datetime.now())
    _background_tasks["b"] = BackgroundTask(task_id="b", kind="command", task=None, session_id="s2", created_at=datetime.datetime.now())

    payload = json.loads(await session_logs_resource("s1"))
    assert payload["session_id"] == "s1"
    assert [item["task_id"] for item in payload["logs"]] == ["a"]


@pytest.mark.asyncio
async def test_stata_estimation_plan_reports_missing_variables():
    mock_session = MagicMock()
    mock_session.call = AsyncMock(return_value={"variables": [{"name": "y"}, {"name": "x1"}, {"name": "fe"}]})

    with patch("mcp_stata.server.session_manager.get_or_create_session", new=AsyncMock(return_value=mock_session)):
        result = _unwrap(
            await stata_estimation_plan(
                dependent_var="y",
                independent_vars=["x1", "x2"],
                fixed_effects=["fe"],
                cluster_var="cluster_id",
                estimator="reghdfe",
            )
        )

    assert result["success"] is False
    assert sorted(result["data"]["missing_variables"]) == ["cluster_id", "x2"]
    assert "reghdfe y x1 x2, absorb(fe), vce(cluster cluster_id)" == result["data"]["command"]


@pytest.mark.asyncio
async def test_project_reproducibility_report_aggregates_tool_envelopes():
    with (
        patch(
            "mcp_stata.server.stata_manage_session",
            new=AsyncMock(
                side_effect=[
                    ToolEnvelope(tool="stata_manage_session", success=True, session_id="default", data={"stata_version": "19"}),
                    ToolEnvelope(tool="stata_manage_session", success=True, session_id="default", data={"sessions": []}),
                ]
            ),
        ),
        patch("mcp_stata.server._recent_session_logs", new=AsyncMock(return_value=[{"task_id": "x"}])),
    ):
        result = _unwrap(await stata_project_reproducibility_report())

    assert result["success"] is True
    assert result["data"]["environment"]["stata_version"] == "19"
    assert result["data"]["recent_logs"] == [{"task_id": "x"}]
