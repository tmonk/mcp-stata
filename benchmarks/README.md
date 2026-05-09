# Statest Benchmarks

This directory contains performance benchmarks and history for the `statest` framework.

## Structure

- `suites/`: Contains synthetic test suites for performance testing.
  - `significant/`: A suite of 20+ tests used for baseline measurements.
- `history/`: Contains JSON and Markdown results from previous benchmark runs.

## Running Benchmarks

Use the provided script in `benchmarks/scripts/`:

```bash
# Run the 'significant' suite with 4 workers
python3 benchmarks/scripts/benchmark_statest.py --suite significant

# Run both sequential and parallel modes
python3 benchmarks/scripts/benchmark_statest.py --suite significant --sequential
```

## Performance Targets

The current optimized baseline for a 20-test suite is:
- **Sequential**: ~8s (~0.4s/test)
- **Parallel (4 workers)**: ~8.5s (~0.4s/test)

Any significant increase (>10%) in these numbers should be investigated for regressions in session pooling or IPC overhead.
