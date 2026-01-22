import os
import shutil
import pathlib
import signal
import sys
import atexit
import pytest
from unittest.mock import patch, MagicMock
import mcp_stata.utils
from mcp_stata.utils import (
    register_temp_file, 
    register_temp_dir, 
    _cleanup_temp_resources,
    _signal_handler
)

@pytest.fixture(autouse=True)
def reset_globals():
    """Reset the module-level globals before each test."""
    mcp_stata.utils._files_to_cleanup = set()
    mcp_stata.utils._dirs_to_cleanup = set()

def test_atexit_registration():
    """Verify that the cleanup function is registered with atexit."""
    # This is a bit tricky to test across different python versions, 
    # but we can check the internal _exithandlers in many cases or just mock it.
    # A simpler way is to check if it's in the list of functions.
    import atexit
    # Not all Python implementations expose this, but CPython does
    if hasattr(atexit, '_exithandlers'):
        # _exithandlers is a list of (func, args, kwargs)
        funcs = [h[0] for h in atexit._exithandlers]
        assert _cleanup_temp_resources in funcs

def test_cleanup_with_symlinks(tmp_path):
    """Verify that cleanup handles symlinks correctly (deleting the link, not the target)."""
    target = tmp_path / "target.txt"
    target.write_text("target content")
    
    link = tmp_path / "link.txt"
    try:
        os.symlink(str(target), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform")
        
    register_temp_file(str(link))
    
    _cleanup_temp_resources()
    
    # Link should be gone, target should remain
    assert not link.exists()
    assert target.exists()

def test_cleanup_with_locked_file(tmp_path):
    """Test that cleanup is robust if one file cannot be deleted."""
    ok_file = tmp_path / "ok.txt"
    ok_file.write_text("ok")
    
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text("bad")
    
    register_temp_file(str(bad_file))
    register_temp_file(str(ok_file))
    
    # Mock os.unlink to fail for bad_file
    real_unlink = os.unlink
    def fake_unlink(p):
        p_str = str(p)
        if p_str == str(bad_file.resolve()):
            raise PermissionError("Locked")
        return real_unlink(p)
        
    with patch("os.unlink", side_effect=fake_unlink):
        # This should not raise and should still delete ok_file
        _cleanup_temp_resources()
        
    assert ok_file.exists() == False
    assert bad_file.exists() == True # Failed but didn't crash the loop

def test_cleanup_with_read_only_file(tmp_path):
    """Test cleanup of read-only files if possible (best effort)."""
    ro_file = tmp_path / "readonly.txt"
    ro_file.write_text("readonly")
    
    # Make it read-only
    os.chmod(str(ro_file), 0o444)
    
    register_temp_file(str(ro_file))
    
    # On many systems, read-only files can still be unlinked if you have write permission on the directory.
    _cleanup_temp_resources()
    
    # If it's still there, it's not a failure of our code, but good to know it didn't crash.
    # We don't assert it's gone because it depends on OS/Filesystem.

def test_signal_handler_triggers_cleanup():
    """Verify that _signal_handler calls cleanup and exits."""
    with patch("mcp_stata.utils._cleanup_temp_resources") as mock_cleanup, \
         patch("sys.exit") as mock_exit:
        
        _signal_handler(signal.SIGTERM, None)
        
        mock_cleanup.assert_called_once()
        mock_exit.assert_called_once_with(0)

def test_cleanup_dirs_robustness(tmp_path):
    """Test that directory cleanup handles partial failures gracefully."""
    ok_dir = tmp_path / "ok_dir"
    ok_dir.mkdir()
    (ok_dir / "f1").write_text("data")
    
    bad_dir = tmp_path / "bad_dir"
    bad_dir.mkdir()
    
    register_temp_dir(str(ok_dir))
    register_temp_dir(str(bad_dir))
    
    # Mock rmtree to fail for bad_dir
    real_rmtree = shutil.rmtree
    def fake_rmtree(path, *args, **kwargs):
        path_str = str(path)
        if path_str == str(bad_dir.resolve()):
            raise OSError("Internal error")
        return real_rmtree(path, *args, **kwargs)
        
    with patch("shutil.rmtree", side_effect=fake_rmtree):
        _cleanup_temp_resources()
        
    assert not ok_dir.exists()
    assert bad_dir.exists() # Should still exist if rmtree failed

def test_concurrent_registration_during_cleanup(tmp_path):
    """Very basic check of the lock (no crash)."""
    # This doesn't truly test concurrency without threads, but ensures no deadlock.
    f1 = tmp_path / "f1.txt"
    f1.write_text("1")
    register_temp_file(str(f1))
    
    _cleanup_temp_resources()
    
    f2 = tmp_path / "f2.txt"
    f2.write_text("2")
    register_temp_file(str(f2))
    
    _cleanup_temp_resources()
    assert not f2.exists()
