import os
import pytest
import json
from mcp_stata.stata_client import StataClient

pytestmark = pytest.mark.requires_stata

@pytest.fixture
def client():
    """StataClient fixture that ensures it's initialized."""
    c = StataClient()
    c.init()
    # Ensure a clean slate
    c.stata.run("clear all", echo=False)
    # Clear any leftover global macros or return results
    c.stata.run("capture _return drop _all", echo=False)
    return c

def test_rc_preservation_across_internal_calls(client):
    """Verify that internal calls (_exec_no_capture_silent) preserve the user's RC."""
    
    # 1. Set a user RC by running a command that fails
    # r(111) is variable not found
    client.stata.run("capture quietly summarize non_existent_variable", echo=False)
    
    # Verify we actually have a non-zero RC in Stata
    from sfi import Scalar
    initial_rc = int(float(Scalar.getValue("c(rc)") or 0))
    assert initial_rc == 111
    
    # 2. Run an internal command that SUCCEEDS
    # Internal commands use _exec_no_capture_silent
    internal_resp = client._exec_no_capture_silent("display 2+2", echo=False)
    assert internal_resp.success
    assert internal_resp.rc == 0
    
    # 3. Verify the user's RC is still 111
    final_rc = int(float(Scalar.getValue("c(rc)") or 0))
    assert final_rc == 111, f"Internal command corrupted user _rc. Expected 111, got {final_rc}"

def test_return_results_preservation(client):
    """Verify that internal calls preserve user r() results."""
    
    # 1. Set some r() results
    client.stata.run("sysuse auto, clear", echo=False)
    client.stata.run("summarize price", echo=False)
    
    # Get the real mean
    from sfi import Scalar
    results = client.get_stored_results()
    user_mean = results.get("r", {}).get("mean")
    assert user_mean is not None
    
    # 2. Run an internal command that would normally overwrite r()
    # graph dir sets r(list)
    client._exec_no_capture_silent("quietly graph dir, memory", echo=False)
    
    # 3. Verify user's r() results are preserved
    preserved_results = client.get_stored_results()
    assert preserved_results.get("r", {}).get("mean") == user_mean
    assert preserved_results.get("r", {}).get("N") == 74

def test_graph_identifier_stata19_compatibility(client):
    """Verify that graph names with spaces and special chars don't cause r(198)."""
    
    client.run_command_structured("sysuse auto, clear", echo=False)
    
    # Test names that previously caused issues
    problematic_names = [
        "My Graph",
        "Graph_1",
        "Graph.A",
        "Test 123"
    ]
    
    for name in problematic_names:
        # Create the graph via run_command_structured which handles aliases
        resp = client.run_command_structured(f"scatter price mpg, name(\"{name}\", replace)", echo=False)
        assert resp.success, f"Failed to create graph {name}: {resp.error}"
        
        # This calls graph display and graph export under the hood
        # Should not raise SystemError r(198)
        success = client.cache_graph_on_creation(name)
        assert success, f"Failed to cache graph with name: {name}"

def test_error_capture_priority(client):
    """Test that we correctly prioritize captured error codes over intermediate success."""
    
    # Clear state first
    client.stata.run("capture error 0", echo=False)

    # Run a command that definitely fails
    # Use _exec_with_capture which is the core of user command execution
    resp = client._exec_with_capture("noisily error 198", echo=True)
    
    assert resp.rc == 198
    
    # Now verify that an internal poll immediately after doesn't clobber it
    # We use _exec_no_capture_silent which has the isolation logic
    client._exec_no_capture_silent("display \"I am an internal poll\"", echo=False)
    
    # Check c(rc) again
    from sfi import Scalar
    current_rc = int(float(Scalar.getValue("c(rc)") or 0))
    assert current_rc == 198

def test_aliased_graph_names_isolation(client):
    """Verify that graph names rewritten to aliases are correctly handled by cache and isolation."""
    
    client.run_command_structured("sysuse auto, clear", echo=False)
    
    # user uses name("Price vs MPG")
    # client rewrites to Price_vs_MPG
    code = "scatter price mpg, name(\"Price vs MPG\", replace)"
    resp = client._exec_with_capture(code, echo=True)
    assert resp.success
    
    # Check if alias was created
    aliases = getattr(client, "_graph_name_aliases", {})
    assert "Price vs MPG" in aliases
    alias = aliases["Price vs MPG"]
    
    # Test caching the user-facing name (should resolve to alias internally)
    success = client.cache_graph_on_creation("Price vs MPG")
    assert success
    
    # Verify the file exists in preemptive cache
    with client._cache_lock:
        assert "Price vs MPG" in client._preemptive_cache
        path = client._preemptive_cache["Price vs MPG"]
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
