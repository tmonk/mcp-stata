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

def _unwrap(result):
    return result.model_dump() if hasattr(result, "model_dump") else json.loads(result)

async def wait_for_task_result(task_id, timeout=10.0):
    return _unwrap(await stata_task_status(task_id, wait=True, timeout=timeout))

async def test_server_tools_consolidated(client):
    # Test stata_run (sync)
    res = _unwrap(await stata_run("display 5+5", strip_smcl=False))
    assert res["data"]["rc"] == 0
    assert "{com}. display 5+5" in res["data"]["stdout"]
    assert "{res}10" in res["data"]["stdout"]
    assert res.get("log", {}).get("path")
    log_text = Path(res["log"]["path"]).read_text(encoding="utf-8", errors="replace")
    assert "10" in log_text

    # Test stata_read_log (search)
    find_basic = _unwrap(stata_read_log(res["log"]["path"], query="10", max_matches=5))
    assert find_basic["data"]["matches"]
    assert any("10" in "\n".join(m["context"]) for m in find_basic["data"]["matches"])

    # Test stata_read_log (regex search)
    find_regex = _unwrap(stata_read_log(res["log"]["path"], query=r"\b10\b", regex=True, before=1, after=1))
    assert find_regex["data"]["matches"]
    assert all(len(m["context"]) >= 1 for m in find_regex["data"]["matches"])

    # Test stata_manage_graphs (list empty)
    empty_graphs = _unwrap(await stata_manage_graphs(action="list"))
    assert "graphs" in empty_graphs["data"]

    # Test stata_inspect_data (get)
    await stata_run("sysuse auto, clear")
    parsed_data = _unwrap(await stata_inspect_data(action="get", count=2))
    assert parsed_data["data"]["data"][0].get("price") is not None
    
    # Test stata_inspect_data (describe)
    desc = _unwrap(await stata_inspect_data(action="describe"))
    assert "Contains data" in desc["data"]["rendered"] or "obs:" in desc["data"]["rendered"]

    # Test stata_manage_graphs (list with graph)
    await stata_run("scatter price mpg, name(ServerGraph, replace)")
    g_list = _unwrap(await stata_manage_graphs(action="list"))
    names = [g["name"] for g in g_list["data"]["graphs"]]
    assert "ServerGraph" in names
    
    # Test stata_manage_graphs (export)
    pdf_export = _unwrap(await stata_manage_graphs(action="export", graph_name="ServerGraph", format="pdf"))
    pdf_path = pdf_export["data"]["graphs"][0]["file_path"]
    assert pdf_path.endswith(".pdf")
    assert Path(pdf_path).exists()
    
    # Test stata_get_help
    h = _unwrap(await stata_get_help("sysuse"))
    assert h["data"]["rendered"].lower().startswith("# help for")
    assert "sysuse" in h["data"]["rendered"].lower()
    
    # Test stata_get_results
    await stata_run("summarize price")
    results = _unwrap(await stata_get_results())
    assert "mean" in results["data"].get("r", {})

    # Test stata_load_data
    load_resp = _unwrap(await stata_load_data("auto"))
    assert load_resp["data"]["rc"] == 0

    # Test stata_inspect_data (codebook)
    cb_resp = _unwrap(await stata_inspect_data(action="codebook", query="price"))
    assert cb_resp["data"]["rc"] == 0

    # Test stata_manage_graphs (export_all)
    all_graphs = _unwrap(await stata_manage_graphs(action="export_all"))
    assert any(g["name"] == "ServerGraph" for g in all_graphs["data"].get("graphs", []))


async def test_server_run_do_file_consolidated(client, tmp_path):
    # Test stata_run with is_file=True
    tmp = tmp_path / "test.do"
    tmp.write_text('display "ok"\n')
    
    do_resp = _unwrap(await stata_run(str(tmp), is_file=True, strip_smcl=False))
    assert do_resp["data"]["rc"] == 0
    assert "{res}ok" in do_resp["data"]["stdout"]


async def test_server_background_consolidated(client):
    # Test stata_run with background=True
    # In tests without a real Context, background tasks might run synchronously
    cmd_resp = _unwrap(await stata_run("display 7", background=True))
    assert cmd_resp["data"]["task_id"]
    assert cmd_resp.get("log", {}).get("path")

    # Test stata_task_status
    status = _unwrap(await stata_task_status(cmd_resp["data"]["task_id"]))
    assert status["data"]["status"] in {"running", "done"}

    # Test wait in status
    cmd_result = await wait_for_task_result(cmd_resp["data"]["task_id"])
    assert cmd_result["data"]["status"] == "done"
    assert cmd_result["data"].get("result")


async def test_stata_control_consolidated(client):
    # Start a slow command
    # Note: without a real Context, this might run synchronously in the test
    cmd_resp = _unwrap(await stata_run("sleep 10", background=True))
    task_id = cmd_resp["data"]["task_id"]
    
    # Cancel it (it might already be done if it ran synchronously)
    cancel_resp = _unwrap(await stata_control(action="cancel", id=task_id))
    assert cancel_resp["data"]["status"] in {"cancelling", "done"}


async def test_stata_manage_session_consolidated(client):
    # Test list
    sessions = _unwrap(await stata_manage_session(action="list"))
    assert "sessions" in sessions["data"]
    
    # Test create
    create_resp = _unwrap(await stata_manage_session(action="create", session_id="test_new"))
    assert create_resp["data"]["status"] == "created"
    
    # Test stop
    stop_resp = _unwrap(await stata_manage_session(action="stop", session_id="test_new"))
    assert stop_resp["data"]["status"] == "stopped"

async def test_inspect_data_variants(client):
    await stata_run("sysuse auto, clear")
    
    # Search
    res = _unwrap(await stata_inspect_data(action="search", query="price"))
    assert any(v["name"] == "price" for v in res["data"]["variables"])
    
    # List
    res = _unwrap(await stata_inspect_data(action="list"))
    assert len(res["data"]["variables"]) > 10
    
    # Summary
    res = _unwrap(await stata_inspect_data(action="summary", variables=["price"]))
    assert "price" in res["data"]["summary"]


async def test_server_retains_complex_table_smcl_when_stripping_disabled(client):
    await stata_run("sysuse auto, clear")

    res = _unwrap(
        await stata_run(
            "tabstat price mpg weight length displacement gear_ratio, by(foreign) "
            "statistics(n mean sd min p25 p50 p75 max) columns(statistics)",
            strip_smcl=False,
        )
    )

    stdout = res["data"]["stdout"]

    assert res["data"]["rc"] == 0
    assert "{txt}" in stdout
    assert "{hline" in stdout
    assert "{ralign" in stdout or "{c |}" in stdout
    assert "Summary for variables:" in stdout
    assert "Group variable: foreign (Car origin)" in stdout
    assert "price" in stdout
    assert "mpg" in stdout
    assert "weight" in stdout
    assert "length" in stdout
    assert "displacement" in stdout
    assert "gear_ratio" in stdout
    assert "Turn circle" not in stdout  # sanity: only requested vars should appear
    assert "mean" in stdout.lower()
    assert "sd" in stdout.lower()
    assert "p50" in stdout.lower() or "median" in stdout.lower()
    assert "6072.423" in stdout or "6384.682" in stdout
    assert "2.806538" in stdout or "3.74" in stdout
