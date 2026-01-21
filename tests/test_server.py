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
    session_manager
)

# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata

async def _wait_for_task_result_async(task_id: str, timeout: float = 10.0) -> dict:
    with anyio.fail_after(timeout):
        while True:
            status_json = get_task_status(task_id, allow_polling=True)
            status = json.loads(status_json)
            if status.get("status") == "done":
                # Get final result
                result_json = get_task_result(task_id, allow_polling=True)
                return json.loads(result_json)
            await anyio.sleep(0.1)

@pytest.mark.asyncio
async def test_server_tools():
    # Ensure session manager started
    await session_manager.start()
    
    # Test run_command tool
    res_str = await run_command("display 5+5")
    res = json.loads(res_str)
    assert res["rc"] == 0
    assert res["stdout"] == ""
    assert res.get("log_path")
    log_text = Path(res["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "10" in log_text

    # Test find_in_log tool (basic, case-insensitive)
    find_basic = json.loads(find_in_log(res["log_path"], "10", max_matches=5))
    assert find_basic["matches"]
    assert any("10" in "\n".join(m["context"]) for m in find_basic["matches"])

    # Test get_data tool
    await run_command("sysuse auto, clear")
    data_str = await get_data(count=2)
    parsed_data = json.loads(data_str)
    assert parsed_data["data"][0].get("price") is not None
    
    # Test describe tool
    desc = await describe()
    assert "Contains data" in desc or "obs:" in desc

    # Test graphs tool
    await run_command("scatter price mpg, name(ServerGraph, replace)")
    g_list_str = await list_graphs()
    g_list = json.loads(g_list_str)
    names = [g["name"] for g in g_list["graphs"]]
    assert "ServerGraph" in names
    
    # Test export tool (path return, default PDF)
    pdf_path = await export_graph("ServerGraph")
    assert isinstance(pdf_path, str)
    assert pdf_path.endswith(".pdf")
    assert Path(pdf_path).exists()
    
    # Test help tool
    h = await get_help("sysuse")
    assert h.lower().startswith("# help for")
    assert "sysuse" in h.lower()
    
    # Test stored results tool
    await run_command("summarize price")
    res_json = await get_stored_results()
    assert "mean" in res_json

    # Test load_data helper
    load_resp = json.loads(await load_data("auto"))
    assert load_resp["rc"] == 0

    # Test codebook helper
    cb_resp = json.loads(await codebook("price", as_json=True))
    assert cb_resp["rc"] == 0

@pytest.mark.asyncio
async def test_server_resources():
    await session_manager.start()
    await run_command("sysuse auto, clear")

    # Test summary resource
    summary = await get_summary()
    assert "Variable" in summary

    # Test metadata resource
    metadata = await get_metadata()
    assert "Contains data" in metadata

    # Test graph list resource
    await run_command("scatter price mpg, name(ResourceGraph, replace)")
    g_list = json.loads(await list_graphs_resource())
    names = [g["name"] for g in g_list.get("graphs", [])]
    assert "ResourceGraph" in names

@pytest.mark.asyncio
async def test_server_tools_with_cwd(tmp_path):
    await session_manager.start()
    project = tmp_path / "proj"
    project.mkdir()

    child = project / "child.do"
    child.write_text('display "child-ok"\n')
    parent = project / "parent.do"
    parent.write_text('do "child.do"\ndisplay "parent-ok"\n')

    # run_do_file should resolve relative path via cwd
    do_resp = json.loads(await run_do_file("parent.do", as_json=True, cwd=str(project)))
    assert do_resp["rc"] == 0
    text = Path(do_resp["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "child-ok" in text
    assert "parent-ok" in text

@pytest.mark.asyncio
async def test_server_background_tools(tmp_path):
    await session_manager.start()
    cmd_resp = json.loads(await run_command_background("display 7", as_json=True))
    assert cmd_resp["task_id"]

    cmd_result = await _wait_for_task_result_async(cmd_resp["task_id"])
    assert cmd_result["status"] == "done"

    dofile = tmp_path / "mcp_background.do"
    dofile.write_text('display "bg-ok"\n')
    do_resp = json.loads(await run_do_file_background(str(dofile), as_json=True))
    assert do_resp["task_id"]

    do_result = await _wait_for_task_result_async(do_resp["task_id"])
    assert do_result["status"] == "done"

@pytest.mark.asyncio
async def test_export_graphs_all_multiple():
    await session_manager.start()
    await run_command("clear all")
    await run_command("graph drop _all")
    await run_command("sysuse auto, clear")
    
    await run_command('scatter price mpg, name("Graph A", replace)')
    await run_command('histogram price, name("Graph:1", replace)')
    
    all_graphs = json.loads(await export_graphs_all())
    assert len(all_graphs["graphs"]) >= 2
