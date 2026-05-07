import pytest
import os
import tempfile
from mcp_stata.server import (
    stata_manage_session,
    stata_inspect_data,
    session_manager
)

pytestmark = [pytest.mark.requires_stata, pytest.mark.xdist_group("stata_heavy")]


@pytest.mark.asyncio
async def test_toolkit_detect_action():
    """Test the 'detect' action in stata_manage_session."""
    try:
        await session_manager.start()

        info = (await stata_manage_session(action="detect")).data
        assert "stata_version" in info
        assert "flavor" in info
        assert "os" in info

        info_pkg = (await stata_manage_session(action="detect", include_packages=True)).data
        assert "packages" in info_pkg

    finally:
        await session_manager.stop_all()


@pytest.mark.asyncio
async def test_toolkit_lint_action():
    """Test the 'lint' action in stata_inspect_data."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.do', delete=False) as f:
        f.write("sysuse auto\ncd /tmp\n")
        temp_path = f.name

    try:
        await session_manager.start()

        env = await stata_inspect_data(action="lint", path=temp_path)
        result = env.data

        assert result["path"] == temp_path
        assert result["count"] >= 1
        assert any("cd" in v["message"] for v in result["violations"])

    finally:
        await session_manager.stop_all()
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@pytest.mark.asyncio
async def test_toolkit_lint_no_path():
    """Test lint action error when path is missing."""
    try:
        await session_manager.start()
        env = await stata_inspect_data(action="lint")
        assert env.success is False
        assert env.error is not None
    finally:
        await session_manager.stop_all()
