import os
import sys
from unittest.mock import MagicMock
import pytest

# Mock Stata dependencies ONLY if they're not already available
# This allows tests that need real Stata to use it, while providing mocks for unit tests
def _setup_stata_mocks_if_needed():
    """Set up mock Stata modules only if real ones are NOT available or if MOCK_STATA is set."""
    stata_base_available = False
    force_mock = os.environ.get("MCP_STATA_MOCK") == "1"
    
    try:
        # Check for stata_setup which is the entry point
        import stata_setup
        stata_base_available = True
    except (ImportError, ModuleNotFoundError):
        pass

    # Special check: If we are running in a worker, pystata might not be in path
    # but site-packages should be.
    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    
    # If Stata is available, prefer real Stata even if MCP_STATA_MOCK=1.
    if stata_base_available:
        if force_mock:
            print("[conftest] MCP_STATA_MOCK=1 ignored because Stata is available.")
            os.environ["MCP_STATA_MOCK"] = "0"
        force_mock = False

    # Only mock if stata_setup is missing or explicitly forced with no Stata available
    if not stata_base_available or force_mock:
        print(f"[conftest] {'Force mocking' if force_mock else 'Stata not found'}{f' (worker {worker_id})' if worker_id else ''}. Setting up protocol mocks.")
        
        # Setup sfi mock
        if 'sfi' not in sys.modules or force_mock:
            sfi = MagicMock()
            # Default Scalar.getValue to 0 (success)
            sfi.Scalar.getValue.return_value = 0
            # Default Macro.getGlobal to empty string or identifiable values
            sfi.Macro.getGlobal.return_value = ""
            sys.modules['sfi'] = sfi
            
        # Setup pystata mock
        if 'pystata' not in sys.modules or force_mock:
            pystata = MagicMock()
            
            def mock_run(code, echo=True, **kwargs):
                # If we're executing a command, append it to the mock log file
                mock_log = "/tmp/mock_session.smcl"
                try:
                    with open(mock_log, "a") as f:
                        if echo:
                            f.write(f"{{com}}. {code}\n")
                        # Use a recognizable marker for the mock output
                        f.write("{txt}Mock Stata output\n")
                except:
                    pass
                
                # Mock findfile behavior for get_help
                if "findfile" in code:
                    from sfi import Macro
                    if "regress" in code:
                        Macro.getGlobal.return_value = "/tmp/regress.sthlp"
                    else:
                        Macro.getGlobal.return_value = ""

                return "{txt}Mock Stata output"
            
            pystata.stata.run.side_effect = mock_run
            sys.modules['pystata'] = pystata
            
        # Setup stata_setup mock
        if 'stata_setup' not in sys.modules or force_mock:
            sys.modules['stata_setup'] = MagicMock()
    else:
        # If stata_setup is available, we should NOT mock sfi/pystata
        # However, we must ensure they can be imported eventually.
        # We'll just print a diagnostic.
        if worker_id:
            pass # Verbose logging here can slow down xdist startup
        else:
            print(f"[conftest] Stata installation detected. Mocks disabled.")

# In conftest.py
@pytest.fixture(scope="session")
def stata_client():
    """Single StataClient shared across all test files."""
    from mcp_stata.stata_client import StataClient
    from mcp_stata import discovery
    
    # Speed up tests by skipping the heavy subprocess pre-flight check in StataClient.init()
    os.environ["MCP_STATA_SKIP_PREFLIGHT"] = "1"
    
    force_mock = os.environ.get("MCP_STATA_MOCK") == "1"
    
    if not force_mock:
        stata_path = os.environ.get("STATA_PATH")
        if not stata_path or not os.path.exists(stata_path):
            try:
                stata_path, _ = discovery.find_stata_path()
                os.environ["STATA_PATH"] = stata_path
            except Exception:
                # If discovery fails and we're not forcing mock, 
                # we'll probably fail later, but let's let init() handle it
                pass
    
    c = StataClient()
    if force_mock:
        # Manually initialize enough for mock mode
        c.stata = sys.modules['pystata'].stata
        c._initialized = True
        c._persistent_log_path = "/tmp/mock_session.smcl"
        c._persistent_log_name = "_mcp_session"
        
        # Ensure the mock log file exists so logic that reads it doesn't crash
        with open(c._persistent_log_path, "w") as f:
            f.write("{txt}Mock Stata session started\n")

        # Create dummy help file for test_help
        import pathlib
        help_path = pathlib.Path("/tmp/regress.sthlp")
        help_path.write_text("{smcl}\n{marker help}{...}\n{title:Help for regress}\n\n{pstd}\nThis is a mock help file for testing.\n{pstd}\nSyntax:\nregress depvar [indepvars]\n" + ("Long text " * 50) + "\n")
            
        # Mock the list_graphs TTL cache & state
        import threading
        c._list_graphs_cache = None
        c._list_graphs_cache_time = 0
        c._list_graphs_cache_lock = threading.Lock()
        
        # Initialize graph aliasing structures
        c._graph_name_aliases = {}
        c._graph_name_reverse = {}
        
        # Manually set initialized
        c._initialized = True
    return c

# Call this immediately to ensure mocks are available if needed
_setup_stata_mocks_if_needed()


@pytest.fixture(scope="session", autouse=True)
def mock_stata_modules():
    """Session-scoped fixture to ensure Stata modules are mocked if needed."""
    _setup_stata_mocks_if_needed()
    yield
    # Note: We don't remove the mocks after tests because other tests might need them


def pytest_collection_modifyitems(config, items):
    """Skip Stata-required tests when running in forced mock mode."""
    force_mock = os.environ.get("MCP_STATA_MOCK") == "1"
    if force_mock:
        try:
            import stata_setup
            # If Stata is available, do not skip.
            return
        except (ImportError, ModuleNotFoundError):
            pass
        skip_marker = pytest.mark.skip(reason="Stata tests skipped in MCP_STATA_MOCK mode")
        for item in items:
            if "requires_stata" in item.keywords:
                item.add_marker(skip_marker)


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


@pytest.fixture
def client(stata_client):
    """
    Function-scoped alias to the shared Stata client.

    Tests that need additional isolation should clean state explicitly.
    """
    return stata_client


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
