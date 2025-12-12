import pytest
from stata_mcp.server import (
    mcp, run_command, get_data, describe, list_graphs, export_graph, get_help, get_stored_results,
    get_summary, get_metadata, get_graph_list, get_variable_list, get_stored_results_resource
)

# We can test the tool functions directly since they are just Python functions decorated
# We assume the singleton client is initialized by the time we import server

@pytest.fixture(scope="session")
def init_server():
    # Ensure client init
    # The server module creates 'client = StataClient()' at module level
    # We just need to trigger one init
    run_command("display 1")

def test_server_tools(init_server):
    # Test run_command tool
    res = run_command("display 5+5") 
    assert "10" in res

    # Test get_data tool
    # Need data first
    run_command("sysuse auto, clear")
    data_str = get_data(count=2)
    assert "price" in data_str
    
    # Test describe tool
    desc = describe()
    assert "Contains data" in desc or "obs:" in desc

    # Test graphs tool
    run_command("scatter price mpg, name(ServerGraph, replace)")
    g_list = list_graphs()
    assert "ServerGraph" in g_list
    
    # Test export tool
    # Returns Image object
    img = export_graph("ServerGraph")
    print("\nDEBUG IMAGE ATTRS:", dir(img), img.__dict__)
    # For FastMCP Image, checking data presence is key
    assert len(img.data) > 0
    
    # Test help tool
    h = get_help("sysuse")
    assert "smcl" in h or "sysuse" in h
    
    # Test stored results tool
    run_command("summarize price")
    res_json = get_stored_results()
    assert "mean" in res_json
    
def test_server_resources(init_server):
    # Load data for resources to have content
    run_command("sysuse auto, clear")

    # Test summary resource
    summary = get_summary()
    assert "Variable" in summary
    assert "Obs" in summary

    # Test metadata resource
    metadata = get_metadata()
    assert "Contains data" in metadata

    # Test graph list resource
    # Ensure a graph exists
    run_command("scatter price mpg, name(ResourceGraph, replace)")
    g_list = get_graph_list()
    assert "ResourceGraph" in g_list

    # Test variable list resource
    v_list = get_variable_list()
    assert "make" in v_list
    assert "price" in v_list

    # Test stored results resource
    run_command("summarize mpg")
    stored = get_stored_results_resource()
    assert "mean" in stored
