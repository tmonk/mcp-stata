---
name: stata-mcp
description: Run or debug Stata workflows through the local io.github.tmonk/mcp-stata server. Use when users mention Stata commands, .do files, r()/e() results, dataset inspection, or Stata graph exports.
---

# Stata MCP Skill

## Instructions
1. Ensure the `stata` MCP server is registered (see project README for config) and request it if not already active.
2. When the user asks for Stata work:
   - Use `run_command` for ad-hoc syntax (`trace=true` if they need call stacks).
   - Use `load_data` before analyses that require datasets.
   - Use `get_data`, `describe`, `codebook`, or `get_variable_list` to inspect data.
   - Use `run_do_file` for provided `.do` scripts.
   - Use `export_graph`/`export_graphs_all` for visualization requests.
   - Use `get_help` when the user wants Stata documentation.
   - Use `get_stored_results` to return `r()`/`e()` scalars/macros after commands for validation.
3. Surface `rc`/`stderr` info back to the user, referencing `r()`/`e()` codes.
4. If Stata isn’t auto-discovered, remind the user to set `STATA_PATH` (examples in README).

## Tool quick reference
- `run_command(code, trace, raw)`: run Stata syntax; enable trace when debugging.
- `load_data(source, clear)`: sysuse/webuse/use/path heuristic loader.
- `get_data(start, count)`: slice rows for inspection; capped for safety.
- `describe()`, `get_variable_list()`, `codebook(variable)`: structure and metadata.
- `run_do_file(path, trace)`: execute .do files with structured errors.
- `export_graph(name, format="png|pdf")`, `export_graphs_all()`, `list_graphs()`: graph listing and export (PNG for viewing).
- `get_help(topic, plain_text)`: Stata help (Markdown by default).
- `get_stored_results()`: fetch `r()`/`e()` results after a command.

## Graph review workflow
- Call `list_graphs()` to see available plots and the active graph.
- Use `export_graphs_all()` to fetch base64 PNGs for every graph; open them directly in the client.
- For a single plot, call `export_graph(name, format="png")` to get a viewable path.
- Compare the rendered PNGs to the user spec (titles, axes labels, legends, colors, filters); state whether the graph matches and what to change.

## Examples
- “Fit a regression of price on mpg in Stata” → load sample data (`sysuse auto`), call `run_command("regress price mpg")`, report coefficients.
- “Export that histogram” → confirm graph exists, call `export_graph(name="Graph", format="png")`, return the saved path.