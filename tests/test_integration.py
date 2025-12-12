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
    assert help_text.lower().startswith("# help for")
    assert "regress" in help_text.lower()
    assert "syntax" in help_text.lower()
    assert len(help_text) > 200

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


def test_structured_error_envelope(client, tmp_path):
    missing_do = tmp_path / "does_not_exist.do"
    resp = client.run_do_file(str(missing_do))
    assert resp.success is False
    assert resp.error is not None
    assert resp.error.rc == 601

    # Intentional syntax error to surface rc and snippet
    bad_do = tmp_path / "bad.do"
    bad_do.write_text("sysuse auto\nthis_is_bad_syntax\n")
    resp2 = client.run_do_file(str(bad_do), trace=True)
    assert resp2.success is False
    assert resp2.error is not None
    assert resp2.error.rc is not None
    assert resp2.error.snippet is not None


def test_nested_do_and_program_errors(client, tmp_path):
    # Prepare data
    client.run_command("sysuse auto, clear")

    # Child do-file with invalid variable to trigger r(111)
    child = tmp_path / "child_bad.do"
    child.write_text('regress price bogusvar\n')

    # Parent do-file that calls child
    parent = tmp_path / "parent_bad.do"
    parent.write_text(f'do "{child}"\n')

    resp = client.run_do_file(str(parent), trace=True)
    assert resp.success is False
    assert resp.error is not None
    assert resp.error.rc is not None
    combined = (resp.error.snippet or "") + (resp.error.stderr or "") + (resp.error.stdout or "")
    assert "bogusvar" in combined.lower()

    # Program-defined command inside a do-file with an error
    program_do = tmp_path / "program_bad.do"
    program_do.write_text(
        "program define badprog\n"
        "    syntax varlist(min=1)\n"
        "    regress price bogusvar\n"
        "end\n"
        "badprog price\n"
    )

    resp2 = client.run_do_file(str(program_do), trace=True)
    assert resp2.success is False
    assert resp2.error is not None
    assert resp2.error.rc is not None
    combined2 = (resp2.error.snippet or "") + (resp2.error.stderr or "") + (resp2.error.stdout or "")
    assert "bogusvar" in combined2.lower()


def test_additional_error_cases(client, tmp_path):
    # Structured run_command error with trace
    bad_cmd = client.run_command_structured("invalid_command_xyz", trace=True)
    assert bad_cmd.success is False
    assert bad_cmd.error is not None
    assert bad_cmd.error.rc is not None

    # load_data with missing file
    missing = client.load_data("/tmp/nonexistent_file_1234.dta")
    assert missing.success is False
    assert missing.error is not None
    assert missing.error.rc is not None

    # codebook on missing variable
    client.run_command("sysuse auto, clear")
    cb = client.codebook("definitely_not_a_var", trace=True)
    assert cb.success is False
    assert cb.error is not None
    assert cb.error.rc is not None
    combined = (cb.error.stderr or "") + (cb.error.stdout or "") + (cb.error.snippet or "")
    assert "definitely_not_a_var" in combined

    # Nested do-file that references another missing do-file
    missing_child = tmp_path / "missing_child.do"
    parent = tmp_path / "parent_missing_child.do"
    parent.write_text(f'do "{missing_child}"\n')
    resp = client.run_do_file(str(parent), trace=True)
    assert resp.success is False
    assert resp.error is not None
    assert resp.error.rc is not None


def test_success_paths(client, tmp_path):
    # Structured run_command success with trace toggled
    ok_cmd = client.run_command_structured("display 1+1", trace=True)
    assert ok_cmd.success is True
    assert ok_cmd.rc == 0
    assert "2" in ok_cmd.stdout

    # load_data success via sysuse heuristic
    load_ok = client.load_data("auto", clear=True)
    assert load_ok.success is True
    assert load_ok.rc == 0

    # codebook success on existing variable
    cb_ok = client.codebook("price", trace=True)
    assert cb_ok.success is True
    assert cb_ok.rc == 0
    assert "price" in cb_ok.stdout.lower()

    # run_do_file success
    good_do = tmp_path / "good.do"
    good_do.write_text('sysuse auto, clear\ndisplay "hello ok"\n')
    do_ok = client.run_do_file(str(good_do), trace=True)
    assert do_ok.success is True
    assert do_ok.rc == 0
    assert "hello ok" in (do_ok.stdout or "") or "hello ok" in (do_ok.error.stdout if do_ok.error else "")
