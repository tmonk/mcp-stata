import os
import pathlib
import tempfile
import uuid
import shutil
import pytest
from unittest.mock import patch, MagicMock
from mcp_stata.utils import (
    get_writable_temp_dir, 
    register_temp_file, 
    register_temp_dir, 
    _cleanup_temp_resources,
    _temp_dir_cache,
    _files_to_cleanup,
    _dirs_to_cleanup
)
import mcp_stata.utils

@pytest.fixture(autouse=True)
def reset_globals():
    """Reset the module-level globals before each test."""
    mcp_stata.utils._temp_dir_cache = None
    mcp_stata.utils._files_to_cleanup = set()
    mcp_stata.utils._dirs_to_cleanup = set()
    # Clear environment variable if set
    os.environ.pop("MCP_STATA_TEMP", None)

def test_get_writable_temp_dir_env_var(tmp_path):
    """Test that MCP_STATA_TEMP takes priority."""
    custom_dir = tmp_path / "custom_temp"
    custom_dir.mkdir()
    
    with patch.dict(os.environ, {"MCP_STATA_TEMP": str(custom_dir)}):
        path = get_writable_temp_dir()
        assert path == str(custom_dir.resolve())
        assert os.path.exists(path)

def test_get_writable_temp_dir_system_fallback(tmp_path):
    """Test fallback to system temp when env var is not set."""
    # Ensure env var is not set
    if "MCP_STATA_TEMP" in os.environ:
        del os.environ["MCP_STATA_TEMP"]
        
    path = get_writable_temp_dir()
    # Resolve both to handle macOS /private/var symlink
    assert pathlib.Path(path).resolve() == pathlib.Path(tempfile.gettempdir()).resolve()

def test_get_writable_temp_dir_unwritable_system_fallback(tmp_path):
    """Test fallback when system temp is unwritable."""
    # Mock system temp to be unwritable
    unwritable_dir = tmp_path / "unwritable"
    unwritable_dir.mkdir()
    
    # We want mkstemp to fail only for the unwritable_dir
    real_mkstemp = tempfile.mkstemp
    
    def side_effect(prefix=None, suffix=None, dir=None, text=False):
        if dir and str(pathlib.Path(dir).resolve()).startswith(str(unwritable_dir.resolve())):
            raise PermissionError("Denied")
        return real_mkstemp(prefix=prefix, suffix=suffix, dir=dir, text=text)

    with patch("tempfile.gettempdir", return_value=str(unwritable_dir)):
        with patch("tempfile.mkstemp", side_effect=side_effect):
            # It should skip system temp and eventually try home or cwd .tmp
            path = get_writable_temp_dir()
            # Since we allowed real_mkstemp for others, it should eventually succeed
            assert path != str(unwritable_dir.resolve())
            assert ".tmp" in path or ".mcp-stata" in path or tempfile.gettempdir() in path

def test_get_writable_temp_dir_cwd_fallback(tmp_path):
    """Test fallback to CWD .tmp when others fail."""
    # Create fake home and sys dirs in tmp_path
    sys_temp = tmp_path / "sys_temp"
    home_temp = tmp_path / "home_temp"
    cwd_temp = tmp_path / "cwd_temp"
    
    # We'll use absolute paths
    sys_temp_str = str(sys_temp.resolve())
    home_temp_str = str(home_temp.resolve())
    
    # Mock home to return our home_temp_str
    with patch("tempfile.gettempdir", return_value=sys_temp_str), \
         patch("pathlib.Path.home", return_value=pathlib.Path(home_temp_str)), \
         patch("pathlib.Path.cwd", return_value=cwd_temp):
        
        # We want sys and home to fail during write
        real_mkstemp = tempfile.mkstemp
        def side_effect(prefix=None, suffix=None, dir=None, text=False):
            p = str(pathlib.Path(dir).resolve()) if dir else ""
            if p.startswith(sys_temp_str) or p.startswith(home_temp_str):
                raise PermissionError("Fail")
            return real_mkstemp(prefix=prefix, suffix=suffix, dir=dir, text=text)
            
        with patch("tempfile.mkstemp", side_effect=side_effect):
            path = get_writable_temp_dir()
            # It should have fallen back to cwd_temp / ".tmp"
            assert path == str((cwd_temp / ".tmp").resolve())
            assert os.path.exists(path)

def test_resource_registration():
    """Test registration of files and directories."""
    # Using a path that doesn't trigger symlink resolution issues in the test itself
    # although absolute() is what we are testing now.
    file_path = "/tmp/test.file"
    dir_path = "/tmp/test.dir"
    
    register_temp_file(file_path)
    register_temp_dir(dir_path)
    
    # Paths are stored as absolute paths in registration
    assert pathlib.Path(file_path).absolute() in mcp_stata.utils._files_to_cleanup
    assert pathlib.Path(dir_path).absolute() in mcp_stata.utils._dirs_to_cleanup

def test_cleanup_resources(tmp_path):
    """Test that _cleanup_temp_resources actually deletes files and dirs."""
    test_file = tmp_path / "cleanup.txt"
    test_file.write_text("data")
    
    test_dir = tmp_path / "cleanup_dir"
    test_dir.mkdir()
    (test_dir / "inner.txt").write_text("inner")
    
    register_temp_file(str(test_file))
    register_temp_dir(str(test_dir))
    
    _cleanup_temp_resources()
    
    assert not test_file.exists()
    assert not test_dir.exists()

def test_cleanup_resources_graceful_missing(tmp_path):
    """Test that cleanup doesn't crash if files are already gone."""
    missing_file = str(tmp_path / "missing.txt")
    register_temp_file(missing_file)
    
    # Should not raise exception
    _cleanup_temp_resources()
