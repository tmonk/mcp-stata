# mcp-stata Plugin

MCP tools, skills, and specialist agents for academic Stata workflows. The plugin connects supported coding agents to a local Stata installation and adds paper-oriented skills for replication, data audit, publication QA, causal inference, and referee-response work.

## Install

### Claude plugin install

```text
/plugin install mcp-stata
```

Or directly from the repository:

```text
/plugin install https://github.com/tmonk/mcp-stata
```

### Generic installer

Project-scoped install:

```bash
bash plugin/install.sh --scope project
```

User-scoped install:

```bash
bash plugin/install.sh --scope user
```

Offline or local-source install:

```bash
bash plugin/install.sh --local-source /path/to/mcp-stata
```

Other useful variants:

```bash
bash plugin/install.sh --agent codex
bash plugin/install.sh --agent all
bash plugin/install.sh --version 2.5.1
bash plugin/install.sh --dry-run
bash plugin/install.sh --verify
```

Supports: `claude`, `codex`, `gemini`, `cursor`, `windsurf`, `vscode`.

## What Gets Installed

- MCP server registration under the canonical id `mcp-stata`
- Project or user config depending on `--scope`
- Codex skill symlink under `~/.codex/skills/mcp-stata`
- Shared skill symlink under `~/.agents/skills/mcp-stata` for compatible agents
- Gemini extension metadata from `plugin/gemini-extension.json`
- A managed `mcp-stata` block in project-root `AGENTS.md` for Codex discovery

## Academic Workflows

- Replication and robustness checks
- Data audit before estimation
- Publication QA for tables and figures
- Causal inference workflow support
- Referee-response reruns and evidence tracking
- Environment diagnosis on managed or unusual machines

## New MCP Surfaces

- Structured tool envelopes with explicit `data`, `error`, `artifacts`, and `log` fields
- Prompt templates for replication, audit, debugging, causal design, and referee responses
- Session/project resources such as `stata://project/manifest` and `stata://session/{session_id}/state`
- Runtime guardrails including risk classification, path allowlists, `read_only=True`, and `stata_doctor`

## Plugin Files

| File/Dir | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | Claude Code plugin registry manifest |
| `.codex-plugin/plugin.json` | Codex plugin registry manifest |
| `.agents/plugins/marketplace.json` | Generic plugin manifest |
| `.mcp.json` | Project-scoped MCP config template |
| `AGENTS.md` | Agent-facing guidance for non-Claude clients |
| `gemini-extension.json` | Gemini CLI extension metadata |
| `hooks/hooks.json` | Claude Code session-start reminder hook |

## Skills

### Model-Invoked

<!-- BEGIN GENERATED_MODEL_SKILLS -->
| Skill | Trigger |
|---|---|
| `stata-causal-inference` | Design, run, and critique causal inference workflows in Stata. Use when the user is working on identification, treatment effects, DiD, IV, event studies, RD, or assumption-sensitive empirical claims. |
| `stata-data-audit` | Audit datasets for structure, missingness, labeling, suspicious values, duplicate identifiers, and documentation readiness. Use when a researcher asks for data QA, codebook review, sanity checks, or pre-analysis cleanup guidance. |
| `stata-data-provenance` | Track dataset lineage, transformation steps, merge logic, and reproducibility risks in Stata workflows. Use when the user needs to explain where data came from, how it changed, or why a pipeline can be trusted. |
| `stata-environment-diagnose` | Diagnose local Stata, MCP, package, startup, graph-export, and permissions issues. Use when setup is failing, Stata is not discovered, packages are missing, logs are truncated, or a managed machine behaves differently from a normal workstation. |
| `stata-modernize` | Improve, modernize, and optimize existing Stata code for performance, portability, and maintainability. Use when legacy patterns such as preserve/restore, cd, #delimit, slow aggregation, or weak fixed-effects workflows appear in code under review. |
| `stata-power-analysis` | Plan and critique power, MDE, and sample-size calculations for Stata-based research workflows. Use when the user is designing a study, checking detectability, or defending precision claims. |
| `stata-publication-qa` | Review regression outputs, tables, and graphs for publication readiness. Use when the user asks whether a result is ready for a paper, appendix, seminar, referee response, or coauthor review. |
| `stata-referee-response` | Organize and execute Stata workflows for referee responses, robustness requests, and coauthor follow-ups. Use when the user needs to answer a critique with targeted reruns, tables, figures, and a defensible audit trail. |
| `stata-replication` | Run replication, robustness, and specification-sensitivity workflows for Stata projects. Use when a researcher wants to reproduce a result, rerun a pipeline, compare specifications, audit a do-file sequence, or check whether a claim is stable. |
| `stata-table-builder` | Build and review paper-ready regression, balance, and summary tables from Stata outputs. Use when the user needs a clean table for a draft, appendix, or coauthor share-out. |
| `stata-toolkit` | Activate when users mention Stata commands, .do files, regressions, econometrics, stored results, graphs, dataset inspection, replication, or Stata errors. Route the task through mcp-stata tools and the specialized research skills instead of treating it as plain text coding. |
<!-- END GENERATED_MODEL_SKILLS -->

### Slash Commands

<!-- BEGIN GENERATED_SLASH_SKILLS -->
| Command | Description |
|---|---|
| `/stata` | Show mcp-stata identity, connected tools, and status. Use when the user asks if mcp-stata is available, asks about access to the toolkit, or asks what Stata tools are connected. |
| `/stata-graph [graph_name]` | List, export, and review Stata graphs from the current session. |
| `/stata-help <topic>` | Look up Stata command documentation and display formatted help text. |
| `/stata-inspect [variable]` | Describe and summarize the current dataset in memory. Optionally inspect a specific variable with codebook. |
| `/stata-lint <path>` | Run static analysis on a Stata .do or .ado file and report style and best-practice issues. |
| `/stata-log <path or task_id> [search_term]` | Tail, read, or search a Stata log file from a previous command or background task. |
| `/stata-results` | Fetch and display stored r(), e(), and s() results from the last Stata command. |
| `/stata-run <code or /path/to/file.do>` | Run arbitrary Stata code or a .do file and display the result. |
| `/stata-setup` | Install, configure, update, or verify mcp-stata across Claude Code, Codex, Gemini CLI, Cursor, Windsurf, and VS Code. Activate when users ask to set up the Stata toolkit or troubleshoot the installation. |
<!-- END GENERATED_SLASH_SKILLS -->

## Agents

<!-- BEGIN GENERATED_AGENTS -->
| Agent | Purpose |
|---|---|
| `stata-analyst` | End-to-end statistical analysis agent for Stata. Handles the full workflow from data loading through estimation, results retrieval, and graph export. Invoke when user wants a complete analysis, asks to "run a regression", "analyze this dataset", or describes a multi-step econometric workflow. |
| `stata-debugger` | Stata error diagnosis and debugging agent. Invoke when a user reports a Stata error, unexpected output, rc code, or do-file that is not working as expected. |
| `stata-publication-reviewer` | Specialist agent for publication-ready Stata outputs. Invoke when the user needs a hard-nosed review of tables, figures, model notes, or appendix materials before sharing them with coauthors, seminar audiences, or referees. |
| `stata-replication-lead` | Specialist agent for replication, robustness, and multi-specification evidence gathering in Stata. Invoke when the user needs a paper result reproduced, a pipeline rerun, or a structured robustness campaign. |
<!-- END GENERATED_AGENTS -->

## Verification

Ask your agent:

```text
Do you have access to mcp-stata, an agentic toolkit for Stata?
```

Or in Claude Code:

```text
/stata
```

## More Docs

- [GETTING_STARTED.md](GETTING_STARTED.md)
- [SECURITY.md](SECURITY.md)
- [EVALS.md](EVALS.md)

## Source

[github.com/tmonk/mcp-stata](https://github.com/tmonk/mcp-stata) · AGPL-3.0-or-later · Thomas Monk
