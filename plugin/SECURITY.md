# Security

`mcp-stata` executes commands against a local Stata installation. Treat it like a powerful local automation layer.

## Recommended safeguards

- Review destructive Stata commands before running them.
- Be careful with proprietary or confidential data in logs and exported graphs.
- Keep a human in the loop for package installation or major workflow changes.
- Prefer project-scoped installs when working on sensitive research projects.

## Sensitive surfaces

- local datasets,
- generated logs,
- exported graphs and tables,
- startup do-files and profile behavior,
- user-written Stata packages.

The default installer does not install Stata packages automatically.
