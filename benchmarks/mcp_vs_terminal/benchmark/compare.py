from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict
from typing import Any, Iterable

from .results import RunRecord, load_results


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return (math.nan, math.nan)
    if len(values) == 1:
        return (values[0], 0.0)
    return (statistics.mean(values), statistics.stdev(values))


def _fmt_float(x: float, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "nan"
    return f"{x:.{digits}f}"


def _fmt_int(x: float) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "nan"
    return str(int(round(x)))


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    # Minimal plain-text table (no external deps).
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(r: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r))

    out = [fmt_row(headers), fmt_row(["-" * w for w in widths])]
    out.extend(fmt_row(r) for r in rows)
    return "\n".join(out)


def summarize(records: list[RunRecord]) -> list[dict[str, Any]]:
    """
    Group by (mcp_stata_version, approach, task_id) and report mean/std of:
    total_tokens, turns, cost_usd.
    """
    groups: dict[tuple[str, str, str], list[RunRecord]] = defaultdict(list)
    for r in records:
        groups[(r.mcp_stata_version, r.approach, r.task_id)].append(r)

    out: list[dict[str, Any]] = []
    for (ver, approach, task_id), rs in sorted(groups.items()):
        tokens = [float(r.total_tokens) for r in rs]
        turns = [float(r.turns) for r in rs]
        cost = [float(r.cost_usd) for r in rs]
        mt, st = _mean_std(tokens)
        mtr, str_ = _mean_std(turns)
        mc, sc = _mean_std(cost)
        out.append(
            {
                "mcp_stata_version": ver,
                "approach": approach,
                "task_id": task_id,
                "n": len(rs),
                "mean_total_tokens": mt,
                "std_total_tokens": st,
                "mean_turns": mtr,
                "std_turns": str_,
                "mean_cost_usd": mc,
                "std_cost_usd": sc,
            }
        )
    return out


def _group_means_by(records: Iterable[RunRecord], key_fields: tuple[str, str]) -> dict[tuple[str, str], dict[str, float]]:
    """
    Build means by (approach, task_id) (or similar 2-tuple), returning:
      key -> {mean_total_tokens, mean_turns, mean_cost_usd}
    """
    groups: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for r in records:
        k = tuple(getattr(r, f) for f in key_fields)  # type: ignore[misc]
        groups[k].append(r)

    means: dict[tuple[str, str], dict[str, float]] = {}
    for k, rs in groups.items():
        means[k] = {
            "mean_total_tokens": float(statistics.mean(r.total_tokens for r in rs)),
            "mean_turns": float(statistics.mean(r.turns for r in rs)),
            "mean_cost_usd": float(statistics.mean(r.cost_usd for r in rs)),
        }
    return means


def diff_versions(records: list[RunRecord], version_a: str, version_b: str) -> list[dict[str, Any]]:
    ra = [r for r in records if r.mcp_stata_version == version_a]
    rb = [r for r in records if r.mcp_stata_version == version_b]

    ma = _group_means_by(ra, ("approach", "task_id"))
    mb = _group_means_by(rb, ("approach", "task_id"))

    common = sorted(set(ma.keys()) & set(mb.keys()))
    out: list[dict[str, Any]] = []
    for (approach, task_id) in common:
        a = ma[(approach, task_id)]
        b = mb[(approach, task_id)]
        delta_tokens = b["mean_total_tokens"] - a["mean_total_tokens"]
        pct = (delta_tokens / a["mean_total_tokens"] * 100.0) if a["mean_total_tokens"] else math.inf
        delta_turns = b["mean_turns"] - a["mean_turns"]
        delta_cost = b["mean_cost_usd"] - a["mean_cost_usd"]
        regression = (approach == "mcp") and (pct > 10.0)
        out.append(
            {
                "approach": approach,
                "task_id": task_id,
                "version_a": version_a,
                "version_b": version_b,
                "delta_mean_total_tokens": delta_tokens,
                "delta_mean_total_tokens_pct": pct,
                "delta_mean_turns": delta_turns,
                "delta_mean_cost_usd": delta_cost,
                "regression": regression,
            }
        )
    return out


def diff_approaches(records: list[RunRecord], version: str, approach_a: str, approach_b: str) -> list[dict[str, Any]]:
    rv = [r for r in records if r.mcp_stata_version == version]
    ma = _group_means_by([r for r in rv if r.approach == approach_a], ("approach", "task_id"))
    mb = _group_means_by([r for r in rv if r.approach == approach_b], ("approach", "task_id"))

    # Keys are (approach, task_id). Align by task_id.
    tasks_a = {task_id for (_ap, task_id) in ma.keys()}
    tasks_b = {task_id for (_ap, task_id) in mb.keys()}
    common_tasks = sorted(tasks_a & tasks_b)

    out: list[dict[str, Any]] = []
    for task_id in common_tasks:
        a = ma[(approach_a, task_id)]
        b = mb[(approach_b, task_id)]
        delta_tokens = b["mean_total_tokens"] - a["mean_total_tokens"]
        pct = (delta_tokens / a["mean_total_tokens"] * 100.0) if a["mean_total_tokens"] else math.inf
        delta_turns = b["mean_turns"] - a["mean_turns"]
        delta_cost = b["mean_cost_usd"] - a["mean_cost_usd"]
        out.append(
            {
                "approach_a": approach_a,
                "approach_b": approach_b,
                "task_id": task_id,
                "version": version,
                "delta_mean_total_tokens": delta_tokens,
                "delta_mean_total_tokens_pct": pct,
                "delta_mean_turns": delta_turns,
                "delta_mean_cost_usd": delta_cost,
            }
        )
    return out


def check_version(records: list[RunRecord], version: str) -> list[dict[str, Any]]:
    """
    Returns a list of offending rows. Empty means pass.
    """
    rv = [r for r in records if r.mcp_stata_version == version]
    if not rv:
        return []

    # Use mean comparisons for token + turns_to_detect checks (robust across reruns).
    means = _group_means_by(rv, ("approach", "task_id"))

    # Build per-task mean turns_to_detect for mcp/terminal when present.
    ttd_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in rv:
        if r.turns_to_detect is not None:
            ttd_groups[(r.approach, r.task_id)].append(int(r.turns_to_detect))
    mean_ttd: dict[tuple[str, str], float] = {
        k: float(statistics.mean(v)) for k, v in ttd_groups.items() if v
    }

    offenders: list[dict[str, Any]] = []

    # 1) Any mcp task has total_tokens > corresponding terminal task.
    tasks = sorted(
        {task_id for (_ap, task_id) in means.keys() if (_ap in ("mcp", "terminal"))}
    )
    for task_id in tasks:
        if ("mcp", task_id) in means and ("terminal", task_id) in means:
            if means[("mcp", task_id)]["mean_total_tokens"] > means[("terminal", task_id)]["mean_total_tokens"]:
                offenders.append(
                    {
                        "rule": "mcp_total_tokens_gt_terminal",
                        "task_id": task_id,
                        "mcp_mean_total_tokens": means[("mcp", task_id)]["mean_total_tokens"],
                        "terminal_mean_total_tokens": means[("terminal", task_id)]["mean_total_tokens"],
                    }
                )

    # 2) Any T2/T3 task has resolution_correct == False (any failing run).
    for r in rv:
        if (r.task_id.startswith("T2") or r.task_id.startswith("T3")) and (not r.resolution_correct):
            offenders.append(
                {
                    "rule": "resolution_incorrect",
                    "task_id": r.task_id,
                    "approach": r.approach,
                    "run_id": r.run_id,
                }
            )

    # 3) Any mcp T2 task has turns_to_detect > corresponding terminal task.
    for task_id in tasks:
        if not task_id.startswith("T2"):
            continue
        km = ("mcp", task_id)
        kt = ("terminal", task_id)
        if km in mean_ttd and kt in mean_ttd:
            if mean_ttd[km] > mean_ttd[kt]:
                offenders.append(
                    {
                        "rule": "mcp_turns_to_detect_gt_terminal",
                        "task_id": task_id,
                        "mcp_mean_turns_to_detect": mean_ttd[km],
                        "terminal_mean_turns_to_detect": mean_ttd[kt],
                    }
                )

    return offenders


def _cmd_summary(records: list[RunRecord], as_json: bool) -> int:
    if not records:
        print("No results found")
        return 0

    rows = summarize(records)
    if as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    headers = [
        "mcp_stata_version",
        "approach",
        "task_id",
        "n",
        "mean_total_tokens",
        "std_total_tokens",
        "mean_turns",
        "std_turns",
        "mean_cost_usd",
        "std_cost_usd",
    ]
    table_rows: list[list[str]] = []
    for r in rows:
        table_rows.append(
            [
                str(r["mcp_stata_version"]),
                str(r["approach"]),
                str(r["task_id"]),
                str(r["n"]),
                _fmt_int(r["mean_total_tokens"]),
                _fmt_float(r["std_total_tokens"], 1),
                _fmt_float(r["mean_turns"], 2),
                _fmt_float(r["std_turns"], 2),
                _fmt_float(r["mean_cost_usd"], 4),
                _fmt_float(r["std_cost_usd"], 4),
            ]
        )
    print(_render_table(headers, table_rows))
    return 0


def _cmd_diff_versions(records: list[RunRecord], version_a: str, version_b: str, as_json: bool) -> int:
    if not records:
        print("No results found")
        return 0
    rows = diff_versions(records, version_a=version_a, version_b=version_b)
    if as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    if not rows:
        print("No comparable rows found")
        return 0

    headers = [
        "approach",
        "task_id",
        "Δtokens",
        "Δtokens(%)",
        "Δturns",
        "Δcost_usd",
        "flag",
    ]
    table_rows: list[list[str]] = []
    for r in rows:
        flag = "REGRESSION" if r["regression"] else ""
        table_rows.append(
            [
                str(r["approach"]),
                str(r["task_id"]),
                _fmt_int(r["delta_mean_total_tokens"]),
                _fmt_float(r["delta_mean_total_tokens_pct"], 1),
                _fmt_float(r["delta_mean_turns"], 2),
                _fmt_float(r["delta_mean_cost_usd"], 4),
                flag,
            ]
        )
    print(_render_table(headers, table_rows))
    return 0


def _cmd_diff_approaches(
    records: list[RunRecord], version: str, approach_a: str, approach_b: str, as_json: bool
) -> int:
    if not records:
        print("No results found")
        return 0
    rows = diff_approaches(records, version=version, approach_a=approach_a, approach_b=approach_b)
    if as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    if not rows:
        print("No comparable rows found")
        return 0

    headers = [
        "task_id",
        "approach_a",
        "approach_b",
        "Δtokens",
        "Δtokens(%)",
        "Δturns",
        "Δcost_usd",
    ]
    table_rows: list[list[str]] = []
    for r in rows:
        table_rows.append(
            [
                str(r["task_id"]),
                str(r["approach_a"]),
                str(r["approach_b"]),
                _fmt_int(r["delta_mean_total_tokens"]),
                _fmt_float(r["delta_mean_total_tokens_pct"], 1),
                _fmt_float(r["delta_mean_turns"], 2),
                _fmt_float(r["delta_mean_cost_usd"], 4),
            ]
        )
    print(_render_table(headers, table_rows))
    return 0


def _cmd_check(records: list[RunRecord], version: str, as_json: bool) -> int:
    if not records:
        print("No results found")
        return 0
    offenders = check_version(records, version=version)
    if as_json:
        print(json.dumps(offenders, indent=2, sort_keys=True))
    else:
        if not offenders:
            print("OK")
        else:
            headers = sorted({k for o in offenders for k in o.keys()})
            table_rows = [[str(o.get(h, "")) for h in headers] for o in offenders]
            print(_render_table(headers, table_rows))
    return 1 if offenders else 0


def _normalize_global_flags(argv: list[str]) -> list[str]:
    """
    Allow global flags to appear before or after the subcommand.

    argparse only supports "global before subcommand" by default; this
    rewrites argv so users can do either:
      python -m benchmark.compare --results-dir X summary
      python -m benchmark.compare summary --results-dir X
    """
    if not argv:
        return argv

    out: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--json":
            out.append("--json")
            i += 1
            continue
        if a == "--results-dir":
            if i + 1 >= len(argv):
                out.append(a)
                i += 1
                continue
            out.extend([a, argv[i + 1]])
            i += 2
            continue
        rest.append(a)
        i += 1
    return out + rest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m benchmark.compare")
    p.add_argument("--results-dir", default="results/", help="Directory containing JSONL result files")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of plain text")

    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("summary", help="Summarize all runs")
    s.set_defaults(_cmd="summary")

    d = sub.add_parser("diff", help="Compute diffs between versions or approaches")
    d.add_argument("--version-a", help="Version A (compare versions mode)")
    d.add_argument("--version-b", help="Version B (compare versions mode)")
    d.add_argument("--approach-a", choices=["mcp", "terminal"], help="Approach A (compare approaches mode)")
    d.add_argument("--approach-b", choices=["mcp", "terminal"], help="Approach B (compare approaches mode)")
    d.add_argument("--version", help="Version (compare approaches mode)")
    d.set_defaults(_cmd="diff")

    c = sub.add_parser("check", help="Check invariants for a single version")
    c.add_argument("--version", required=True)
    c.set_defaults(_cmd="check")

    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    argv2 = _normalize_global_flags(raw_argv)
    args = p.parse_args(argv2)
    records = load_results(results_dir=args.results_dir)

    if args._cmd == "summary":
        return _cmd_summary(records, as_json=args.json)

    if args._cmd == "diff":
        # Mode 1: compare versions.
        if args.version_a and args.version_b:
            return _cmd_diff_versions(records, args.version_a, args.version_b, as_json=args.json)
        # Mode 2: compare approaches within a version.
        if args.version and args.approach_a and args.approach_b:
            return _cmd_diff_approaches(records, args.version, args.approach_a, args.approach_b, as_json=args.json)
        raise SystemExit("diff requires either --version-a/--version-b OR --version/--approach-a/--approach-b")

    if args._cmd == "check":
        return _cmd_check(records, version=args.version, as_json=args.json)

    raise SystemExit("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())

