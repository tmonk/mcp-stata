#!/usr/bin/env python3
"""Measure approximate and exact token counts for Stata log content."""

import argparse
import os
import sys
import json
import re

# Try tiktoken for exact GPT-4 token counts; fall back to rough heuristic
try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))
except Exception:
    def count_tokens(text: str) -> int:
        # Rough heuristic: ~4 chars per token for English/ASCII
        return max(1, len(text) // 4)


def strip_smcl_simple(text: str) -> str:
    """Naive SMCL tag stripper (approximates mcp-stata cleaning)."""
    # Remove SMCL tags like {txt}, {err}, {com}, {hline ...}, etc.
    cleaned = re.sub(r"\{[^{}]*\}", "", text)
    # Collapse multiple newlines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def truncate_tail(text: str, max_tokens: int) -> str:
    """Keep only the tail of the text that fits within max_tokens."""
    total = count_tokens(text)
    if total <= max_tokens:
        return text
    # Binary search for the right cutoff
    low, high = 0, len(text)
    while low < high:
        mid = (low + high) // 2
        truncated = text[mid:]
        if count_tokens(truncated) <= max_tokens:
            high = mid
        else:
            low = mid + 1
    return text[low:]


def extract_error_context(text: str, context_lines: int = 15) -> str:
    """Extract error context from SMCL or plain text."""
    lines = text.splitlines()
    error_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if "{err}" in lines[i] or "r(" in lines[i] and "error" in lines[i].lower():
            error_idx = i
            break
    if error_idx == -1:
        # No error found; return last N lines
        return "\n".join(lines[-context_lines:])
    start = max(0, error_idx - context_lines)
    return "\n".join(lines[start:])


def analyze_log(path: str):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    cleaned = strip_smcl_simple(raw)
    error_ctx = extract_error_context(raw)
    cleaned_error_ctx = strip_smcl_simple(error_ctx)

    results = {
        "file": path,
        "file_size_kb": round(len(raw.encode("utf-8")) / 1024, 2),
        "raw_chars": len(raw),
        "raw_tokens": count_tokens(raw),
        "cleaned_chars": len(cleaned),
        "cleaned_tokens": count_tokens(cleaned),
        "error_context_chars": len(cleaned_error_ctx),
        "error_context_tokens": count_tokens(cleaned_error_ctx),
        "lines": raw.count("\n"),
    }

    # Token budget analysis
    budgets = [500, 1000, 2000, 4000, 8000]
    for budget in budgets:
        tail = truncate_tail(cleaned, budget)
        results[f"tail_{budget}_tokens"] = count_tokens(tail)
        results[f"tail_{budget}_chars"] = len(tail)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    all_results = []
    for path in args.files:
        if not os.path.exists(path):
            print(f"Skip: {path} not found", file=sys.stderr)
            continue
        res = analyze_log(path)
        all_results.append(res)
        if not args.json:
            print(f"\n=== {path} ===")
            for k, v in sorted(res.items()):
                if isinstance(v, float):
                    print(f"  {k}: {v:.1f}")
                else:
                    print(f"  {k}: {v}")

    if args.json:
        print(json.dumps(all_results, indent=2))


if __name__ == "__main__":
    main()
