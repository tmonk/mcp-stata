import os
import pytest
import time
from pathlib import Path
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
    # Reset some common settings to standard defaults for testing
    c.stata.run("set more off", echo=False)
    c.stata.run("set graphics on", echo=False)
    return c

def test_estimation_and_return_isolation(client):
    """Verify that e() and r() are both preserved across internal tool usage."""
    client.stata.run("sysuse auto, clear", echo=False)
    
    # 1. Run a regression to set e() results
    client.run_command_structured("regress price mpg weight")
    
    from sfi import Scalar
    # Get N from e(N)
    e_n_before = client.get_stored_results().get("e", {}).get("N")
    assert e_n_before == 74
    
    # 2. Run a summarize to set r() results
    client.run_command_structured("summarize mpg")
    r_mean_before = client.get_stored_results().get("r", {}).get("mean")
    assert r_mean_before is not None
    
    # 3. Trigger an internal operation that normally clobbers both
    # For example, list_graphs() internally runs 'graph dir, memory' which clears r()
    # and some internal checks might even clear e() if they ran models (unlikely but good to test).
    graphs = client.list_graphs()
    
    # 4. Use another internal tool - get_variable_details runs 'describe'
    details = client.get_variable_details("price")
    assert details is not None
    
    # 5. Verify e() and r() are STILL THERE
    final_results = client.get_stored_results()
    assert final_results.get("e", {}).get("N") == 74
    assert final_results.get("r", {}).get("mean") == r_mean_before

def test_global_macro_preservation(client):
    """Verify that user-defined global macros are not clobbered by MCP server."""
    # 1. Set a global macro
    client.stata.run("global mcp_test_macro \"User Value\"", echo=False)
    
    # 2. Run various MCP tools
    client.list_variables()
    client.list_graphs()
    client.run_command_structured("display \"some work\"", echo=False)
    
    # 3. Verify global still exists
    # We'll use get_stored_results if it captured macros (it currently captures r, e, and s)
    # Or just run a command to display it.
    resp = client.run_command_structured("display \"$mcp_test_macro\"", echo=False)
    assert "User Value" in resp.stdout

def test_settings_preservation_graphics_and_dp(client):
    """Verify that global settings like 'set dp' and 'set graphics' are preserved."""
    # 1. Set unusual settings (that are not forced to 'off' by PyStata)
    # set dp comma makes results like 2,5 instead of 2.5
    client.stata.run("set dp comma", echo=False)
    client.stata.run("set graphics off", echo=False)
    
    # 2. Run an MCP command that involves graphing (which usually turns graphics ON temporarily)
    client.run_command_structured("sysuse auto, clear", echo=False)
    client.run_command_structured("scatter price mpg, name(TestSettings, replace)", echo=False)
    
    # Internal caching of the graph
    client.cache_graph_on_creation("TestSettings")
    
    # 3. Verify settings are restored
    # We can check via c(dp) and c(graphics)
    resp = client.run_command_structured("display c(dp) \" \" c(graphics)", echo=False)
    assert "comma" in resp.stdout.lower()
    assert "off" in resp.stdout.lower()

    # Reset for next tests
    client.stata.run("set dp period", echo=False)
    client.stata.run("set graphics on", echo=False)

def test_s_results_preservation(client):
    """Verify that s-class results (like from 'label list') are preserved."""
    # 1. Create an s-class program to set s() results
    client.stata.run(
        "program define set_s, sclass\n"
        "    sreturn local test_s \"S-Value\"\n"
        "end", echo=False
    )
    client.stata.run("set_s", echo=False)
    
    # Check it worked
    res_before = client.get_stored_results()
    assert res_before.get("s", {}).get("test_s") == "S-Value"

    # 2. Run MCP internal
    client.list_variables()
    
    # 3. Verify s() results are STILL THERE
    results = client.get_stored_results()
    assert results.get("s", {}).get("test_s") == "S-Value"

def test_robust_aliasing_collision_handling(client):
    """Verify that multiple graphs with similar names don't collide when aliased."""
    client.run_command_structured("sysuse auto, clear", echo=False)
    
    # User names that might collide if aliased naively
    # "My Graph!" -> "My_Graph_"
    # "My Graph?" -> "My_Graph_"
    # Our aliasing needs to be deterministic but avoid collisions if possible, 
    # OR we need to ensure the alias doesn't stomp existing ones.
    
    name1 = "My Graph!"
    name2 = "My Graph?"
    
    client.run_command_structured(f"scatter price mpg, name(\"{name1}\", replace)")
    # Cache it
    client.cache_graph_on_creation(name1)
    
    client.run_command_structured(f"scatter weight mpg, name(\"{name2}\", replace)")
    # Cache it
    client.cache_graph_on_creation(name2)
    
    # List graphs - should see both original names
    graphs = client.list_graphs()
    assert name1 in graphs
    assert name2 in graphs
    
    # Export both - should get different images (different sizes/content)
    path1 = client.export_graph(name1, format="png")
    path2 = client.export_graph(name2, format="png")
    
    assert path1 != path2
    assert os.path.getsize(path1) > 0
    assert os.path.getsize(path2) > 0

def test_stale_rc_prevention_in_structured_run(client):
    """Verify that if a previous command failed, a subsequent successful structured command reports RC 0."""
    # 1. Fail a command
    client._exec_with_capture("noisily error 111", echo=False)
    
    # 2. Run a successful command
    resp = client.run_command_structured("display \"Success\"", echo=False)
    
    # 3. Verify RC is 0, not 111
    assert resp.success is True
    assert resp.rc == 0

def test_nested_hold_safety(client):
    """Verify that if the user already has a 'hold' name active, we don't clobber it."""
    # 1. User holds results with a specific name
    client.stata.run("sysuse auto, clear", echo=False)
    client.stata.run("summarize price", echo=False)
    client.stata.run("_return hold my_user_hold", echo=False)
    
    # 2. MCP runs a command (which uses its own uuid-based hold)
    client.list_variables()
    
    # 3. User restores their hold
    # If MCP clobbered the state or messed up the stack, this might fail or give wrong results
    client.stata.run("_return restore my_user_hold", echo=False)
    
    # Verify user results are back
    results = client.get_stored_results()
    assert results.get("r", {}).get("mean") is not None

def test_large_output_streaming_stability(client):
    """Verify that extremely large output doesn't crash the RC capture or state restoration."""
    # 1. Generate many lines of output
    # 1000 lines
    code = "forvalues i=1/1000 { \n display \"Line `i' of output\" \n }"
    resp = client.run_command_structured(code, echo=False)
    
    assert resp.success is True
    assert resp.rc == 0
    assert "Line 1000" in resp.stdout

@pytest.mark.asyncio
async def test_nested_do_file_streaming_robustness(client, tmp_path):
    """Verify that nested do-files don't lose RC or output context during streaming."""
    # 1. Create a deep nesting of do-files
    level3 = tmp_path / "level3.do"
    level3.write_text("display \"Level 3 start\"\nerror 459\ndisplay \"Level 3 end\"\n")
    
    level2 = tmp_path / "level2.do"
    level2.write_text(f"display \"Level 2 start\"\ndo \"{level3}\"\ndisplay \"Level 2 end\"\n")
    
    level1 = tmp_path / "level1.do"
    level1.write_text(f"display \"Level 1 start\"\ndo \"{level2}\"\ndisplay \"Level 1 end\"\n")
    
    # 2. Run via streaming
    chunks = []
    async def notify_log(text: str) -> None:
        chunks.append(text)
        
    resp = await client.run_do_file_streaming(str(level1), notify_log=notify_log)
    
    # 3. Verify
    assert resp.success is False
    assert resp.rc == 459
    
    full_output = "".join(chunks)
    assert "Level 3 start" in full_output
    assert "r(459)" in full_output
    assert "Level 3 end" not in full_output
    assert "Level 2 end" not in full_output
    assert "Level 1 end" not in full_output
    
    # 4. Verify user RC in Stata is preserved as 459
    from sfi import Scalar
    current_rc = int(float(Scalar.getValue("c(rc)") or 0))
    assert current_rc == 459

if __name__ == "__main__":
    pytest.main([__file__])
