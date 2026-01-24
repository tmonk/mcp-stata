import json
import pytest
import anyio
from pathlib import Path
from mcp_stata.server import (
    mcp,
    run_command,
    run_command_background,
    read_log,
    find_in_log,
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
    run_do_file_background,
    get_task_status,
    get_task_result,
)

# Mark all tests in this module as requiring Stata and being async
pytestmark = [pytest.mark.requires_stata, pytest.mark.asyncio]

async def wait_for_task_result(task_id, timeout=5.0):
    with anyio.fail_after(timeout):
        while True:
            result = json.loads(get_task_result(task_id, allow_polling=True))
            if result.get("status") == "done":
                return result
            await anyio.sleep(0.05)

async def test_server_tools(client):
    # Test run_command tool
    res = json.loads(await run_command("display 5+5"))
    assert res["rc"] == 0
    assert "{com}. display 5+5" in res["stdout"]
    assert "{res}10" in res["stdout"]
    assert res.get("log_path")
    log_text = Path(res["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "10" in log_text

    # Test find_in_log tool (basic, case-insensitive)
    find_basic = json.loads(find_in_log(res["log_path"], "10", max_matches=5))
    assert find_basic["matches"]
    assert any("10" in "\n".join(m["context"]) for m in find_basic["matches"])

    # Test find_in_log tool with regex and context window
    find_regex = json.loads(find_in_log(res["log_path"], r"\b10\b", regex=True, before=1, after=1))
    assert find_regex["matches"]
    assert all(len(m["context"]) >= 1 for m in find_regex["matches"])

    # Test find_in_log tool with case sensitivity (expect no matches)
    find_case = json.loads(find_in_log(res["log_path"], "DISPLAY", case_sensitive=True))
    assert find_case["matches"] == []
    res_struct = json.loads(await run_command("display 2+3"))
    assert res_struct["rc"] == 0
    assert "{com}. display 2+3" in res_struct["stdout"]
    assert "{res}5" in res_struct["stdout"]
    assert res_struct.get("log_path")
    log_text2 = Path(res_struct["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "5" in log_text2

    # list_graphs should work even before any graph exists / prior init
    empty_graphs = json.loads(await list_graphs())
    assert "graphs" in empty_graphs

    # Test get_data tool
    # Need data first
    await run_command("sysuse auto, clear")
    data_str = await get_data(count=2)
    parsed_data = json.loads(data_str)
    assert parsed_data["data"][0].get("price") is not None
    
    # Test describe tool
    desc = await describe()
    assert "Contains data" in desc or "obs:" in desc

    # Test graphs tool
    await run_command("scatter price mpg, name(ServerGraph, replace)")
    g_list = json.loads(await list_graphs())
    names = [g["name"] for g in g_list["graphs"]]
    assert "ServerGraph" in names
    
    # Test export tool (path return, default PDF)
    pdf_path = await export_graph("ServerGraph")
    assert isinstance(pdf_path, str)
    assert pdf_path.endswith(".pdf")
    assert Path(pdf_path).exists()
    assert Path(pdf_path).stat().st_size > 0
    
    # Test export tool with PNG format
    png_path = await export_graph("ServerGraph", format="png")
    assert isinstance(png_path, str)
    assert png_path.endswith(".png")
    assert Path(png_path).exists()
    assert Path(png_path).stat().st_size > 0
    
    # Test help tool
    h = await get_help("sysuse")
    assert h.lower().startswith("# help for")
    assert "sysuse" in h.lower()
    
    # Test stored results tool
    await run_command("summarize price")
    res_json = await get_stored_results()
    assert "mean" in res_json

    # Test load_data helper (heuristic sysuse)
    load_resp = json.loads(await load_data("auto"))
    assert load_resp["rc"] == 0

    # Test codebook helper
    cb_resp = json.loads(await codebook("price", as_json=True))
    assert cb_resp["rc"] == 0

    # Test export all graphs (default: token-efficient file paths)
    all_graphs = json.loads(await export_graphs_all())
    assert any(g["name"] == "ServerGraph" for g in all_graphs.get("graphs", []))
    assert all_graphs["graphs"][0]["file_path"]

    # Test run_do_file success
    tmp = Path("tmp_server_test.do")
    tmp.write_text('display "ok"\n')
    try:
        do_resp = json.loads(await run_do_file(str(tmp), as_json=True))
        if do_resp["rc"] != 0:
            print(f"DEBUG: do_file failed. Response: {do_resp}")
            if "log_path" in do_resp and Path(do_resp["log_path"]).exists():
                print(f"DEBUG: Log content: {Path(do_resp['log_path']).read_text()}")
        assert do_resp["rc"] == 0
        assert "{com}. do" in do_resp["stdout"]
        assert "{res}ok" in do_resp["stdout"]
        assert do_resp.get("log_path")
        do_log_text = Path(do_resp["log_path"]).read_text(encoding="utf-8", errors="replace")
        assert "ok" in do_log_text
    finally:
        if tmp.exists():
            tmp.unlink()
    
async def test_server_resources(client):
    # Load data for resources to have content
    await run_command("sysuse auto, clear")

    # Test summary resource
    summary = await get_summary()
    assert "Variable" in summary
    assert "Obs" in summary

    # Test metadata resource
    metadata = await get_metadata()
    assert "Contains data" in metadata

    # Test graph list resource
    # Ensure a graph exists
    await run_command("scatter price mpg, name(ResourceGraph, replace)")
    g_list = json.loads(await list_graphs_resource())
    names = [g["name"] for g in g_list.get("graphs", [])]
    assert "ResourceGraph" in names

    # Test variable list resource
    v_list = json.loads(await get_variable_list())
    names = [v["name"] for v in v_list["variables"]]
    assert "make" in names
    assert "price" in names

    # Test stored results resource
    await run_command("summarize mpg")
    stored = await get_stored_results_resource()
    assert "mean" in stored


async def test_server_tools_with_cwd(tmp_path, client):
    project = tmp_path / "proj"
    project.mkdir()

    child = project / "child.do"
    child.write_text('display "child-ok"\n')
    parent = project / "parent.do"
    parent.write_text('do "child.do"\ndisplay "parent-ok"\n')

    # run_do_file should resolve relative path via cwd and also allow nested relative do
    do_resp = json.loads(await run_do_file("parent.do", as_json=True, cwd=str(project)))
    assert do_resp["rc"] == 0
    assert "{com}. do" in do_resp["stdout"]
    assert "{res}child-ok" in do_resp["stdout"]
    assert "{res}parent-ok" in do_resp["stdout"]
    assert do_resp.get("log_path")
    text = Path(do_resp["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "child-ok" in text
    assert "parent-ok" in text

    # run_command should honor cwd as well
    cmd_resp = json.loads(await run_command('do "child.do"', as_json=True, cwd=str(project)))
    assert cmd_resp["rc"] == 0
    assert "{com}. do" in cmd_resp["stdout"]
    assert "{res}child-ok" in cmd_resp["stdout"]
    assert cmd_resp.get("log_path")
    text2 = Path(cmd_resp["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "child-ok" in text2


async def test_server_background_tools(client, tmp_path):
    cmd_resp = json.loads(await run_command_background("display 7", as_json=True))
    assert cmd_resp["task_id"]
    assert cmd_resp.get("log_path")

    status = json.loads(get_task_status(cmd_resp["task_id"], allow_polling=True))
    assert status["status"] in {"running", "done"}
    assert status.get("log_path")

    cmd_result = await wait_for_task_result(cmd_resp["task_id"])
    assert cmd_result["status"] == "done"
    assert cmd_result.get("result")

    dofile = tmp_path / "mcp_background.do"
    dofile.write_text('display "bg-ok"\n')
    do_resp = json.loads(await run_do_file_background(str(dofile), as_json=True))
    assert do_resp["task_id"]
    assert do_resp.get("log_path")

    do_result = await wait_for_task_result(do_resp["task_id"])
    assert do_result["status"] == "done"
    assert do_result.get("result")


async def test_export_graphs_all_multiple(client):
    """Test that multiple produced graphs appear in export_graphs_all output."""
    # Clear any existing graphs first
    await run_command("clear all")
    await run_command("graph drop _all")
    
    # Load data and create multiple graphs
    await run_command("sysuse auto, clear")
    
    # Create graphs with names that can trigger edge cases:
    # - spaces/special characters
    # - cache filename collisions after sanitization (e.g., ":" vs "?")
    await run_command('scatter price mpg, name("Graph A", replace)')
    await run_command('histogram price, name("Graph:1", replace)')
    await run_command('graph box price, over(mpg) name("Graph?1", replace)')
    
    # Debug: check what graphs are available before export
    list_graphs_cmd = 'global mcp_graph_list ""'
    await run_command(list_graphs_cmd)
    await run_command("quietly graph dir, memory")
    await run_command("global mcp_graph_list `r(list)'")
    from sfi import Macro
    graph_list_str = Macro.getGlobal("mcp_graph_list")
    print(f"Graph list from memory: {graph_list_str}")
    
    # Export all graphs and verify all three are present
    all_graphs = json.loads(await export_graphs_all())
    
    # Debug: print available graphs
    graphs_result = await run_command("graph dir")
    print(f"Available graphs in Stata: {graphs_result}")
    print(f"Exported graphs: {[g['name'] for g in all_graphs['graphs']]}")
    
    # Should have exactly 3 graphs
    assert len(all_graphs["graphs"]) == 3
    
    # Check that all graph names are present
    graph_names = [g["name"] for g in all_graphs["graphs"]]
    assert "Graph A" in graph_names
    assert "Graph:1" in graph_names
    assert "Graph?1" in graph_names
    
    # Verify each graph has a valid file path
    paths = []
    for graph in all_graphs["graphs"]:
        assert graph["file_path"]
        # SVG files are now used (smaller, faster, vector format)
        assert graph["file_path"].endswith(".svg")
        assert Path(graph["file_path"]).exists()
        assert Path(graph["file_path"]).stat().st_size > 0
        paths.append(graph["file_path"])

    # Ensure we did not overwrite graphs due to cache filename collisions
    assert len(set(paths)) == 3

