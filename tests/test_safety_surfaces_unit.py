from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_stata.models import CommandResponse, ToolEnvelope
from mcp_stata.server import stata_doctor, stata_load_data, stata_manage_session, stata_run


def _unwrap(result):
    return result.model_dump() if hasattr(result, "model_dump") else result


@pytest.mark.asyncio
async def test_stata_run_read_only_blocks_mutation():
    result = _unwrap(await stata_run("drop price", read_only=True))
    assert result["success"] is False
    assert "read_only=True" in result["error"]["message"]


@pytest.mark.asyncio
async def test_stata_load_data_blocks_unsafe_path():
    result = _unwrap(await stata_load_data("~/.ssh/private_data.dta"))
    assert result["success"] is False
    assert "protected directory" in result["error"]["message"] or "allowed project" in result["error"]["message"]


@pytest.mark.asyncio
async def test_manage_session_detect_adds_package_summary():
    mock_session = MagicMock()
    mock_session.call = AsyncMock(
        side_effect=[
            CommandResponse(command="display c(stata_version)", success=True, rc=0, stdout="19.5").model_dump(),
            CommandResponse(command="display c(version)", success=True, rc=0, stdout="19.5").model_dump(),
            CommandResponse(command="display c(flavor)", success=True, rc=0, stdout="IC").model_dump(),
            CommandResponse(command="display c(os)", success=True, rc=0, stdout="Unix").model_dump(),
            CommandResponse(command="display c(osdtl)", success=True, rc=0, stdout="").model_dump(),
            CommandResponse(command="display c(machine_type)", success=True, rc=0, stdout="Mac").model_dump(),
            CommandResponse(command="ado", success=True, rc=0, stdout="reghdfe\ncoefplot\n").model_dump(),
        ]
    )

    with patch("mcp_stata.server.session_manager.get_or_create_session", new=AsyncMock(return_value=mock_session)):
        result = _unwrap(await stata_manage_session(action="detect", include_packages=True))

    assert result["success"] is True
    assert result["data"]["package_summary"]["reghdfe"] is True
    assert result["data"]["package_summary"]["gtools"] is False


@pytest.mark.asyncio
async def test_stata_doctor_aggregates_smoke_checks():
    with (
        patch("mcp_stata.server.session_manager.get_or_create_session", new=AsyncMock(return_value=MagicMock())),
        patch(
            "mcp_stata.server.stata_manage_session",
            new=AsyncMock(return_value=ToolEnvelope(tool="stata_manage_session", success=True, session_id="doctor", data={"package_summary": {"reghdfe": True}})),
        ),
        patch(
            "mcp_stata.server.stata_run",
            new=AsyncMock(return_value=ToolEnvelope(tool="stata_run", success=True, session_id="doctor", data={"stdout": "4"})),
        ),
        patch(
            "mcp_stata.server.stata_manage_graphs",
            new=AsyncMock(return_value=ToolEnvelope(tool="stata_manage_graphs", success=True, session_id="doctor", data={"graphs": []})),
        ),
    ):
        result = _unwrap(await stata_doctor())

    assert result["success"] is True
    assert len(result["data"]["checks"]) == 3
