import json
import pytest
import anyio
from pathlib import Path
from mcp_stata.server import (
    mcp,
    stata_run,
    stata_read_log,
    stata_inspect_data,
    stata_manage_graphs,
    stata_get_help,
    stata_get_results,
    stata_load_data,
    stata_task_status,
    stata_control,
    stata_manage_session,
    session_manager,
)

# Mark all tests in this module as requiring Stata and being async
pytestmark = [pytest.mark.requires_stata, pytest.mark.asyncio, pytest.mark.xdist_group("stata_heavy")]

async def wait_for_task_result(task_id, timeout=10.0):
    res_str = await stata_task_status(task_id, wait=True, timeout=timeout)
    return json.loads(res_str)

async def test_server_tools_consolidated(client):
    # Test stata_run (sync)
    res = json.loads(await stata_run("display 5+5"))
    assert res["rc"] == 0
    assert "{com}. display 5+5" in res["stdout"]
    assert "{res}10" in res["stdout"]
    assert res.get("log_path")
    log_text = Path(res["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "10" in log_text

    # Test stata_read_log (search)
    find_basic = json.loads(stata_read_log(res["log_path"], query="10", max_matches=5))
    assert find_basic["matches"]
    assert any("10" in "\n".join(m["context"]) for m in find_basic["matches"])

    # Test stata_read_log (regex search)
    find_regex = json.loads(stata_read_log(res["log_path"], query=r"\b10\b", regex=True, before=1, after=1))
    assert find_regex["matches"]
    assert all(len(m["context"]) >= 1 for m in find_regex["matches"])

    # Test stata_manage_graphs (list empty)
    empty_graphs = json.loads(await stata_manage_graphs(action="list"))
    assert "graphs" in empty_graphs

    # Test stata_inspect_data (get)
    await stata_run("sysuse auto, clear")
    data_str = await stata_inspect_data(action="get", count=2)
    parsed_data = json.loads(data_str)
    assert parsed_data["data"][0].get("price") is not None
    
    # Test stata_inspect_data (describe)
    desc = await stata_inspect_data(action="describe")
    assert "Contains data" in desc or "obs:" in desc

    # Test stata_manage_graphs (list with graph)
    await stata_run("scatter price mpg, name(ServerGraph, replace)")
    g_list = json.loads(await stata_manage_graphs(action="list"))
    names = [g["name"] for g in g_list["graphs"]]
    assert "ServerGraph" in names
    
    # Test stata_manage_graphs (export)
    pdf_path = await stata_manage_graphs(action="export", graph_name="ServerGraph", format="pdf")
    assert isinstance(pdf_path, str)
    assert pdf_path.endswith(".pdf")
    assert Path(pdf_path).exists()
    
    # Test stata_get_help
    h = await stata_get_help("sysuse")
    assert h.lower().startswith("# help for")
    assert "sysuse" in h.lower()
    
    # Test stata_get_results
    await stata_run("summarize price")
    res_json = await stata_get_results()
    results = json.loads(res_json)
    assert "mean" in results.get("r", {})

    # Test stata_load_data
    load_resp = json.loads(await stata_load_data("auto"))
    assert load_resp["rc"] == 0

    # Test stata_inspect_data (codebook)
    cb_resp = json.loads(await stata_inspect_data(action="codebook", query="price"))
    assert cb_resp["rc"] == 0

    # Test stata_manage_graphs (export_all)
    all_graphs = json.loads(await stata_manage_graphs(action="export_all"))
    assert any(g["name"] == "ServerGraph" for g in all_graphs.get("graphs", []))


async def test_server_run_do_file_consolidated(client, tmp_path):
    # Test stata_run with is_file=True
    tmp = tmp_path / "test.do"
    tmp.write_text('display "ok"\n')
    
    do_resp = json.loads(await stata_run(str(tmp), is_file=True))
    assert do_resp["rc"] == 0
    assert "{res}ok" in do_resp["stdout"]


async def test_server_background_consolidated(client):
    # Test stata_run with background=True
    # In tests without a real Context, background tasks might run synchronously
    cmd_resp = json.loads(await stata_run("display 7", background=True))
    assert cmd_resp["task_id"]
    assert cmd_resp.get("log_path")

    # Test stata_task_status
    status = json.loads(await stata_task_status(cmd_resp["task_id"]))
    assert status["status"] in {"running", "done"}

    # Test wait in status
    cmd_result = await wait_for_task_result(cmd_resp["task_id"])
    assert cmd_result["status"] == "done"
    assert cmd_result.get("result")


async def test_stata_control_consolidated(client):
    # Start a slow command
    # Note: without a real Context, this might run synchronously in the test
    cmd_resp = json.loads(await stata_run("sleep 10", background=True))
    task_id = cmd_resp["task_id"]
    
    # Cancel it (it might already be done if it ran synchronously)
    cancel_resp = json.loads(await stata_control(action="cancel", id=task_id))
    assert cancel_resp["status"] in {"cancelling", "done"}


async def test_stata_manage_session_consolidated(client):
    # Test list
    sessions = json.loads(await stata_manage_session(action="list"))
    assert "sessions" in sessions
    
    # Test create
    create_resp = json.loads(await stata_manage_session(action="create", session_id="test_new"))
    assert create_resp["status"] == "created"
    
    # Test stop
    stop_resp = json.loads(await stata_manage_session(action="stop", session_id="test_new"))
    assert stop_resp["status"] == "stopped"

async def test_inspect_data_variants(client):
    await stata_run("sysuse auto, clear")
    
    # Search
    res = json.loads(await stata_inspect_data(action="search", query="price"))
    assert any(v["name"] == "price" for v in res["variables"])
    
    # List
    res = json.loads(await stata_inspect_data(action="list"))
    assert len(res["variables"]) > 10
    
    # Summary
    res = json.loads(await stata_inspect_data(action="summary", variables=["price"]))
    assert "price" in res
