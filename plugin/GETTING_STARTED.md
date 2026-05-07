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

## 4. Research Workflows

Use the specialized skills for:

- replication and robustness,
- data audit,
- publication QA,
- causal inference,
- referee responses,
- environment diagnosis.

## 5. Troubleshooting

- Set `STATA_PATH` if Stata is not auto-discovered.
- Use the `stata-environment-diagnose` skill if logs, graph export, or packages behave strangely.
- Re-run with `--scope user` if project-scoped config is not appropriate for your setup.
