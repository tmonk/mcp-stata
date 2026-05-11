from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import os
from dataclasses import dataclass
from typing import Any, Optional


def _iso_utc_now() -> str:
    # ISO 8601 UTC, stable for sorting.
    return _dt.datetime.now(tz=_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str  # UUID4, generated at run start
    timestamp: str  # ISO 8601 UTC
    mcp_stata_version: str  # from `uvx mcp-stata --version` or pypi metadata
    gemini_model: str  # e.g. "gemini-3-flash-preview"
    git_commit: str  # `git rev-parse HEAD` of the benchmark repo, or "untracked"
    approach: str  # "mcp" or "terminal"
    task_id: str  # e.g. "T1.1"
    input_tokens: int
    output_tokens: int
    total_tokens: int  # must equal input + output
    turns: int
    cost_usd: float  # input/1M*0.50 + output/1M*3.00
    resolution_correct: bool

    # nullable fields
    error_detected: Optional[bool] = None
    turns_to_detect: Optional[int] = None
    tokens_to_detect: Optional[int] = None
    log_bytes_ingested: Optional[int] = None
    context_lost_at_turn: Optional[int] = None
    reruns: Optional[int] = None
    correctness_failures: Optional[int] = None
    bookkeeping_tokens: Optional[int] = None
    session_contaminated: Optional[bool] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        # Forward-compatible: ignore unknown fields.
        allowed = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in allowed}
        rec = cls(**filtered)  # type: ignore[arg-type]
        if rec.total_tokens != rec.input_tokens + rec.output_tokens:
            raise ValueError(
                f"Invalid total_tokens for run_id={rec.run_id}: "
                f"{rec.total_tokens} != {rec.input_tokens}+{rec.output_tokens}"
            )
        return rec


def _results_filename(result: RunRecord) -> str:
    # results/YYYY-MM-DD_{run_id[:8]}.jsonl
    # Date is derived from the run timestamp (preferred); fall back to "today" if unparsable.
    date_str = None
    try:
        ts = result.timestamp
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(ts)
        date_str = dt.date().isoformat()
    except Exception:
        date_str = _dt.datetime.now(tz=_dt.timezone.utc).date().isoformat()
    return f"{date_str}_{result.run_id[:8]}.jsonl"


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _locked_append_line(path: str, line: str) -> None:
    """
    Append a single line to a file with an exclusive advisory lock.

    This is sufficient for multi-process safety on Unix-like systems:
    - Each writer takes a lock before writing.
    - Each write is a single .write() call of a complete line + flush + fsync.
    """
    # fcntl is Unix-only; benchmark runs on macOS/Linux.
    import fcntl  # noqa: PLC0415

    # a+ ensures we never overwrite an existing file.
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
            if not line.endswith("\n"):
                f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def save_result(result: RunRecord, results_dir: str = "results/") -> str:
    """
    Append one RunRecord to a per-run JSONL file.

    Returns the path written to.
    """
    _ensure_dir(results_dir)
    filename = _results_filename(result)
    path = os.path.join(results_dir, filename)
    payload = json.dumps(result.to_dict(), sort_keys=True)
    _locked_append_line(path, payload)
    return path


def _iter_jsonl_files(results_dir: str) -> list[str]:
    if not os.path.isdir(results_dir):
        return []
    paths: list[str] = []
    for name in os.listdir(results_dir):
        if name.endswith(".jsonl"):
            paths.append(os.path.join(results_dir, name))
    return sorted(paths)


def load_results(results_dir: str = "results/") -> list[RunRecord]:
    records: list[RunRecord] = []
    for path in _iter_jsonl_files(results_dir):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                records.append(RunRecord.from_dict(obj))
    records.sort(key=lambda r: r.timestamp)
    return records


def load_results_for_version(version: str, results_dir: str = "results/") -> list[RunRecord]:
    return [r for r in load_results(results_dir=results_dir) if r.mcp_stata_version == version]


__all__ = [
    "RunRecord",
    "save_result",
    "load_results",
    "load_results_for_version",
    "_iso_utc_now",
]

