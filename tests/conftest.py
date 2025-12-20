import os
import sys
from unittest.mock import MagicMock
import pytest

# Mock Stata dependencies ONLY if they're not already available
# This allows tests that need real Stata to use it, while providing mocks for unit tests
def _setup_stata_mocks_if_needed():
    """Set up mock Stata modules only if real ones are not available."""
    # Try to import the real modules first
    stata_available = False
    try:
        import stata_setup
        stata_available = True
    except (ImportError, ModuleNotFoundError):
        pass

    # Only mock if Stata is not available
    if not stata_available:
        if 'sfi' not in sys.modules:
            sys.modules['sfi'] = MagicMock()
        if 'pystata' not in sys.modules:
            sys.modules['pystata'] = MagicMock()
        if 'stata_setup' not in sys.modules:
            sys.modules['stata_setup'] = MagicMock()

# Call this immediately to ensure mocks are available if needed
_setup_stata_mocks_if_needed()


@pytest.fixture(scope="session", autouse=True)
def mock_stata_modules():
    """Session-scoped fixture to ensure Stata modules are mocked if needed."""
    _setup_stata_mocks_if_needed()
    yield
    # Note: We don't remove the mocks after tests because other tests might need them


def configure_stata_for_tests():
    """
    Helper function to configure Stata for tests that need it.
    Returns (stata_dir, stata_flavor) for stata_setup.config().
    Raises exceptions if Stata is not found.
    """
    import stata_setup
    from mcp_stata.discovery import find_stata_path

    stata_exec_path, stata_flavor = find_stata_path()
    # stata_setup.config needs the directory, not the binary
    bin_dir = os.path.dirname(stata_exec_path)

    # For macOS .app bundles, use the parent directory of the .app
    if '.app/Contents/MacOS/' in stata_exec_path:
        # Go up from MacOS -> Contents -> .app -> parent directory
        app_bundle = os.path.dirname(os.path.dirname(bin_dir))
        stata_dir = os.path.dirname(app_bundle)
    else:
        stata_dir = bin_dir

    return stata_dir, stata_flavor


# Work around Windows PermissionError when pytest tries to unlink the
# pytest-current symlink during temp directory cleanup. Pytest's cleanup
# lives in _pytest.pathlib.cleanup_dead_symlinks; wrap it to ignore
# PermissionError so test runs don't warn/fail on exit.
if os.name == "nt":
    try:
        import _pytest.pathlib as _pl  # type: ignore
    except ImportError:
        _pl = None

    if _pl is not None:
        _orig_cleanup_dead_symlinks = getattr(_pl, "cleanup_dead_symlinks", None)

        def _cleanup_dead_symlinks_safe(root):
            if _orig_cleanup_dead_symlinks is None:
                return
            try:
                _orig_cleanup_dead_symlinks(root)
            except PermissionError:
                # Ignore symlink removal failures (e.g., antivirus or handle held)
                return

        _pl.cleanup_dead_symlinks = _cleanup_dead_symlinks_safe  # type: ignore
