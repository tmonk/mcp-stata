import json
import pytest
from mcp_stata.server import (
    mcp,
    run_command,
    get_data,
    describe,
    list_graphs,
    export_graph,
    export_graphs_all,
    get_help,
    get_stored_results,
    get_summary,
    get_metadata,
    get_graph_list,
    get_variable_list,
    get_stored_results_resource,
    load_data,
    codebook,
    run_do_file,
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
    res = json.loads(run_command("display 5+5"))
    assert res["rc"] == 0
    assert "10" in res["stdout"]
    res_struct = json.loads(run_command("display 2+3"))
    assert res_struct["rc"] == 0
    assert "5" in res_struct["stdout"]

    # Test get_data tool
    # Need data first
    run_command("sysuse auto, clear")
    data_str = get_data(count=2)
    parsed_data = json.loads(data_str)
    assert parsed_data["data"][0].get("price") is not None
    
    # Test describe tool
    desc = describe()
    assert "Contains data" in desc or "obs:" in desc

    # Test graphs tool
    run_command("scatter price mpg, name(ServerGraph, replace)")
    g_list = json.loads(list_graphs())
    names = [g["name"] for g in g_list["graphs"]]
    assert "ServerGraph" in names
    
    # Test export tool
    # Returns Image object
    img = export_graph("ServerGraph")
    print("\nDEBUG IMAGE ATTRS:", dir(img), img.__dict__)
    # For FastMCP Image, checking data presence is key
    assert len(img.data) > 0
    
    # Test help tool
    h = get_help("sysuse")
    assert h.lower().startswith("# help for")
    assert "sysuse" in h.lower()
    
    # Test stored results tool
    run_command("summarize price")
    res_json = get_stored_results()
    assert "mean" in res_json

    # Test load_data helper (heuristic sysuse)
    load_resp = json.loads(load_data("auto"))
    assert load_resp["rc"] == 0

    # Test codebook helper
    cb_resp = json.loads(codebook("price", as_json=True))
    assert cb_resp["rc"] == 0

    # Test export all graphs
    all_graphs = json.loads(export_graphs_all())
    assert any(g["name"] == "ServerGraph" for g in all_graphs.get("graphs", []))
    assert all_graphs["graphs"][0]["image_base64"]

    # Test run_do_file success
    from pathlib import Path
    tmp = Path("tmp_server_test.do")
    tmp.write_text('display "ok"\n')
    try:
        do_resp = json.loads(run_do_file(str(tmp), as_json=True))
        assert do_resp["rc"] == 0
    finally:
        if tmp.exists():
            tmp.unlink()
    
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
    v_list = json.loads(get_variable_list())
    names = [v["name"] for v in v_list["variables"]]
    assert "make" in names
    assert "price" in names

    # Test stored results resource
    run_command("summarize mpg")
    stored = get_stored_results_resource()
    assert "mean" in stored
