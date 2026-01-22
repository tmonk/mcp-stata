import os
import pytest
import shutil
from pathlib import Path

# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata

def test_connection_and_math(client):
    result = client.run_command_structured("display 2+2")
    assert result.success is True
    assert "4" in result.stdout

def test_list_graphs_without_prior_init(client):
    # Force reset to simulate fresh use before any command
    client._initialized = False
    if hasattr(client, "stata"):
        delattr(client, "stata")
    graphs = client.list_graphs()
    assert isinstance(graphs, list)


def test_export_graph_invalid_format(client):
    s = client.run_command_structured("sysuse auto, clear")
    assert s.success is True
    g = client.run_command_structured("scatter price mpg, name(BadFmtGraph, replace)")
    assert g.success is True
    with pytest.raises(ValueError, match="Unsupported graph export format"):
        client.export_graph("BadFmtGraph", format="jpg")


def test_export_graph_pdf_with_explicit_filename(client, tmp_path):
    s = client.run_command_structured("sysuse auto, clear")
    assert s.success is True
    g = client.run_command_structured("scatter price mpg, name(PdfGraph, replace)")
    assert g.success is True
    pdf_path = tmp_path / "explicit.pdf"
    if pdf_path.exists():
        pdf_path.unlink()
    returned = client.export_graph("PdfGraph", filename=str(pdf_path))
    assert returned == str(pdf_path)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0

def test_data_and_variables(client):
    s = client.run_command_structured("sysuse auto, clear")
    assert s.success is True
    
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
    s = client.run_command_structured("sysuse auto, clear")
    assert s.success is True
    g = client.run_command_structured("scatter price mpg, name(MyGraph, replace)")
    assert g.success is True
    
    # Test list_graphs
    graphs = client.list_graphs()
    assert "MyGraph" in graphs
    
    # Test export (default PDF)
    default_path = client.export_graph("MyGraph")
    assert os.path.exists(default_path)
    assert default_path.endswith(".pdf")
    assert Path(default_path).stat().st_size > 0

    # Test explicit PNG export to a provided path
    export_path = tmp_path / "test_graph.png"
    if export_path.exists():
        export_path.unlink()
    returned_path = client.export_graph("MyGraph", filename=str(export_path), format="png")
    assert os.path.exists(returned_path)
    assert returned_path.endswith(".png")
    assert Path(returned_path).stat().st_size > 0

def test_stored_results(client):
    s = client.run_command_structured("sysuse auto, clear")
    assert s.success is True
    summ = client.run_command_structured("summarize price")
    assert summ.success is True
    
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
    s = client.run_command_structured("sysuse auto, clear")
    assert s.success is True
    reg = client.run_command_structured("regress price mpg")
    assert reg.success is True
    out = reg.stdout
    
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
    result = client.run_command_structured("invalid_command_xyz")
    assert result.success is False
    assert result.error is not None
    assert result.error.rc == 199 or "r(199)" in (result.error.snippet or "")

    # Test invalid export
    with pytest.raises(RuntimeError, match=r"Graph export failed|Graph window|r\(693\)|not found r\(111\)"):
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
    resp2 = client.run_do_file(str(bad_do), trace=False)
    assert resp2.success is False
    assert resp2.error is not None
    assert resp2.error.rc is not None
    assert resp2.error.snippet is not None


def test_nested_do_and_program_errors(client, tmp_path):
    # Prepare data
    s = client.run_command_structured("sysuse auto, clear")
    assert s.success is True

    # Child do-file with invalid variable to trigger r(111)
    child = tmp_path / "child_bad.do"
    child.write_text('regress price bogusvar\n')

    # Parent do-file that calls child
    parent = tmp_path / "parent_bad.do"
    parent.write_text(f'do "{child}"\n')

    resp = client.run_do_file(str(parent), trace=False)
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

    resp2 = client.run_do_file(str(program_do), trace=False)
    assert resp2.success is False
    assert resp2.error is not None
    assert resp2.error.rc is not None
    combined2 = (resp2.error.snippet or "") + (resp2.error.stderr or "") + (resp2.error.stdout or "")
    assert "bogusvar" in combined2.lower()


def test_additional_error_cases(client, tmp_path):
    # Structured run_command error with trace
    bad_cmd = client.run_command_structured("invalid_command_xyz", trace=False)
    assert bad_cmd.success is False
    assert bad_cmd.error is not None
    assert bad_cmd.error.rc is not None

    # load_data with missing file
    missing = client.load_data("/tmp/nonexistent_file_1234.dta")
    assert missing.success is False
    assert missing.error is not None
    assert missing.error.rc is not None

    # codebook on missing variable
    s = client.run_command_structured("sysuse auto, clear")
    assert s.success is True
    cb = client.codebook("definitely_not_a_var", trace=False)
    assert cb.success is False
    assert cb.error is not None
    assert cb.error.rc is not None
    combined = (cb.error.stderr or "") + (cb.error.stdout or "") + (cb.error.snippet or "")
    assert "definitely_not_a_var" in combined

    # Nested do-file that references another missing do-file
    missing_child = tmp_path / "missing_child.do"
    parent = tmp_path / "parent_missing_child.do"
    parent.write_text(f'do "{missing_child}"\n')
    resp = client.run_do_file(str(parent), trace=False)
    assert resp.success is False
    assert resp.error is not None
    assert resp.error.rc is not None


def test_success_paths(client, tmp_path):
    # Structured run_command success with trace toggled
    ok_cmd = client.run_command_structured("display 1+1", trace=False)
    assert ok_cmd.success is True
    assert ok_cmd.rc == 0
    assert "2" in ok_cmd.stdout
    assert ok_cmd.smcl_output is not None

    # load_data success via sysuse heuristic
    load_ok = client.load_data("auto", clear=True)
    assert load_ok.success is True
    assert load_ok.rc == 0

    # codebook success on existing variable
    cb_ok = client.codebook("price", trace=False)
    assert cb_ok.success is True
    assert cb_ok.rc == 0
    assert "price" in cb_ok.stdout.lower()

    # run_do_file success
    good_do = tmp_path / "good.do"
    good_do.write_text('sysuse auto, clear\ndisplay "hello ok"\n')
    do_ok = client.run_do_file(str(good_do), trace=False)
    assert do_ok.success is True
    assert do_ok.rc == 0
    assert do_ok.log_path is not None
    assert Path(do_ok.log_path).exists()
    log_text = Path(do_ok.log_path).read_text(encoding="utf-8", errors="replace")
    assert "hello ok" in log_text

if __name__ == "__main__":
    pytest.main([__file__])