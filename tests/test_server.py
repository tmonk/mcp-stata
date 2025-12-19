import json
import pytest
import anyio
from pathlib import Path
from mcp_stata.server import (
    mcp,
    run_command,
    get_data,
    describe,
    list_graphs,
    list_graphs_resource,
    export_graph,
    export_graphs_all,
    get_help,
    get_stored_results,
    get_summary,
    get_metadata,
    get_variable_list,
    get_stored_results_resource,
    load_data,
    codebook,
    run_do_file,
)

# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata

# We can test the tool functions directly since they are just Python functions decorated
# We assume the singleton client is initialized by the time we import server

def _run_command_sync(*args, **kwargs) -> str:
    async def _main() -> str:
        return await run_command(*args, **kwargs)

    return anyio.run(_main)


def _run_do_file_sync(*args, **kwargs) -> str:
    async def _main() -> str:
        return await run_do_file(*args, **kwargs)

    return anyio.run(_main)

@pytest.fixture(scope="session")
def init_server():
    # Ensure client init
    # The server module creates 'client = StataClient()' at module level
    # We just need to trigger one init
    _run_command_sync("display 1")

def test_server_tools(init_server):
    # Test run_command tool
    res = json.loads(_run_command_sync("display 5+5"))
    assert res["rc"] == 0
    assert res["stdout"] == ""
    assert res.get("log_path")
    log_text = Path(res["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "10" in log_text
    res_struct = json.loads(_run_command_sync("display 2+3"))
    assert res_struct["rc"] == 0
    assert res_struct["stdout"] == ""
    assert res_struct.get("log_path")
    log_text2 = Path(res_struct["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "5" in log_text2

    # list_graphs should work even before any graph exists / prior init
    empty_graphs = json.loads(list_graphs())
    assert "graphs" in empty_graphs

    # Test get_data tool
    # Need data first
    _run_command_sync("sysuse auto, clear")
    data_str = get_data(count=2)
    parsed_data = json.loads(data_str)
    assert parsed_data["data"][0].get("price") is not None
    
    # Test describe tool
    desc = describe()
    assert "Contains data" in desc or "obs:" in desc

    # Test graphs tool
    _run_command_sync("scatter price mpg, name(ServerGraph, replace)")
    g_list = json.loads(list_graphs())
    names = [g["name"] for g in g_list["graphs"]]
    assert "ServerGraph" in names
    
    # Test export tool (path return, default PDF)
    pdf_path = export_graph("ServerGraph")
    assert isinstance(pdf_path, str)
    assert pdf_path.endswith(".pdf")
    assert Path(pdf_path).exists()
    assert Path(pdf_path).stat().st_size > 0
    
    # Test export tool with PNG format
    png_path = export_graph("ServerGraph", format="png")
    assert isinstance(png_path, str)
    assert png_path.endswith(".png")
    assert Path(png_path).exists()
    assert Path(png_path).stat().st_size > 0
    
    # Test help tool
    h = get_help("sysuse")
    assert h.lower().startswith("# help for")
    assert "sysuse" in h.lower()
    
    # Test stored results tool
    _run_command_sync("summarize price")
    res_json = get_stored_results()
    assert "mean" in res_json

    # Test load_data helper (heuristic sysuse)
    load_resp = json.loads(load_data("auto"))
    assert load_resp["rc"] == 0

    # Test codebook helper
    cb_resp = json.loads(codebook("price", as_json=True))
    assert cb_resp["rc"] == 0

    # Test export all graphs (default: token-efficient file paths)
    all_graphs = json.loads(export_graphs_all())
    assert any(g["name"] == "ServerGraph" for g in all_graphs.get("graphs", []))
    assert all_graphs["graphs"][0]["file_path"]

    # Also test base64 export for backward compatibility
    all_graphs_b64 = json.loads(export_graphs_all(use_base64=True))
    assert all_graphs_b64["graphs"][0]["image_base64"]

    # Test run_do_file success
    tmp = Path("tmp_server_test.do")
    tmp.write_text('display "ok"\n')
    try:
        do_resp = json.loads(_run_do_file_sync(str(tmp), as_json=True))
        assert do_resp["rc"] == 0
        assert do_resp["stdout"] == ""
        assert do_resp.get("log_path")
        do_log_text = Path(do_resp["log_path"]).read_text(encoding="utf-8", errors="replace")
        assert "ok" in do_log_text
    finally:
        if tmp.exists():
            tmp.unlink()
    
def test_server_resources(init_server):
    # Load data for resources to have content
    _run_command_sync("sysuse auto, clear")

    # Test summary resource
    summary = get_summary()
    assert "Variable" in summary
    assert "Obs" in summary

    # Test metadata resource
    metadata = get_metadata()
    assert "Contains data" in metadata

    # Test graph list resource
    # Ensure a graph exists
    _run_command_sync("scatter price mpg, name(ResourceGraph, replace)")
    g_list = json.loads(list_graphs_resource())
    names = [g["name"] for g in g_list.get("graphs", [])]
    assert "ResourceGraph" in names

    # Test variable list resource
    v_list = json.loads(get_variable_list())
    names = [v["name"] for v in v_list["variables"]]
    assert "make" in names
    assert "price" in names

    # Test stored results resource
    _run_command_sync("summarize mpg")
    stored = get_stored_results_resource()
    assert "mean" in stored


def test_server_tools_with_cwd(tmp_path, init_server):
    project = tmp_path / "proj"
    project.mkdir()

    child = project / "child.do"
    child.write_text('display "child-ok"\n')
    parent = project / "parent.do"
    parent.write_text('do "child.do"\ndisplay "parent-ok"\n')

    # run_do_file should resolve relative path via cwd and also allow nested relative do
    do_resp = json.loads(_run_do_file_sync("parent.do", as_json=True, cwd=str(project)))
    assert do_resp["rc"] == 0
    assert do_resp["stdout"] == ""
    assert do_resp.get("log_path")
    text = Path(do_resp["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "child-ok" in text
    assert "parent-ok" in text

    # run_command should honor cwd as well
    cmd_resp = json.loads(_run_command_sync('do "child.do"', as_json=True, cwd=str(project)))
    assert cmd_resp["rc"] == 0
    assert cmd_resp["stdout"] == ""
    assert cmd_resp.get("log_path")
    text2 = Path(cmd_resp["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "child-ok" in text2
