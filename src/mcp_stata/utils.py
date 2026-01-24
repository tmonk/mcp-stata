from __future__ import annotations
import os
import tempfile
import pathlib
import uuid
import logging
import threading
import shutil
import atexit
import signal
import sys
from typing import Optional, List

logger = logging.getLogger("mcp_stata")

_temp_dir_cache: Optional[str] = None
_temp_dir_lock = threading.Lock()
_files_to_cleanup: set[pathlib.Path] = set()
_dirs_to_cleanup: set[pathlib.Path] = set()

def register_temp_file(path: str | pathlib.Path) -> None:
    """
    Register a file to be deleted on process exit.
    Using this instead of NamedTemporaryFile(delete=True) because on Windows,
    delete=True prevents Stata from opening the file simultaneously.
    """
    with _temp_dir_lock:
        p = pathlib.Path(path).absolute()
        _files_to_cleanup.add(p)

def register_temp_dir(path: str | pathlib.Path) -> None:
    """Register a directory to be recursively deleted on process exit."""
    with _temp_dir_lock:
        p = pathlib.Path(path).absolute()
        _dirs_to_cleanup.add(p)

def is_windows() -> bool:
    """Returns True if the current operating system is Windows."""
    return os.name == "nt"

def _cleanup_temp_resources():
    """Cleanup registered temporary files and directories."""
    with _temp_dir_lock:
        # Sort and copy to avoid modification during iteration
        files = sorted(list(_files_to_cleanup), reverse=True)
        for p in files:
            try:
                # missing_ok=True is Python 3.8+
                p.unlink(missing_ok=True)
                _files_to_cleanup.discard(p)
            except Exception:
                pass
        
        dirs = sorted(list(_dirs_to_cleanup), reverse=True)
        for p in dirs:
            try:
                if p.exists() and p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                _dirs_to_cleanup.discard(p)
            except Exception:
                pass

atexit.register(_cleanup_temp_resources)

def _signal_handler(signum, frame):
    """Handle signals by cleaning up and exiting."""
    _cleanup_temp_resources()
    sys.exit(0)

# Register signal handlers for graceful cleanup on termination
try:
    # Avoid hijacking signals if we are running in a test environment or not in main thread
    is_pytest = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
    if threading.current_thread() is threading.main_thread() and not is_pytest:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
except (ValueError, RuntimeError):
    # Not in main thread or other signal handling restriction
    pass

def get_writable_temp_dir() -> str:
    """
    Finds a writable temporary directory by trying multiple fallback locations.
    Priority:
    1. MCP_STATA_TEMP environment variable
    2. System Temp (tempfile.gettempdir())
    3. User Home subdirectory (~/.mcp-stata/temp)
    4. Current Working Directory subdirectory (.tmp)
    
    Results are cached after the first successful identification.
    """
    global _temp_dir_cache
    
    with _temp_dir_lock:
        if _temp_dir_cache is not None:
            return _temp_dir_cache
        
        candidates = []
        
        # 1. Environment variable
        env_temp = os.getenv("MCP_STATA_TEMP")
        if env_temp:
            candidates.append((pathlib.Path(env_temp), "MCP_STATA_TEMP environment variable"))
            
        # 2. System Temp
        candidates.append((pathlib.Path(tempfile.gettempdir()), "System temp directory"))
        
        # 3. User Home
        try:
            home_temp = pathlib.Path.home() / ".mcp-stata" / "temp"
            candidates.append((home_temp, "User home directory"))
        except Exception:
            pass
            
        # 4. Current working directory subdirectory (.tmp)
        candidates.append((pathlib.Path.cwd() / ".tmp", "Working directory (.tmp)"))
        
        tested_paths = []
        for path, description in candidates:
            try:
                # Ensure directory exists
                path.mkdir(parents=True, exist_ok=True)
                
                # Test writability using standard tempfile logic
                try:
                    fd, temp_path = tempfile.mkstemp(
                        prefix=".mcp_write_test_", 
                        suffix=".tmp", 
                        dir=str(path)
                    )
                    os.close(fd)
                    os.unlink(temp_path)
                    
                    # Success
                    validated_path = str(path.absolute())
                    
                    # Log if we fell back from the first preferred (non-env) candidate
                    # (System temp is second, index 1 if env_temp is set, else index 0)
                    first_preferred_idx = 1 if env_temp else 0
                    if candidates.index((path, description)) > first_preferred_idx:
                        logger.warning(f"Falling back to temporary directory: {validated_path} ({description})")
                    else:
                        logger.debug(f"Using temporary directory: {validated_path} ({description})")
                        
                    _temp_dir_cache = validated_path
                    # Globally set tempfile.tempdir so other parts of the app and libraries
                    # use our validated writable path by default.
                    tempfile.tempdir = validated_path
                    return validated_path
                except (OSError, PermissionError) as e:
                    tested_paths.append(f"{path} ({description}): {e}")
                    continue
            except (OSError, PermissionError) as e:
                tested_paths.append(f"{path} ({description}): {e}")
                continue
                
        error_msg = "Failed to find any writable temporary directory. Errors:\n" + "\n".join(tested_paths)
        logger.error(error_msg)
        raise RuntimeError(error_msg)
