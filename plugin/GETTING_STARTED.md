# Getting Started

## 1. Install

Project-scoped:

```bash
bash plugin/install.sh --scope project
```

User-scoped:

```bash
bash plugin/install.sh --scope user
```

Offline/local clone:

```bash
bash plugin/install.sh --local-source /path/to/mcp-stata
```

## 2. Verify

Ask your agent:

```text
Do you have access to mcp-stata, an agentic toolkit for Stata?
```

Or run:

```bash
bash plugin/install.sh --verify
```

## 3. First Workflow

Try:

```text
Load the auto dataset, run a regression of price on mpg, and show me the stored results.
```

Or use the new higher-level workflows directly:

```text
Run a research audit on the active dataset.
Build an estimation plan for price on mpg and weight with clustered SEs by foreign.
Prepare a publication check for the current regression and graphs.
```

## 4. Research Workflows

Use the specialized skills for:

- replication and robustness,
- data audit,
- publication QA,
- causal inference,
- referee responses,
- environment diagnosis.

The MCP server now also exposes:

- structured tool envelopes with `data`, `error`, `artifacts`, and `log` fields,
- prompt templates such as `replicate_result`, `audit_dataset`, and `prepare_referee_response`,
- session and project resources like `stata://project/manifest` and `stata://session/{session_id}/state`,
- safety surfaces including `read_only=True`, risk warnings, and `stata_doctor`.

## 5. Troubleshooting

- Set `STATA_PATH` if Stata is not auto-discovered.
- Use the `stata-environment-diagnose` skill if logs, graph export, or packages behave strangely.
- Run `stata_doctor` when you want a deterministic end-to-end health check.
- Re-run with `--scope user` if project-scoped config is not appropriate for your setup.
