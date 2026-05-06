import json
import pytest
import asyncio
import os
import tempfile
from mcp_stata.server import (
    stata_manage_session,
    stata_inspect_data,
    session_manager
)

# Mark as requiring Stata
pytestmark = [pytest.mark.requires_stata, pytest.mark.xdist_group("stata_heavy")]

@pytest.mark.asyncio
async def test_toolkit_detect_action():
    """Test the 'detect' action in stata_manage_session."""
    try:
        await session_manager.start()
        
        res_json = await stata_manage_session(action="detect")
        info = json.loads(res_json)
        
        assert "stata_version" in info
        assert "flavor" in info
        assert "os" in info
        
        # Test with packages (might be slow, but it's an E2E test)
        res_pkg_json = await stata_manage_session(action="detect", include_packages=True)
        info_pkg = json.loads(res_pkg_json)
        assert "packages" in info_pkg
        
    finally:
        await session_manager.stop_all()

@pytest.mark.asyncio
async def test_toolkit_lint_action():
    """Test the 'lint' action in stata_inspect_data."""
    # Create a file with a violation
    with tempfile.NamedTemporaryFile(mode='w', suffix='.do', delete=False) as f:
        f.write("sysuse auto\ncd /tmp\n")
        temp_path = f.name
    
    try:
        # Note: lint doesn't actually require a running Stata session as it's static analysis,
        # but the tool call might expect one to be initialized or it's just cleaner to have it.
        await session_manager.start()
        
        res_json = await stata_inspect_data(action="lint", path=temp_path)
        result = json.loads(res_json)
        
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
        res_json = await stata_inspect_data(action="lint")
        result = json.loads(res_json)
        assert "error" in result
    finally:
        await session_manager.stop_all()
