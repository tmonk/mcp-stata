import json
import os

import pytest

from benchmark.compare import diff_versions, main as compare_main
from benchmark.results import RunRecord, load_results, save_result


def test_save_result_jsonl_append_and_no_overwrite(tmp_path, sample_run_records):
    results_dir = tmp_path / "results"
    r = sample_run_records[0]

    p1 = save_result(r, results_dir=str(results_dir))
    assert os.path.exists(p1)

    with open(p1, "r", encoding="utf-8") as f:
        lines1 = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines1) == 1
    json.loads(lines1[0])  # valid json

    # Re-run save_result with same record: should append, not overwrite/truncate.
    p2 = save_result(r, results_dir=str(results_dir))
    assert p2 == p1
    with open(p1, "r", encoding="utf-8") as f:
        lines2 = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines2) == 2


def test_load_results_round_trip(tmp_path, sample_run_records):
    results_dir = tmp_path / "results"
    for r in sample_run_records:
        save_result(r, results_dir=str(results_dir))

    loaded = load_results(results_dir=str(results_dir))
    assert len(loaded) == len(sample_run_records)
    assert [r.run_id for r in loaded] == [r.run_id for r in sorted(sample_run_records, key=lambda x: x.timestamp)]

    # Compare dict representation so we cover all fields.
    by_id = {r.run_id: r for r in loaded}
    for r in sample_run_records:
        assert by_id[r.run_id].to_dict() == r.to_dict()


def test_total_tokens_validation_raises(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    path = results_dir / "2026-05-11_deadbeef.jsonl"
    bad = {
        "run_id": "deadbeef-dead-4ead-8ead-deadbeefdead",
        "timestamp": "2026-05-11T10:00:00Z",
        "mcp_stata_version": "0.1.0",
        "gemini_model": "gemini-3-flash-preview",
        "git_commit": "untracked",
        "approach": "mcp",
        "task_id": "T1.1",
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 999,  # wrong
        "turns": 1,
        "cost_usd": 0.0,
        "resolution_correct": True,
        # unknown field should be ignored, but validation should still fail
        "new_future_field": "ok",
    }
    path.write_text(json.dumps(bad) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"run_id=deadbeef-dead-4ead-8ead-deadbeefdead"):
        load_results(results_dir=str(results_dir))


def test_diff_detects_planted_regression(sample_run_records):
    rows = diff_versions(sample_run_records, version_a="0.1.0", version_b="0.2.0")
    # We planted mcp T1.1 to be +20% tokens (1200 vs 1000), should be flagged regression.
    target = [r for r in rows if r["approach"] == "mcp" and r["task_id"] == "T1.1"]
    assert len(target) == 1
    assert target[0]["delta_mean_total_tokens_pct"] > 10.0
    assert target[0]["regression"] is True


def test_check_exits_1_when_mcp_tokens_exceed_terminal(tmp_path, sample_run_records, capsys):
    # Create a violation for version 0.1.0 on task T1.1 by making mcp tokens > terminal.
    results_dir = tmp_path / "results"
    for r in sample_run_records:
        save_result(r, results_dir=str(results_dir))

    violating = RunRecord(
        **{
            **sample_run_records[0].to_dict(),
            "run_id": "77777777-7777-4777-8777-777777777777",
            "timestamp": "2026-05-10T10:00:30Z",
            "total_tokens": 2000,
            "input_tokens": 1500,
            "output_tokens": 500,
        }
    )
    save_result(violating, results_dir=str(results_dir))

    code = compare_main(["--results-dir", str(results_dir), "check", "--version", "0.1.0"])
    out = capsys.readouterr().out
    assert code == 1
    assert "mcp_total_tokens_gt_terminal" in out

