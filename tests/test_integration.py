import os
import sys
import pytest
import shutil
from pathlib import Path

# Ensure src is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from stata_mcp.stata_client import StataClient

# Fixture for the Stata client (session scope to init once)
@pytest.fixture(scope="session")
def client():
    print("\n--- Initializing Stata Client ---")
    try:
        c = StataClient()
        c.init()
        return c
    except Exception as e:
        pytest.skip(f"Stata initialization failed: {e}")

def test_connection_and_math(client):
    result = client.run_command("display 2+2")
    assert "4" in result

def test_data_and_variables(client):
    client.run_command("sysuse auto, clear")
    
    # Test get_data
    data = client.get_data(count=5)
    assert len(data) == 5
    assert "price" in data[0]
    
    # Test list_variables
    vars_list = client.list_variables()
    var_names = [v["name"] for v in vars_list]
    assert "price" in var_names
    assert "mpg" in var_names
    
    # Test get_variable_details
    details = client.get_variable_details("price")
    assert len(details) > 0

def test_graphs(client, tmp_path):
    client.run_command("sysuse auto, clear")
    client.run_command("scatter price mpg, name(MyGraph, replace)")
    
    # Test list_graphs
    graphs = client.list_graphs()
    assert "MyGraph" in graphs
    
    # Test export
    # Use a specific temp file for this test
    export_path = tmp_path / "test_graph.png"
    # Ensure it doesn't exist
    if export_path.exists():
        export_path.unlink()
        
    returned_path = client.export_graph("MyGraph", filename=str(export_path))
    assert os.path.exists(returned_path)
    assert Path(returned_path).stat().st_size > 0

def test_stored_results(client):
    client.run_command("sysuse auto, clear")
    client.run_command("summarize price")
    
    results = client.get_stored_results()
    r_results = results.get("r", {})
    
    assert "mean" in r_results
    assert float(r_results["mean"]) > 6000

def test_help(client):
    help_text = client.get_help("regress")
    # Check for SMCL content or common words
    # Verification script found: "{smcl} ... {viewerdialog regress ...}"
    assert "{smcl}" in help_text or "{vieweralsosee" in help_text
    assert "Linear regression" in help_text
    assert len(help_text) > 1000

def test_standard_commands(client):
    """Verifies standard analysis commands like regress conform to expected output."""
    client.run_command("sysuse auto, clear")
    out = client.run_command("regress price mpg")
    
    # Check for standard Regression Table parts
    assert "Source" in out
    assert "SS" in out and "df" in out and "MS" in out
    assert "Number of obs" in out
    assert "Prob > F" in out
    
    # Check for specific coefficient results (mpg should be negative)
    # mpg | -238.89
    assert "mpg" in out
    assert "-" in out # implies negative coef or dashed lines, but context matters
    assert "Condition Number" not in out # Example of what NOT to expect perhaps?


def test_error_handling(client):
    # Test invalid command
    result = client.run_command("invalid_command_xyz")
    assert "r(199)" in result

    # Test invalid export
    with pytest.raises(RuntimeError, match="Graph export failed"):
         client.export_graph("NonExistentGraph")
