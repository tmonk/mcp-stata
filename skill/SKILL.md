---
name: stata-mcp
description: Run or debug Stata workflows through the local io.github.tmonk/mcp-stata server. Use when users mention Stata commands, .do files, r()/e() results, dataset inspection, or Stata graph exports.
---

# Stata MCP Skill

## Instructions
1. Ensure the `stata` MCP server is registered (see project README for config) and request it if not already active.
2. When the user asks for Stata work:
   - Use `run_command` for ad-hoc syntax (`trace=True` for call stacks, `raw=True` for plain output).
   - Use `load_data` before analyses that require datasets.
   - Use `get_data`, `describe`, `codebook`, or `get_variable_list` to inspect data.
   - Use `run_do_file` for provided `.do` scripts.
   - Use `export_graph`/`export_graphs_all` for visualization requests.
   - Use `get_help` when the user wants Stata documentation.
   - Use `get_stored_results` to return `r()`/`e()` scalars/macros after commands for validation.
3. Surface `rc`/`stderr` info back to the user, referencing `r()`/`e()` codes.
4. If Stata isn't auto-discovered, remind the user to set `STATA_PATH` (examples in README).

## Tool quick reference

### Command Execution
- `run_command(code, echo=True, as_json=True, trace=False, raw=False)`: Run Stata syntax.
  - `code`: The Stata command(s) to execute.
  - `echo`: Include the command itself in output (default: True).
  - `as_json`: Return JSON envelope with rc/stdout/stderr/error (default: True).
  - `trace`: Enable `set trace on` for deeper error diagnostics (default: False).
  - `raw`: Return plain stdout/error message instead of JSON (default: False).

- `run_do_file(path, echo=True, as_json=True, trace=False, raw=False)`: Execute .do files.
  - `path`: Path to the .do file.
  - `echo`: Include commands in output (default: True).
  - `as_json`: Return JSON envelope (default: True).
  - `trace`: Enable trace mode for debugging (default: False).
  - `raw`: Return plain output instead of JSON (default: False).

### Data Loading & Inspection
- `load_data(source, clear=True, as_json=True, raw=False)`: Load data using sysuse/webuse/use heuristics.
  - `source`: Dataset name, URL, or file path (e.g., "auto", "webuse nlsw88", "/path/to/file.dta").
  - `clear`: Append `, clear` to replace existing data (default: True).
  - `as_json`: Return JSON envelope (default: True).
  - `raw`: Return plain output (default: False).

- `get_data(start=0, count=50)`: Retrieve a slice of the active dataset as JSON.
  - `start`: Zero-based index of first observation (default: 0).
  - `count`: Number of observations to retrieve (default: 50, max: 500).

- `describe()`: Return variable descriptions, storage types, and labels.

- `get_variable_list()`: Return JSON list of all variables with names, labels, and types.

- `codebook(variable, as_json=True, trace=False, raw=False)`: Return codebook/summary for a specific variable.
  - `variable`: Variable name to describe.
  - `as_json`: Return JSON envelope (default: True).
  - `trace`: Enable trace mode (default: False).
  - `raw`: Return plain output (default: False).

### Graph Management
- `list_graphs()`: List all graphs in Stata's memory with active graph marked.

- `export_graph(graph_name=None, format="pdf")`: Export a stored graph to file.
  - `graph_name`: Name of graph to export (from `list_graphs`); if None, exports active graph.
  - `format`: Output format—"pdf" (default) or "png". Use "png" to view plots directly.

- `export_graphs_all()`: Export all graphs as base64-encoded PNGs for direct viewing.

### Help & Results
- `get_help(topic, plain_text=False)`: Return Stata help text.
  - `topic`: Command or help topic (e.g., "regress", "graph").
  - `plain_text`: Return plain text instead of Markdown (default: False).

- `get_stored_results()`: Return current `r()` and `e()` results as JSON after a command.

## Graph review workflow
1. Call `list_graphs()` to see available plots and identify the active graph.
2. Use `export_graphs_all()` to fetch base64 PNGs for every graph; view them directly in the client.
3. For a single plot, call `export_graph(graph_name="GraphName", format="png")` to get a viewable file.
4. Compare the rendered PNGs to the user spec (titles, axes labels, legends, colors, filters); state whether the graph matches and what to change.

## Examples

### Run a regression
```
# Load sample data and run regression
load_data("auto")
run_command("regress price mpg")
get_stored_results()  # Retrieve coefficients and statistics
```

### Export a histogram
```
# Create and export a graph
run_command("histogram price")
list_graphs()  # Confirm graph exists
export_graph(graph_name="Graph", format="png")  # Export for viewing
```

### Debug a do-file
```
run_do_file("/path/to/analysis.do", trace=True)
```

### Inspect data structure
```
load_data("nlsw88", clear=True)
describe()
get_variable_list()
codebook("wage")
get_data(start=0, count=10)
```