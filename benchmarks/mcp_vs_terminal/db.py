import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
import os

DB_PATH = os.environ.get("BENCHMARK_DB", "benchmarks.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_runs (
    run_id      TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    model_name  TEXT NOT NULL,
    notes       TEXT,
    source      TEXT NOT NULL DEFAULT 'live'
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

CREATE INDEX IF NOT EXISTS idx_results_run   ON task_results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_task  ON task_results(task_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_results_triplet
  ON task_results(run_id, approach, task_id);

CREATE TABLE IF NOT EXISTS run_artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,           -- e.g. "run_log", "source_log"
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


# ── Runs ──────────────────────────────────────────────────────────────────────

def create_run(model_name: str, notes: str = None, source: str = "live") -> str:
    run_id = (
        f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        f"_{uuid.uuid4().hex[:6]}"
    )
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO benchmark_runs (run_id, created_at, model_name, notes, source)"
            " VALUES (?, ?, ?, ?, ?)",
            (run_id, _now(), model_name, notes, source),
        )
    return run_id


def upsert_run(run_id: str, model_name: str, created_at: str,
               notes: str = None, source: str = "ingested") -> str:
    """Insert a run with a known ID; skip if already exists."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO benchmark_runs"
            " (run_id, created_at, model_name, notes, source)"
            " VALUES (?, ?, ?, ?, ?)",
            (run_id, created_at, model_name, notes, source),
        )
    return run_id


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
            "       r.notes, r.source"
            " FROM task_results t"
            " JOIN benchmark_runs r ON t.run_id = r.run_id"
            " ORDER BY r.created_at DESC, t.task_id, t.approach"
        ).fetchall()
        return [dict(r) for r in rows]


def get_summary_stats():
    """Per-run aggregates used by the dashboard."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.run_id, r.model_name, r.created_at, r.notes, r.source,"
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
