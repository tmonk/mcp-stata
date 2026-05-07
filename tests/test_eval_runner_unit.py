from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_toolkit_evals.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_toolkit_evals", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fixture_eval_scores_all_fixtures():
    mod = _load_module()
    report = mod.run_fixture_evals()
    assert report["passed"] >= 1
    assert report["failed"] == 0


def test_write_report_creates_json_file(tmp_path):
    mod = _load_module()
    original = mod.REPORTS
    mod.REPORTS = tmp_path
    try:
        path = mod.write_report({"fixture_eval": {"passed": 1, "failed": 0}})
    finally:
        mod.REPORTS = original
    assert path.exists()
    assert path.read_text().startswith("{")
