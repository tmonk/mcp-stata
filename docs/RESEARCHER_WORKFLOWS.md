# Researcher Workflows

`mcp-stata` now exposes a layered workflow surface for academic research.

## Core Workflow Tools

- `stata_research_audit`: dataset structure, labels, missingness, and identifier checks
- `stata_estimation_plan`: preflight planning for estimators, fixed effects, and clustered SEs
- `stata_compare_specs`: structured comparison across baseline and alternative commands
- `stata_publication_check`: active result and graph review for paper readiness
- `stata_project_reproducibility_report`: project-level manifest, environment, and recent log summary
- `stata_doctor`: deterministic health check for discovery, execution, and graph readiness

## Prompt Templates

- `replicate_result`
- `audit_dataset`
- `review_table`
- `debug_do_file`
- `design_causal_spec`
- `prepare_referee_response`

## Resource Surface

- `stata://project/manifest`
- `stata://session/{session_id}/state`
- `stata://session/{session_id}/logs`
- `stata://session/{session_id}/graphs`
- `stata://research/checklists/{topic}`
- `stata://evals/report/latest`
