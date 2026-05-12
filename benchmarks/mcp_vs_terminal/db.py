import sqlite3
import uuid
import re
from contextlib import contextmanager
from datetime import datetime, timezone
import os

DB_PATH = os.environ.get("BENCHMARK_DB", "benchmarks.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_runs (
    run_id       TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    model_name   TEXT NOT NULL,
    notes        TEXT,
    source       TEXT NOT NULL DEFAULT 'live',
    is_baseline  INTEGER NOT NULL DEFAULT 0,
    mcp_version  TEXT
);

CREATE TABLE IF NOT EXISTS task_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
    approach        TEXT NOT NULL,
    task_id         TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    turns           INTEGER,
    final_response  TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_results_run    ON task_results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_task   ON task_results(task_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_results_triplet
  ON task_results(run_id, approach, task_id);

CREATE TABLE IF NOT EXISTS run_artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,
    filename      TEXT NOT NULL,
    bytes         INTEGER,
    sha256        TEXT,
    content_text  TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE(run_id, kind, filename)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_run  ON run_artifacts(run_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def parse_mcp_version(notes: str | None) -> str | None:
    """Extract MCP version string from notes field."""
    if not notes:
        return None
    m = re.search(r'\[LOCAL:\s*([^\]]+)\]', notes)
    if m:
        return m.group(1).strip()
    m = re.search(r'mcp-stata[vV]?(\d+\.\d+(?:\.\d+)?)', notes)
    if m:
        return m.group(0)
    return None


# ── Runs ──────────────────────────────────────────────────────────────────────

def create_run(
    model_name: str,
    notes: str = None,
    source: str = "live",
    is_baseline: bool = False,
    mcp_version: str = None,
) -> str:
    run_id = (
        f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        f"_{uuid.uuid4().hex[:6]}"
    )
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO benchmark_runs"
            " (run_id, created_at, model_name, notes, source, is_baseline, mcp_version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, _now(), model_name, notes, source, int(is_baseline), mcp_version),
        )
    return run_id


def upsert_run(
    run_id: str,
    model_name: str,
    created_at: str,
    notes: str = None,
    source: str = "ingested",
    is_baseline: bool = False,
    mcp_version: str = None,
) -> str:
    """Insert a run with a known ID; skip if already exists."""
    parsed_version = mcp_version or parse_mcp_version(notes)
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO benchmark_runs"
            " (run_id, created_at, model_name, notes, source, is_baseline, mcp_version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, created_at, model_name, notes, source, int(is_baseline), parsed_version),
        )
    return run_id


def get_baseline_run():
    """Return the run marked as baseline, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM benchmark_runs WHERE is_baseline = 1 LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_latest_terminal_run():
    """Return the most recent run that is either ingested (source='ingested')
    or has no mcp_version — essentially, a terminal-style run."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM benchmark_runs"
            " WHERE mcp_version IS NULL OR source = 'ingested'"
            " ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_default_baseline():
    """Return the best available baseline: explicit is_baseline run, or latest terminal run."""
    baseline = get_baseline_run()
    if baseline:
        return baseline
    return get_latest_terminal_run()


def set_baseline_run(run_id: str):
    """Set exactly one run as baseline (clears any existing baseline)."""
    with get_conn() as conn:
        conn.execute("UPDATE benchmark_runs SET is_baseline = 0 WHERE is_baseline = 1")
        conn.execute(
            "UPDATE benchmark_runs SET is_baseline = 1 WHERE run_id = ?", (run_id,)
        )


def get_all_runs():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.*, COUNT(t.id) AS result_count"
            " FROM benchmark_runs r"
            " LEFT JOIN task_results t ON t.run_id = r.run_id"
            " GROUP BY r.run_id"
            " ORDER BY r.created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_mcp_runs():
    """Return all runs that have an mcp_version set."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.*, COUNT(t.id) AS result_count"
            " FROM benchmark_runs r"
            " LEFT JOIN task_results t ON t.run_id = r.run_id"
            " WHERE r.mcp_version IS NOT NULL"
            " GROUP BY r.run_id"
            " ORDER BY r.created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_terminal_runs():
    """Return all runs that don't have an mcp_version (i.e., terminal/baseline runs)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.*, COUNT(t.id) AS result_count"
            " FROM benchmark_runs r"
            " LEFT JOIN task_results t ON t.run_id = r.run_id"
            " WHERE r.mcp_version IS NULL"
            " GROUP BY r.run_id"
            " ORDER BY r.created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_run(run_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM benchmark_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None


# ── Results ───────────────────────────────────────────────────────────────────

def save_result(run_id: str, result: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO task_results"
            " (run_id, approach, task_id, input_tokens, output_tokens,"
            "  turns, final_response, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(run_id, approach, task_id) DO UPDATE SET"
            "   input_tokens   = excluded.input_tokens,"
            "   output_tokens  = excluded.output_tokens,"
            "   turns          = excluded.turns,"
            "   final_response = excluded.final_response,"
            "   created_at     = excluded.created_at",
            (
                run_id,
                result["approach"],
                str(result["task_id"]),
                result.get("input_tokens"),
                result.get("output_tokens"),
                result.get("turns"),
                result.get("final_response"),
                _now(),
            ),
        )


def get_run_results(run_id: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM task_results WHERE run_id = ?"
            " ORDER BY task_id, approach",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_results():
    """Flat join of all results with their run metadata."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT t.*, r.model_name, r.created_at AS run_date,"
            "       r.notes, r.source, r.is_baseline, r.mcp_version"
            " FROM task_results t"
            " JOIN benchmark_runs r ON t.run_id = r.run_id"
            " ORDER BY r.created_at DESC, t.task_id, t.approach"
        ).fetchall()
        return [dict(r) for r in rows]


def get_run_comparison(run_id: str):
    """
    Returns {run, baseline, deltas} for a given run.
    - 'run': this run's metadata + results
    - 'baseline': the default baseline run's results (keyed by task_id)
    - 'deltas': per-task delta dicts comparing this run to baseline
    Returns None if run_id not found.
    """
    run = get_run(run_id)
    if not run:
        return None

    run_results = {}
    for r in get_run_results(run_id):
        if r["approach"] == "mcp":
            run_results[r["task_id"]] = r

    baseline = get_default_baseline()
    baseline_results = {}
    deltas = []

    if baseline:
        for r in get_run_results(baseline["run_id"]):
            approach = r["approach"]
            if approach in ("baseline", "terminal"):
                baseline_results[r["task_id"]] = r

    all_task_ids = sorted(set(run_results.keys()) | set(baseline_results.keys()))

    for task_id in all_task_ids:
        mcp_r = run_results.get(task_id, {})
        base_r = baseline_results.get(task_id, {})

        mcp_in = mcp_r.get("input_tokens") or 0
        mcp_out = mcp_r.get("output_tokens") or 0
        mcp_tot = mcp_in + mcp_out
        base_in = base_r.get("input_tokens") if base_r else None
        base_out = base_r.get("output_tokens") if base_r else None
        base_tot = (base_in + base_out) if base_in is not None else None

        delta = None
        if base_tot is not None:
            delta = {
                "task_id": task_id,
                "mcp_input": mcp_in,
                "mcp_output": mcp_out,
                "mcp_total": mcp_tot,
                "baseline_input": base_in,
                "baseline_output": base_out,
                "baseline_total": base_tot,
                "input_delta": mcp_in - base_in,
                "output_delta": mcp_out - base_out,
                "total_delta": mcp_tot - base_tot,
                "turns_mcp": mcp_r.get("turns"),
                "turns_baseline": base_r.get("turns") if base_r else None,
                "mcp_final_response": mcp_r.get("final_response"),
                "baseline_final_response": base_r.get("final_response") if base_r else None,
            }
        else:
            delta = {
                "task_id": task_id,
                "mcp_input": mcp_in,
                "mcp_output": mcp_out,
                "mcp_total": mcp_tot,
                "baseline_input": None,
                "baseline_output": None,
                "baseline_total": None,
                "input_delta": None,
                "output_delta": None,
                "total_delta": None,
                "turns_mcp": mcp_r.get("turns"),
                "turns_baseline": None,
                "mcp_final_response": mcp_r.get("final_response"),
                "baseline_final_response": None,
            }

        deltas.append(delta)

    return {
        "run": {**run, "results": run_results},
        "baseline": {**baseline, "results": baseline_results} if baseline else None,
        "deltas": deltas,
    }


def get_summary_stats():
    """Per-run aggregates used by the dashboard."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.run_id, r.model_name, r.created_at, r.notes, r.source,"
            "       r.is_baseline, r.mcp_version,"
            "       COUNT(t.id)           AS total_tasks,"
            "       SUM(t.input_tokens)   AS total_input_tokens,"
            "       SUM(t.output_tokens)  AS total_output_tokens,"
            "       AVG(t.turns)          AS avg_turns,"
            "       MAX(t.turns)          AS max_turns"
            " FROM benchmark_runs r"
            " LEFT JOIN task_results t ON t.run_id = r.run_id"
            " GROUP BY r.run_id"
            " ORDER BY r.created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ── Artifacts ────────────────────────────────────────────────────────────────

def save_artifact(
    run_id: str,
    *,
    kind: str,
    filename: str,
    content_text: str,
    bytes: int | None = None,
    sha256: str | None = None,
    created_at: str | None = None,
):
    created_at = created_at or _now()
    if bytes is None:
        bytes = len(content_text.encode("utf-8", errors="replace"))
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO run_artifacts"
            " (run_id, kind, filename, bytes, sha256, content_text, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, kind, filename, bytes, sha256, content_text, created_at),
        )


def get_run_artifacts(run_id: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM run_artifacts WHERE run_id = ? ORDER BY created_at DESC, kind, filename",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
