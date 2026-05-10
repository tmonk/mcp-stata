#!/bin/bash
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTFILE="benchmarks/test_suite/bench_${TIMESTAMP}.txt"
mkdir -p benchmarks/test_suite
time uv run pytest --no-cov --durations=0 > "$OUTFILE" 2>&1 && tail -n 20 "$OUTFILE"
echo "Full output: $OUTFILE"