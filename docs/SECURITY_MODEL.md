# Security Model

`mcp-stata` is designed for local, researcher-controlled environments.

## Guardrails

- Path allowlisting for explicit dataset and do-file paths
- Protected-directory blocking for common credential locations such as `.ssh`, `.aws`, `.gnupg`, and `.netrc`
- Command risk classification for destructive, package-installing, file-writing, data-mutating, and external-URL commands
- `read_only=True` for workflows that must not mutate data or files

## Operational Guidance

- Keep the default stdio transport for local use unless you have a strong reason to expose another transport.
- Treat `allow_unsafe_paths=True` as an explicit override for trusted paths only.
- Use `stata_doctor` and `stata_project_reproducibility_report` to verify environment assumptions before large reruns.
