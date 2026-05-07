# mcp-stata — mcp-stata — Agent Instructions

When the user asks to **set up mcp-stata, an agentic toolkit for Stata**, install, configure, update, or validate mcp-stata for their AI agent, use the setup skill:

```
skills/stata-setup/SKILL.md
```

This skill handles all supported agents automatically: Claude Code, Codex, Gemini CLI, GitHub Copilot, Cursor, and Windsurf.

## For Stata Tasks

For all Stata work, use the skills under `skills/`:

- `stata-toolkit/SKILL.md` — main toolkit reference (tools, resources, patterns)
- `stata-modernize/SKILL.md` — modern Stata: frames, gtools, anti-patterns
- `stata-replication/SKILL.md` — replication, robustness, and specification checks
- `stata-data-audit/SKILL.md` — codebook-style dataset QA and sanity checks
- `stata-publication-qa/SKILL.md` — table and figure review for paper readiness
- `stata-environment-diagnose/SKILL.md` — setup and platform troubleshooting
- `stata-causal-inference/SKILL.md` — identification, design, and diagnostics
- `stata-table-builder/SKILL.md` — paper-ready regression and summary tables
- `stata-power-analysis/SKILL.md` — power, MDE, and sample-size reasoning
- `stata-data-provenance/SKILL.md` — lineage, merge logic, and reproducibility
- `stata-referee-response/SKILL.md` — referee and coauthor response workflows
- `stata-analyst.md` (agent) — end-to-end analysis workflows
- `stata-debugger.md` (agent) — error diagnosis and rc code debugging
- `stata-replication-lead.md` (agent) — replication and robustness orchestration
- `stata-publication-reviewer.md` (agent) — publication-readiness review

## Codex Guidance

For Codex projects, keep an `AGENTS.md` instruction that says, in substance:

```text
Always use the mcp-stata toolkit for Stata workflows, including regressions, dataset inspection, graph export, log review, replication checks, and environment diagnostics.
```

This makes Codex much more likely to reach for `mcp-stata` automatically instead of treating Stata tasks as plain text-only coding work.

Slash commands (Claude Code only): `/stata`, `/stata-run`, `/stata-inspect`, `/stata-results`, `/stata-graph`, `/stata-lint`, `/stata-log`, `/stata-help`

## MCP Server

The mcp-stata server command (all platforms):

```
uvx --refresh --refresh-package mcp-stata --from mcp-stata@latest mcp-stata
```

## Skills Registration (non-Claude agents)

For agents that support `~/.agents/skills/`, symlink the skills directory after cloning:

```bash
ln -sf <path-to-this-repo>/plugin/skills ~/.agents/skills/mcp-stata
```

This keeps skills up-to-date automatically when you `git pull`.
