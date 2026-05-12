"""
ingest.py – Import historical benchmark data into benchmarks.db.

Supported formats
-----------------
results.json          – JSON array of result objects (legacy output)
benchmark_run_N.log   – auto-detected: JSON array, JSON lines, or keyed text
benchmark_run_N.log.json – JSON array or object with a 'results' key

Usage
-----
    python ingest.py                        # ingest all default files
    python ingest.py path/to/file.json ...  # ingest specific files
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import hashlib

from db import init_db, upsert_run, save_result, get_run, save_artifact, get_baseline_run, set_baseline_run

# Files ingested when no CLI args are given
DEFAULT_FILES = [
    "results.json",
    "benchmark_run_1.log",
    "benchmark_run_2.log",
    "benchmark_run_2.log.json",
]

REQUIRED_KEYS = {"approach", "task_id"}


# ── Parsing helpers ────────────────────────────────────────────────────────────

def _parse_json_file(path: Path) -> list[dict]:
    """Parse a file that is a JSON array or an object containing a result list."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("results", "task_results", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # The dict itself might be a single result
        if REQUIRED_KEYS.issubset(data.keys()):
            return [data]
    raise ValueError(f"Unrecognised JSON shape in {path}")


def _parse_jsonl(text: str) -> list[dict]:
    """Parse newline-delimited JSON objects."""
    results = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and REQUIRED_KEYS.issubset(obj.keys()):
                results.append(obj)
        except json.JSONDecodeError:
            pass
    return results


def _extract_inline_json(text: str) -> list[dict]:
    """Pull any {...} blobs from a mixed log file that look like result objects."""
    results = []
    # Greedy match of top-level JSON objects
    for match in re.finditer(r'\{[^{}]*\}', text):
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict) and REQUIRED_KEYS.issubset(obj.keys()):
                results.append(obj)
        except json.JSONDecodeError:
            pass
    return results


def _parse_log_file(path: Path) -> list[dict]:
    """Try multiple strategies to extract result records from a .log file."""
    text = path.read_text(errors="replace")

    # 1. Try full JSON parse
    try:
        return _parse_json_file(path)
    except Exception:
        pass

    # 2. Try JSON lines
    results = _parse_jsonl(text)
    if results:
        return results

    # 3. Try inline JSON objects scattered through log text
    results = _extract_inline_json(text)
    if results:
        return results

    print(f"  [warn] Could not extract any result records from {path.name}")
    return []


def _parse_file(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _parse_json_file(path)
    if suffix == ".log":
        return _parse_log_file(path)
    # Fallback: try json parse, then log parse
    try:
        return _parse_json_file(path)
    except Exception:
        return _parse_log_file(path)


# ── Run-ID derivation ──────────────────────────────────────────────────────────

def _base_stem(filename: str) -> str:
    """Strip compound suffixes like .log.json down to a shared base stem.

    Example:
      benchmark_run_2.log.json -> benchmark_run_2
      benchmark_run_2.log      -> benchmark_run_2
    """
    p = Path(filename)
    name = p.name
    # Remove known suffixes repeatedly
    while True:
        lower = name.lower()
        if lower.endswith(".json"):
            name = name[: -len(".json")]
            continue
        if lower.endswith(".log"):
            name = name[: -len(".log")]
            continue
        break
    base = Path(name).name
    # Canonicalize aliases: results_run_N.* should map to benchmark_run_N.*
    m = re.match(r"results_run_(\d+)$", base)
    if m:
        return f"benchmark_run_{m.group(1)}"
    return base


def _run_id_candidates(filename: str) -> list[str]:
    """Return candidate run_ids; first one found in DB wins."""
    base = _base_stem(filename)
    base_slug = re.sub(r"[^a-z0-9]", "_", base.lower()).strip("_")
    # Back-compat: older behavior used Path(...).stem which can preserve ".log"
    legacy_stem = Path(filename).stem
    legacy_slug = re.sub(r"[^a-z0-9]", "_", legacy_stem.lower()).strip("_")
    cands = [f"run_ingested_{base_slug}", f"run_ingested_{legacy_slug}"]
    # Dedupe while preserving order
    out = []
    for c in cands:
        if c not in out:
            out.append(c)
    return out


def _run_id_from_filename(filename: str) -> str:
    for cand in _run_id_candidates(filename):
        if get_run(cand):
            return cand
    return _run_id_candidates(filename)[0]


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def _ingest_companion_logs(run_id: str, source_path: Path):
    """Attach matching .log files as artifacts for this run."""
    base = _base_stem(source_path.name)
    candidates: list[Path] = [source_path.with_name(f"{base}.log")]

    # Heuristic: results_run_N.json often corresponds to benchmark_run_N.log
    m = re.match(r"results_run_(\d+)$", base)
    if m:
        candidates.append(source_path.with_name(f"benchmark_run_{m.group(1)}.log"))

    # Heuristic: benchmark_run_N.* may also have a "results_run_N.log" companion
    m2 = re.match(r"benchmark_run_(\d+)$", base)
    if m2:
        candidates.append(source_path.with_name(f"results_run_{m2.group(1)}.log"))

    # Dedupe candidates while preserving order
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in candidates:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)

    for log_path in uniq:
        if not log_path.exists() or not log_path.is_file():
            continue
        text = log_path.read_text(errors="replace")
        save_artifact(
            run_id,
            kind="source_log",
            filename=log_path.name,
            content_text=text,
            bytes=log_path.stat().st_size,
            sha256=_sha256_text(text),
            created_at=_timestamp_from_filename(log_path),
        )
        print(f"  Linked artifact {log_path.name!r} → run {run_id!r}")


def _timestamp_from_filename(pathish: str | Path) -> str:
    """Infer a reasonable created_at from the source path/filename.

    Preference order:
    1) YYYY-MM-DD or YYYY_MM_DD embedded in the filename
    2) file mtime (if the path exists)
    3) epoch
    """
    p = Path(pathish)
    m = re.search(r"(\d{4}[-_]\d{2}[-_]\d{2})", p.name)
    if m:
        try:
            return datetime.strptime(m.group(1).replace('_', '-'), "%Y-%m-%d").isoformat()
        except ValueError:
            pass
    # Fallback: file mtime if it exists on disk, else epoch
    if p.exists():
        mtime = p.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    return "1970-01-01T00:00:00+00:00"


# ── Main ingestion ─────────────────────────────────────────────────────────────

def ingest_file(path: Path):
    print(f"\nIngesting: {path}")
    if not path.exists():
        print(f"  [skip] File not found: {path}")
        return

    records = _parse_file(path)
    if not records:
        # Still persist the raw log if it's a companion to an existing run
        if path.suffix.lower() == ".log":
            run_id = _run_id_from_filename(path.name)
            if get_run(run_id):
                text = path.read_text(errors="replace")
                save_artifact(
                    run_id,
                    kind="source_log",
                    filename=path.name,
                    content_text=text,
                    bytes=path.stat().st_size,
                    sha256=_sha256_text(text),
                    created_at=_timestamp_from_filename(path),
                )
                print(f"  Linked artifact {path.name!r} → existing run {run_id!r}")
                return
        print("  [skip] No usable records found.")
        return

    # Persist the source file itself as an artifact (for auditability + dedupe)
    try:
        raw = path.read_text(errors="replace")
        save_artifact(
            _run_id_from_filename(path.name),
            kind="source_results" if path.suffix.lower() == ".json" else "source_file",
            filename=path.name,
            content_text=raw,
            bytes=path.stat().st_size,
            sha256=_sha256_text(raw),
            created_at=_timestamp_from_filename(path),
        )
    except Exception:
        # Artifact persistence is best-effort; do not block ingestion.
        pass

    # Group records by any embedded run_id; fall back to one run per file
    groups: dict[str, list[dict]] = {}
    for rec in records:
        rid = rec.get("run_id") or _run_id_from_filename(path.name)
        groups.setdefault(rid, []).append(rec)

    for run_id, group in groups.items():
        # Determine model name
        model = group[0].get("model_name", "unknown")
        created_at = group[0].get("created_at") or _timestamp_from_filename(path)
        notes = f"Ingested from {path.name}"

        if get_run(run_id):
            print(f"  [skip] Run {run_id!r} already in DB.")
        else:
            upsert_run(run_id, model, created_at, notes=notes, source="ingested")
            print(f"  Created run {run_id!r} ({len(group)} records)  model={model}")

        saved = 0
        for rec in group:
            if not REQUIRED_KEYS.issubset(rec.keys()):
                continue
            save_result(run_id, rec)
            saved += 1

        print(f"  Saved {saved} result(s) under {run_id!r}")
        _ingest_companion_logs(run_id, path)


def main(files: list[str] | None = None):
    init_db()
    targets = [Path(f) for f in (files or DEFAULT_FILES)]
    for path in targets:
        ingest_file(path)

    if not get_baseline_run():
        from db import get_latest_terminal_run
        fallback = get_latest_terminal_run()
        if fallback:
            set_baseline_run(fallback["run_id"])
            print(f"\nAuto-set latest terminal run as baseline: {fallback['run_id']}")
        else:
            print("\nWarning: no terminal runs found to set as baseline.")

    print("\nDone.")


if __name__ == "__main__":
    args = sys.argv[1:] or None
    main(args)
