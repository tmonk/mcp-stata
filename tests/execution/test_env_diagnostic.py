import subprocess
import sys
import os
import pytest
import platform

def test_python_executable_health():
    """Verify that sys.executable can actually be run as a subprocess."""
    # This checks if shims are working or if they fail with 'realpath' errors
    res = subprocess.run([sys.executable, "--version"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "Python" in res.stdout or "Python" in res.stderr

def test_realpath_availability():
    """Check if 'realpath' command is available on the system."""
    if platform.system() == "Darwin" or platform.system() == "Linux":
        # We don't ASSERT it exists (since we want to support systems without it),
        # but we log its status for debugging.
        res = subprocess.run(["which", "realpath"], capture_output=True, text=True)
        if res.returncode != 0:
            print("\n[DIAGNOSTIC] 'realpath' command NOT found on this system.")
        else:
            print(f"\n[DIAGNOSTIC] 'realpath' found at: {res.stdout.strip()}")

def test_subprocess_with_env_path():
    """Verify subprocess runs with a standard PATH."""
    path = os.environ.get("PATH", "")
    print(f"\n[DIAGNOSTIC] Current PATH: {path}")
    assert len(path) > 0

def test_os_realpath_consistency():
    """Verify os.path.realpath doesn't crash and returns something sensible."""
    resolved = os.path.realpath(sys.executable)
    assert os.path.exists(resolved)
    print(f"\n[DIAGNOSTIC] sys.executable: {sys.executable}")
    print(f"[DIAGNOSTIC] os.path.realpath: {resolved}")
