import os
import json
from pathlib import Path

import pytest

# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata


DO_FILE = Path("/Users/tom/Library/CloudStorage/Dropbox/projects/indirect_exp/code/4_figures/figure3_main_source_shaped_behavior.do")


@pytest.mark.integration
def test_external_figure3_do_file(client):
    if not DO_FILE.exists():
        pytest.skip("External figure3 do-file not present")

    prev_cwd = os.getcwd()
    os.chdir(DO_FILE.parent)
    try:
        resp = client.run_do_file(str(DO_FILE), trace=False)
        assert resp.success is True
        assert resp.rc == 0

        # Data inspection
        data = client.get_data(0, 2)
        assert isinstance(data, list)
        if data:
            assert isinstance(data[0], dict)

        # Variables
        vars_struct = client.list_variables_structured()
        assert len(vars_struct.variables) > 0

        # Graphs
        graphs = client.list_graphs_structured()
        assert len(graphs.graphs) >= 1

        # Test token-efficient file path export (default)
        exports = client.export_graphs_all()
        assert len(exports.graphs) >= 1
        assert exports.graphs[0].file_path

    finally:
        os.chdir(prev_cwd)

