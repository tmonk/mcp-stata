import os
import platform
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only integration test"),
    pytest.mark.requires_stata
]

from mcp_stata import discovery


@pytest.mark.integration
def test_windows_end_to_end(monkeypatch, tmp_path, client):
    # Prefer explicit STATA_PATH but fall back to autodiscovery so CI/users without env still run.
    stata_path = os.environ.get("STATA_PATH")
    if not stata_path:
        try:
            print("[win-e2e] attempting autodiscovery")
            stata_path, _edition = discovery.find_stata_path()
            print(f"[win-e2e] autodiscovered {stata_path}")
        except Exception as e:
            pytest.skip(f"Stata autodiscovery failed: {e}")

    if not os.path.exists(stata_path):
        pytest.skip("No valid Stata binary found via STATA_PATH or autodiscovery")

    # Ensure downstream logic uses the resolved binary
    monkeypatch.setenv("STATA_PATH", stata_path)
    monkeypatch.setenv("MCP_STATA_LOGLEVEL", "DEBUG")

    print("[win-e2e] run display")
    res = client.run_command_structured("display 2+2")
    assert res.success
    assert "4" in res.stdout

    s = client.run_command_structured("sysuse auto, clear")
    assert s.success
    data = client.get_data(count=3)
    assert len(data) == 3
    assert "price" in data[0]

    vars_struct = client.list_variables_structured()
    names = [v.name for v in vars_struct.variables]
    assert "price" in names
    assert "mpg" in names

    print("[win-e2e] regress price mpg")
    reg = client.run_command_structured("regress price mpg")
    assert reg.success
    assert "Number of obs" in reg.stdout

    g = client.run_command_structured('scatter price mpg, name(WinGraph, replace)')
    assert g.success
    graphs = client.list_graphs_structured()
    graph_names = [g.name for g in graphs.graphs]
    assert "WinGraph" in graph_names

    print("[win-e2e] export graph pdf")
    pdf_path = client.export_graph("WinGraph")
    assert Path(pdf_path).exists()

    png_path = tmp_path / "win_graph.png"
    if png_path.exists():
        png_path.unlink()
    print("[win-e2e] export graph png")
    exported = client.export_graph("WinGraph", filename=str(png_path), format="png")
    assert exported == str(png_path)
    assert png_path.exists()
    assert png_path.stat().st_size > 0

    print("[win-e2e] stored results")
    stored = client.get_stored_results()
    assert "r" in stored
    assert "e" in stored

    print("[win-e2e] codebook price")
    codebook = client.codebook("price", trace=True)
    if not codebook.success:
        assert codebook.error is not None

    print("[win-e2e] run do-file")
    do_path = tmp_path / "win_e2e.do"
    do_path.write_text('display "windows e2e ok"\n')
    do_resp = client.run_do_file(str(do_path))
    assert do_resp.success
    assert do_resp.log_path is not None
    assert Path(do_resp.log_path).exists()
    text = Path(do_resp.log_path).read_text(encoding="utf-8", errors="replace")
    assert "windows e2e ok" in text
    print("[win-e2e] completed")
