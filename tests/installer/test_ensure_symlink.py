import pytest
import os
import shutil
import sys
import subprocess
import stat
from pathlib import Path
from unittest.mock import patch

# Add scripts/install to sys.path
repo_root = Path(__file__).resolve().parents[2]
sys.path.append(str(repo_root / "scripts" / "install"))

import setup_toolkit

@pytest.fixture
def temp_dir(tmp_path):
    yield tmp_path

def test_ensure_symlink_skips_real_directory(temp_dir):
    target = temp_dir / "target"
    target.mkdir()
    (target / "file.txt").write_text("hello")
    
    link = temp_dir / "link"
    link.mkdir()
    (link / "other.txt").write_text("old")
    
    # This should now SKIP replacing the directory 'link' to protect user data
    success = setup_toolkit._ensure_symlink(link, target)
    
    assert success is False
    assert link.exists()
    assert link.is_dir()
    assert not os.path.samefile(link, target)
    assert (link / "other.txt").exists()
    assert not (link / "file.txt").exists()

def test_ensure_symlink_skips_when_already_correct(temp_dir):
    target = temp_dir / "target"
    target.mkdir()
    
    link = temp_dir / "link"
    setup_toolkit._ensure_symlink(link, target)
    
    # Record the mtime or something to see if it was recreated
    original_stat = link.lstat()
    
    # Call again
    success = setup_toolkit._ensure_symlink(link, target)
    
    assert success is True
    # In some cases mtime might be the same, but let's check if it was unlinked
    # For a real test of "skipping", we could mock unlink/rmdir
    
    with patch("os.unlink") as mock_unlink, \
         patch("os.rmdir") as mock_rmdir, \
         patch("shutil.rmtree") as mock_rmtree:
        setup_toolkit._ensure_symlink(link, target)
        mock_unlink.assert_not_called()
        mock_rmdir.assert_not_called()
        mock_rmtree.assert_not_called()

def test_ensure_symlink_handles_broken_symlink(temp_dir):
    target = temp_dir / "target"
    target.mkdir()
    
    link = temp_dir / "link"
    # Create a broken symlink
    if sys.platform == "win32":
        # Create a broken junction using mklink /J
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(temp_dir / "non-existent")], capture_output=True, check=True)
    else:
        os.symlink(temp_dir / "non-existent", link)
        
    # Check if link exists (even if broken, lstat should work)
    try:
        link.lstat()
        exists_somehow = True
    except FileNotFoundError:
        exists_somehow = False
    assert exists_somehow
    
    success = setup_toolkit._ensure_symlink(link, target)
    assert success is True
    assert os.path.samefile(link, target)
