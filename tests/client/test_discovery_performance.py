import os
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from mcp_stata.discovery import (
    verify_stata_install,
    find_working_stata_path,
    _DISCOVERY_CACHE_PATH
)

@pytest.fixture
def clean_cache():
    if _DISCOVERY_CACHE_PATH.exists():
        _DISCOVERY_CACHE_PATH.unlink()
    yield
    if _DISCOVERY_CACHE_PATH.exists():
        _DISCOVERY_CACHE_PATH.unlink()

@patch("subprocess.run")
@patch("os.stat")
@patch("os.listdir")
@patch("os.path.exists")
def test_verify_stata_install_cache_integration(mock_exists, mock_listdir, mock_stat, mock_run, clean_cache):
    # Setup mocks
    mock_exists.return_value = True
    mock_listdir.return_value = ["StataMP.app", "utilities", "stata.lic"]
    
    mock_stat_root = MagicMock()
    mock_stat_root.st_mtime = 1000.0
    mock_stat_root.st_size = 4096
    mock_stat.return_value = mock_stat_root
    
    mock_run.return_value = MagicMock(returncode=0, stdout="PREFLIGHT_OK", stderr="")
    
    root_path = "/path/to/stata"
    edition = "mp"
    
    # 1. First call: should run subprocess (Cold cache)
    assert verify_stata_install(root_path, edition) is True
    assert mock_run.call_count == 1
    
    # Verify cache file was created
    assert _DISCOVERY_CACHE_PATH.exists()
    
    # 2. Second call: should use cache (Warm cache)
    assert verify_stata_install(root_path, edition) is True
    assert mock_run.call_count == 1 # Still 1
    
    # 3. Call after mtime change: should re-verify
    mock_stat_root.st_mtime = 2000.0
    assert verify_stata_install(root_path, edition) is True
    assert mock_run.call_count == 2
    
    # 4. Call after some time for a broken install
    mock_run.return_value = MagicMock(returncode=1, stdout="FAIL", stderr="")
    mock_stat_root.st_mtime = 3000.0
    # First time it fails and caches as broken
    assert verify_stata_install(root_path, edition) is False
    assert mock_run.call_count == 3
    
    # Immediate second call uses cache (False)
    assert verify_stata_install(root_path, edition) is False
    assert mock_run.call_count == 3
    
    # Call after 25 hours (86400+ seconds) should re-verify
    with patch("time.time", return_value=time.time() + 90000):
        assert verify_stata_install(root_path, edition) is False
        assert mock_run.call_count == 4

@patch("mcp_stata.discovery.find_stata_candidates")
@patch("mcp_stata.discovery.verify_stata_install")
@patch("mcp_stata.discovery.get_stata_install_root")
def test_find_working_stata_path_parallel(mock_get_root, mock_verify, mock_find, clean_cache):
    # This tests the parallel execution logic in find_working_stata_path
    mock_find.return_value = [
        ("/stata/mp/stata-mp", "mp"),
        ("/stata/se/stata-se", "se")
    ]
    mock_get_root.side_effect = lambda x: os.path.dirname(x)
    
    # Make verification: MP fails, SE succeeds
    def verify_side_effect(path, edition, **kwargs):
        return "se" in path
    
    mock_verify.side_effect = verify_side_effect
    
    path, edition = find_working_stata_path()
    
    assert path == "/stata/se/stata-se"
    assert edition == "se"
    # Both should have been called (since MP was tried first and failed)
    assert mock_verify.call_count == 2
