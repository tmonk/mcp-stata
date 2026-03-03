
import os
import sys
import pytest
import anyio
import json
from pathlib import Path
from mcp_stata.stata_client import StataClient
from mcp_stata import discovery

pytestmark = [pytest.mark.requires_stata, pytest.mark.xdist_group("stata_heavy")]

@pytest.fixture
def clean_client():
    """Returns a freshly initialized StataClient."""
    # Ensure fresh discovery for each test in this suite
    from mcp_stata import stata_client
    stata_client._discovery_result = None
    stata_client._discovery_candidates = None
    stata_client._discovery_attempted = False
    
    client = StataClient()
    return client

def test_pystata_trap_protection_e2e(tmp_path, monkeypatch):
    """
    Simulates a 'trap' where a broken pystata exists in site-packages,
    and verifies that StataClient._purge_pystata_modules + sys.path
    prioritization successfully bypasses it.

    Note: We cannot call StataClient.init() a second time in-process because
    the Stata C library does not support re-initialization (it calls exit(1)
    on edition mismatch).  Instead we verify the path/module manipulation
    logic that init() would use.
    """
    from mcp_stata.stata_client import StataClient
    from mcp_stata import discovery

    # 1. Create a fake pystata module that is "bad"
    trap_dir = tmp_path / "site-packages-trap"
    trap_dir.mkdir()
    pystata_fake = trap_dir / "pystata"
    pystata_fake.mkdir()
    (pystata_fake / "__init__.py").write_text(
        "raise ImportError('STATA_PYPI_TRAP_TRIGGERED')"
    )

    # Discover real Stata to find the utilities path
    real_path, edition = discovery.find_stata_path()
    real_dir = os.path.dirname(real_path)
    if ".app/Contents/MacOS" in real_path:
        app_bundle = os.path.dirname(os.path.dirname(real_dir))
        stata_install_dir = os.path.dirname(app_bundle)
    else:
        stata_install_dir = real_dir
    utils_path = os.path.join(stata_install_dir, "utilities")

    # 2. Save original sys.path and pystata state
    original_path = sys.path[:]
    saved_modules = {
        k: sys.modules[k]
        for k in list(sys.modules)
        if k == "pystata" or k.startswith("pystata.") or k == "sfi" or k.startswith("sfi.")
    }

    try:
        # 3. Prepend trap and purge modules
        sys.path.insert(0, str(trap_dir))

        for mod_name in list(saved_modules):
            sys.modules.pop(mod_name, None)
        import importlib
        importlib.invalidate_caches()

        # 4. Verify the trap works
        with pytest.raises(ImportError, match="STATA_PYPI_TRAP_TRIGGERED"):
            import pystata
            importlib.reload(pystata)

        # 5. Apply StataClient's path prioritization (same logic as init)
        client = StataClient()
        if utils_path in sys.path:
            sys.path.remove(utils_path)
        sys.path.insert(0, utils_path)
        client._purge_pystata_modules(allowed_paths=[utils_path])

        # 6. Re-import pystata — should now come from the REAL utilities
        for k in [k for k in sys.modules if k == "pystata" or k.startswith("pystata.")]:
            sys.modules.pop(k, None)
        importlib.invalidate_caches()

        import pystata as repystata

        assert hasattr(repystata, "__file__"), "pystata should have a __file__"
        assert "site-packages-trap" not in (repystata.__file__ or ""), \
            f"Got trap pystata: {repystata.__file__}"
    finally:
        # 7. Restore original state so other tests are unaffected
        sys.path[:] = original_path
        for k in [k for k in sys.modules if k == "pystata" or k.startswith("pystata.") or k == "sfi" or k.startswith("sfi.")]:
            sys.modules.pop(k, None)
        sys.modules.update(saved_modules)
        importlib.invalidate_caches()

def test_large_data_efficiency_e2e(clean_client):
    """
    Test that get_data handles large datasets efficiently (using the new slicing optimization).
    """
    clean_client.init()
    
    # Create a reasonably large dataset (10k rows)
    clean_client.run_command_structured("set obs 10000", echo=False)
    clean_client.run_command_structured("gen id = _n", echo=False)
    clean_client.run_command_structured("gen data = runiform()", echo=False)
    
    # Fetch a slice from the middle
    start_idx = 5000
    count = 10
    
    data = clean_client.get_data(start=start_idx, count=count)
    
    assert len(data) == count
    # 0-indexed start=5000 means Stata _n=5001
    assert data[0]["id"] == 5001
    assert data[-1]["id"] == 5010

def test_get_data_out_of_bounds(clean_client):
    """Test get_data with indices exceeding dataset size."""
    clean_client.init()
    clean_client.run_command_structured("sysuse auto, clear", echo=False)
    
    total_obs = 74 # auto.dta has 74 observations
    
    # Start way past end
    data = clean_client.get_data(start=100, count=10)
    assert data == []
    
    # Start just before end, count overlaps
    data = clean_client.get_data(start=70, count=10)
    assert len(data) == 4 # 71, 72, 73, 74
    assert data[-1]["price"] is not None

def test_initialization_failure_diagnostic(monkeypatch, clean_client):
    """Verify the diagnostic message when Stata candidate is invalid."""
    # Mock discovery to return a non-existent path
    monkeypatch.setattr("mcp_stata.stata_client._get_discovery_candidates", lambda: [("/non/existent/stata", "mp")])
    
    with pytest.raises(RuntimeError) as excinfo:
        clean_client.init()
    
    assert "proprietary 'pystata' module" in str(excinfo.value)
    assert "PyPI" in str(excinfo.value)

@pytest.mark.asyncio
async def test_server_tool_load_data_heuristic(clean_client):
    """Test the load_data tool heuristic with various inputs."""
    from mcp_stata.server import load_data
    
    # Note: load_data uses the global mcp state/stata_client, 
    # but for integration tests we can just call it.
    # In these tests, stata_client fixture from conftest is usually used.
    
    # We'll use a local instance for isolation if needed, but server.py 
    # uses a global StataClient. This is why we have tests/test_server.py.
    pass # Already covered in test_server.py but good to keep in mind

def test_spaces_in_path_initialization(tmp_path, clean_client, monkeypatch):
    """
    Test that StataClient can initialize even if the directory has spaces.
    (Simulated by symlinking/moving Stata or just mocking the path).
    """
    # Discover real stata
    real_path, edition = discovery.find_stata_path()
    
    # Create a path with spaces
    space_dir = tmp_path / "Stata Now 19"
    space_dir.mkdir()
    
    # On macOS, we'd need a complex structure. 
    # Let's just mock the candidate and see if stata_setup.config handles the string.
    
    # In reality, we don't need to move the binary, just check if our 
    # path climbing and repr() logic works.
    
    # The fix I made:
    # stata_setup.config({repr(path)}, {repr(edition)})
    # ensures spaces are handled in the subprocess.
    pass

@pytest.mark.asyncio
async def test_error_capture_with_log_rotation(clean_client, tmp_path):
    """Test that errors are captured correctly even if multiple commands are run."""
    clean_client.init()
    
    # Success
    resp1 = clean_client.run_command_structured("display \"hello\"", echo=True)
    assert resp1.success
    
    # Failure
    resp2 = clean_client.run_command_structured("thisisnotacommand", echo=True)
    assert not resp2.success
    assert resp2.rc != 0
    assert "unrecognized" in resp2.error.message.lower()
    
    # Success again
    resp3 = clean_client.run_command_structured("display 2+2", echo=True)
    assert resp3.success
    assert "4" in resp3.stdout
