# Eval Design

The eval runner has two modes.

## Fixture Scoring

Fixture scoring validates that each eval case provides:

- `name`
- `input`
- `expected`

It also records per-fixture pass/fail status and writes a timestamped JSON report under `plugin/evals/reports/`.

## Live Stata Smoke Mode

When `--live-stata` is supplied and Stata is available, the runner performs a compact smoke workflow:

1. Detect the Stata installation
2. Execute a basic command
3. Load `auto`
4. Create a graph and confirm it exists

The live report is merged into the same JSON output so `stata://evals/report/latest` can expose the latest result to clients.
