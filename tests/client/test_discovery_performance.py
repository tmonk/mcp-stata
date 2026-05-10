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

def test_verify_stata_install_cache_integration(clean_cache):
    # Setup mocks for cache functions and subprocess
    with patch("mcp_stata.discovery._load_discovery_cache") as mock_load, \
         patch("mcp_stata.discovery._save_discovery_cache") as mock_save, \
         patch("mcp_stata.discovery._get_stata_fingerprint") as mock_fingerprint, \
         patch("subprocess.run") as mock_run:
         
        # Initial state: empty cache
        mock_load.return_value = {}
        mock_fingerprint.return_value = "fingerprint-1"
        mock_run.return_value = MagicMock(returncode=0, stdout="PREFLIGHT_OK", stderr="")
        
        root_path = "/path/to/stata"
        edition = "mp"
        
        # 1. First call: should run subprocess (Cold cache)
        assert verify_stata_install(root_path, edition) is True
        assert mock_run.call_count == 1
        assert mock_save.call_count == 1
        
        # 2. Second call: should use cache (Warm cache)
        # Update mock_load to return the saved state
        cache_key = f"{root_path}:{edition}"
        mock_load.return_value = {
            cache_key: {
                "working": True,
                "fingerprint": "fingerprint-1",
                "at": time.time()
            }
        }
        assert verify_stata_install(root_path, edition) is True
        assert mock_run.call_count == 1 # Still 1
        
        # 3. Call after fingerprint change: should re-verify
        mock_fingerprint.return_value = "fingerprint-2"
        assert verify_stata_install(root_path, edition) is True
        assert mock_run.call_count == 2
        
        # 4. Broken install behavior
        mock_run.return_value = MagicMock(returncode=1, stdout="FAIL", stderr="")
        mock_fingerprint.return_value = "fingerprint-3"
        # First time it fails
        assert verify_stata_install(root_path, edition) is False
        assert mock_run.call_count == 3
        
        # Immediate second call uses cache (False)
        mock_load.return_value[cache_key] = {
            "working": False,
            "fingerprint": "fingerprint-3",
            "at": time.time()
        }
        assert verify_stata_install(root_path, edition) is False
        assert mock_run.call_count == 3
        
        # Call after 25 hours should re-verify even if fingerprint matches
        mock_load.return_value[cache_key]["at"] = time.time() - 90000
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
