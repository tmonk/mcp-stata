# Evals

The toolkit now ships with a scored eval runner that validates fixture integrity, produces JSON reports, and can execute an optional live-Stata smoke workflow.

## Run scored fixture evals

```bash
./.venv/bin/python plugin/evals/run_toolkit_evals.py
```

The runner writes timestamped reports under `plugin/evals/reports/` and updates the `stata://evals/report/latest` resource.

## Run live smoke checks

```bash
./.venv/bin/python plugin/evals/run_toolkit_evals.py --live-stata
```

Live mode runs a compact discovery, execution, and graph pipeline smoke test when Stata is available.

## What the evals cover

- replication fixture structure,
- data audit findings,
- publication QA scaffolds,
- environment-report formatting,
- table-readiness checks,
- live discovery/execution/graph readiness when enabled.
