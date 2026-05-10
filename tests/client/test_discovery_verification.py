import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from mcp_stata.discovery import (
    get_stata_install_root,
    verify_stata_install,
    find_working_stata_path,
    find_stata_path
)

def test_get_stata_install_root_mac_app():
    # macOS app bundle structure
    exec_path = "/Applications/Stata/StataMP.app/Contents/MacOS/stata-mp"
    # Mocking os.path.isdir to simulate 'utilities' folder presence
    with patch("os.path.isdir") as mock_isdir:
        def isdir_side_effect(path):
            return path == "/Applications/Stata/utilities"
        mock_isdir.side_effect = isdir_side_effect
        
        root = get_stata_install_root(exec_path)
        assert root == "/Applications/Stata"

def test_get_stata_install_root_standard():
    exec_path = "/usr/local/stata19/stata-se"
    with patch("os.path.isdir") as mock_isdir:
        mock_isdir.side_effect = lambda path: path == "/usr/local/stata19/utilities"
        
        root = get_stata_install_root(exec_path)
        assert root == "/usr/local/stata19"

def test_get_stata_install_root_fallback():
    # If no utilities found, return dirname
    exec_path = "/random/path/stata"
    with patch("os.path.isdir", return_value=False):
        root = get_stata_install_root(exec_path)
        assert root == "/random/path"

@patch("subprocess.run")
@patch("sys.executable", "/usr/bin/python3")
def test_verify_stata_install_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="PREFLIGHT_OK", stderr="")
    
    assert verify_stata_install("/path/to/stata", "mp") is True
    
    # Verify subprocess call
    args, kwargs = mock_run.call_args
    assert args[0][0] == "/usr/bin/python3"
    assert "[preflight] Calling stata_setup.config" in args[0][2]
    assert "stata_setup.config('/path/to/stata', 'mp')" in args[0][2]

@patch("subprocess.run")
def test_verify_stata_install_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="ERROR", stderr="License expired")
    
    assert verify_stata_install("/path/to/stata", "mp") is False

@patch("mcp_stata.discovery.find_stata_candidates")
@patch("mcp_stata.discovery.verify_stata_install")
@patch("mcp_stata.discovery.get_stata_install_root")
def test_find_working_stata_path_fallback(mock_get_root, mock_verify, mock_find):
    mock_find.return_value = [
        ("/stata/mp/stata-mp", "mp"),
        ("/stata/se/stata-se", "se")
    ]
    mock_get_root.side_effect = lambda x: os.path.dirname(x)
    
    # Mock verification: MP fails, SE succeeds
    def verify_side_effect(path, edition, **kwargs):
        return "se" in path
    
    mock_verify.side_effect = verify_side_effect
    
    path, edition = find_working_stata_path()
    
    assert path == "/stata/se/stata-se"
    assert edition == "se"
    assert mock_verify.call_count == 2

@patch("mcp_stata.discovery.find_stata_candidates")
@patch("mcp_stata.discovery.verify_stata_install")
def test_find_working_stata_path_all_fail(mock_verify, mock_find):
    mock_find.return_value = [
        ("/path/to/mp", "mp"),
        ("/path/to/se", "se")
    ]
    mock_verify.return_value = False
    
    # Should fall back to first candidate
    path, edition = find_working_stata_path()
    assert path == "/path/to/mp"
    assert edition == "mp"

def test_find_stata_path_empty_candidates():
    with patch("mcp_stata.discovery.find_stata_candidates", return_value=[]):
        with pytest.raises(FileNotFoundError, match="No Stata installations found"):
            find_stata_path()
