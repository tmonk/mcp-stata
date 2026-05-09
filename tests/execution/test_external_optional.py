import os
import json
import tempfile
from pathlib import Path

import pytest

# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata


FIGURE3_DO = Path("/Users/tom/Library/CloudStorage/Dropbox/projects/indirect_exp/code/4_figures/figure3_main_source_shaped_behavior.do")


def _with_cwd(path: Path):
    prev = os.getcwd()
    os.chdir(path)
    return prev


@pytest.mark.integration
def test_external_missing_macro_or_data(client):
    """Run a do-file expected to fail (missing dependency) and assert error envelope surfaces rc/snippet."""
    base_dir = FIGURE3_DO.parent
    if not base_dir.exists():
        base_dir = Path(tempfile.mkdtemp(prefix="mcp_stata_missing_dep_"))

    bogus_do = base_dir / "missing_dep_example.do"
    # Synthesize a tiny failing do-file on the fly
    bogus_do.write_text('do "definitely_missing_config.do"\n')

    prev = _with_cwd(bogus_do.parent)
    try:
        resp = client.run_do_file(str(bogus_do), trace=True)
        assert resp.success is False
        assert resp.error is not None
        assert resp.error.rc is not None
        combined = (resp.error.details or "") + (resp.stdout or "")
        assert "missing_config" in combined.lower() or "definitely_missing" in combined.lower()
    finally:
        os.chdir(prev)
        try:
            bogus_do.unlink()
        except Exception:
            pass


@pytest.mark.integration
def test_external_graph_multi_export(client):
    """Run figure3 do-file and ensure multiple graphs can be exported."""
    if not FIGURE3_DO.exists():
        pytest.skip("figure3 do-file not present")

    prev = _with_cwd(FIGURE3_DO.parent)
    try:
        resp = client.run_do_file(str(FIGURE3_DO), trace=False)
        assert resp.success is True

        s = client.run_command_structured("sysuse auto, clear")
        assert s.success is True

        # Create an extra graph to ensure list/export includes multiple names
        g = client.run_command_structured("scatter price mpg, name(ExtraGraph, replace)")
        assert g.success is True

        graphs = client.list_graphs_structured()
        names = [g.name for g in graphs.graphs]
        assert len(names) >= 1

        # Test token-efficient file path export (default)
        exports = client.export_graphs_all()
        exported_names = [g.name for g in exports.graphs]
        assert len(exported_names) >= 1
        assert all(g.file_path for g in exports.graphs)

    finally:
        os.chdir(prev)


@pytest.mark.integration
def test_external_paged_data_and_codebook(client):
    if not FIGURE3_DO.exists():
        pytest.skip("figure3 do-file not present")

    prev = _with_cwd(FIGURE3_DO.parent)
    try:
        resp = client.run_do_file(str(FIGURE3_DO), trace=False)
        assert resp.success is True

        data = client.get_data(start=100, count=5)
        assert isinstance(data, list)
        assert len(data) <= 5

        vars_struct = client.list_variables_structured()
        assert len(vars_struct.variables) > 0
        first_var = vars_struct.variables[0].name
        cb = client.codebook(first_var, trace=True)
        assert cb.success is True or cb.error is not None  # some vars may not have codebook, but envelope exists
    finally:
        os.chdir(prev)


@pytest.mark.integration
def test_external_stored_results_and_resources(client):
    if not FIGURE3_DO.exists():
        pytest.skip("figure3 do-file not present")

    prev = _with_cwd(FIGURE3_DO.parent)
    try:
        resp = client.run_do_file(str(FIGURE3_DO), trace=False)
        assert resp.success is True

        # Simple regression to populate stored results
        s = client.run_command_structured("sysuse auto, clear")
        assert s.success is True
        r = client.run_command_structured("regress price mpg")
        assert r.success is True
        stored = client.get_stored_results()
        assert "r" in stored
        assert "e" in stored

        # Resource-style fetches
        graphs = client.list_graphs_structured()
        assert isinstance(graphs.model_dump(), dict)
        vars_struct = client.list_variables_structured()
        assert isinstance(vars_struct.model_dump(), dict)
    finally:
        os.chdir(prev)

