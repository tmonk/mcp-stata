#!/usr/bin/env python3
"""Benchmark backward error scanning on large SMCL logs."""

import argparse
import os
import re
import time


def scan_backwards_naive(text: str, error_marker: str = "{err}", max_lines: int = 20):
    """Naive backwards scan: split all lines, search from end."""
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if error_marker in lines[i]:
            start = max(0, i - max_lines)
            return "\n".join(lines[start:])
    return None


def scan_backwards_chunked(text: str, error_marker: str = "{err}", chunk_size: int = 8192, max_lines: int = 20):
    """Memory-efficient chunked backwards scan (simulates _read_log_backwards_until_error)."""
    bytes_data = text.encode("utf-8")
    total = len(bytes_data)
    position = total
    buffer = ""
    total_read = 0
    max_total = 5_000_000  # 5MB safety limit

    while position > 0 and total_read < max_total:
        read_size = min(chunk_size, position, max_total - total_read)
        position -= read_size
        chunk = bytes_data[position:position + read_size].decode("utf-8", errors="replace")
        buffer = chunk + buffer
        total_read += read_size

        lines = buffer.splitlines()
        for i in range(len(lines) - 1, -1, -1):
            if error_marker in lines[i]:
                start = max(0, i - max_lines)
                return "\n".join(lines[start:])

    # No error found in safety limit
    return None


def benchmark(path: str):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    size_kb = len(text.encode("utf-8")) / 1024
    print(f"\nFile: {path} ({size_kb:.1f} KB, {text.count(chr(10))} lines)")

    # Naive scan
    t0 = time.perf_counter()
    result_naive = scan_backwards_naive(text)
    t1 = time.perf_counter()
    print(f"  Naive scan:     {((t1-t0)*1000):>8.3f} ms  -> found={result_naive is not None}")

    # Chunked scan
    t0 = time.perf_counter()
    result_chunked = scan_backwards_chunked(text)
    t1 = time.perf_counter()
    print(f"  Chunked scan:   {((t1-t0)*1000):>8.3f} ms  -> found={result_chunked is not None}")

    if result_naive:
        tokens_approx = len(result_naive) // 4
        print(f"  Error context size: ~{tokens_approx} tokens ({len(result_naive)} chars)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    for path in args.files:
        if os.path.exists(path):
            benchmark(path)
        else:
            print(f"Not found: {path}")


if __name__ == "__main__":
    main()
