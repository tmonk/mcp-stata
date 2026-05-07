# Evals

The toolkit includes mocked eval fixtures and a lightweight eval runner.

## Run mocked evals

```bash
python scripts/run_toolkit_evals.py
```

## Optional live Stata mode

```bash
python scripts/run_toolkit_evals.py --live-stata
```

Live mode is opt-in and should only be used when Stata is available and you want an end-to-end smoke test.

## What the evals cover

- replication comparisons,
- data audit findings,
- publication QA scaffolds,
- environment-report formatting,
- table-readiness checks.
