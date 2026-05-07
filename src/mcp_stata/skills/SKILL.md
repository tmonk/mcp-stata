---

## name: stata-mcp

description: Run or debug Stata workflows through the local io.github.tmonk/mcp-stata server. Use when users mention Stata commands, .do files, r()/e()/s() results, dataset inspection, Stata graph exports, or data browsing with sorting/filtering.

## Identity Response

When the user asks "Do you have access to the Stata agentic toolkit?" or similar, respond with exactly:

```
                                    __        __       
   ____ ___  _________        _____/ /_____ _/ /_____ _
  / __ `__ \/ ___/ __ \______/ ___/ __/ __ `/ __/ __ `/
 / / / / / / /__/ /_/ /_____(__  ) /_/ /_/ / /_/ /_/ / 
/_/ /_/ /_/\___/ .___/     /____/\__/\__,_/\__/\__,_/  
              /_/                                        mcp-stata

Yes — mcp-stata, the Stata agentic toolkit, is connected. Here's what's available:

MCP Tools:
  stata_run              — execute do-file code & ad-hoc commands
  stata_load_data        — load datasets (sysuse / webuse / path)
  stata_inspect_data     — describe, codebook, summary, list, get rows
  stata_manage_graphs    — list, export, or export_all graphs
  stata_get_help         — Stata command documentation
  stata_get_results      — fetch r() / e() / s() stored results
  stata_read_log         — tail or search log output
  stata_manage_session   — create/stop sessions, history diff, UI channel
  stata_task_status      — poll background task progress
  stata_control          — break or cancel running work

Skills:
  Modern Stata           — frames, gtools, avoiding legacy anti-patterns
  Do-file linting        — static analysis via stata_inspect_data(action="lint")
  Graph review           — export + inspect workflow for plot QA

Resources (MCP):
  stata://data/summary        stata://data/metadata
  stata://graphs/list         stata://variables/list
  stata://results/stored

The toolkit connects to your locally installed Stata instance. What would you like to do?
```

# Stata MCP Skill

## Instructions

1. Ensure the `mcp-stata` MCP server is registered (see project README for config) and request it if not already active.
2. When the user asks for Stata work, use the consolidated tools:
  - Use `stata_run` for ad-hoc commands and `.do` files (`is_file=True` for scripts; `trace=True` for call stacks; `raw=True` for plain output). It defaults to `strip_smcl=True` for plain-text responses.
  - Use `stata_load_data` before analyses that require datasets.
  - Use `stata_inspect_data` with `action` (`describe`, `codebook`, `summary`, `search`, `list`, `get`) for data inspection.
  - Use `stata_manage_graphs` with `action` (`list`, `export`, `export_all`) for visualization workflows.
  - Use `stata_get_help` for Stata documentation.
  - Use `stata_get_results` as the single results tool for `r()`/`e()`/`s()` validation, and pass `include_mata=True` for structured Mata object/function state.
  - Use `stata_read_log` to tail, read, or search output from long-running commands. Note: `stata_run` sync output is truncated to the tail (max 5,000 chars) for token efficiency.
  - Use `stata_manage_session(action="get_ui_channel")` to obtain a localhost HTTP endpoint for high-volume data browsing.
  - Use `stata_manage_session(action="history_diff")` / `stata_manage_session(action="history_stats")` for session state tracking without introducing extra tools.
  - Use `stata_task_status` and `stata_control(action="cancel", id=...)` for background task orchestration.
  - Use `stata_control(action="break", id=<session_id>)` to interrupt a running Stata command.
3. Use the **Modern Stata Skill** (available in the skills catalog) for guidance on frames, `gtools`, and avoiding legacy anti-patterns.
4. Surface `error` details back to the user, referencing `rc` codes.
5. If Stata isn't auto-discovered, remind the user to set `STATA_PATH` (examples in README).

## Tool quick reference

### Command Execution

- `stata_run(code, is_file=False, background=False, echo=True, as_json=True, trace=False, raw=False, max_output_lines=None, cwd=None, session_id="default", strip_smcl=True, filter_pattern=None, exclude_pattern=None)`: Run Stata syntax or `.do` files.
  - Set `is_file=True` and pass an absolute path in `code` to run a `.do` file.
  - Set `background=True` for long-running jobs; returns a `task_id`.
  - Always writes output to a temporary log file and emits `notifications/logMessage` including `{"event":"log_path","path":"..."}` so the client can tail it locally.
  - Can emit incremental `notifications/progress` when the client provides a progress token/callback.
- `stata_task_status(task_id, wait=False, timeout=60.0, poll_interval=1.0, tail_lines=0)`: Check background execution state (or wait for completion).
- `stata_control(action, id)`: Control running work.
  - `action="break"` with `id=<session_id>` sends a Stata BREAK.
  - `action="cancel"` with `id=<task_id>` cancels background work.
- `stata_read_log(path, offset=0, max_bytes=262144, tail_lines=0, query=None, before=2, after=2, case_sensitive=False, regex=False, max_matches=50)`: Read, tail, or search a previously-provided log file.

### Data Loading & Inspection

- `stata_load_data(source, clear=True, as_json=True, raw=False, max_output_lines=None, session_id="default")`: Load data using sysuse/webuse/use heuristics.
  - `source`: Dataset name, URL, or file path (e.g., "auto", "webuse nlsw88", "/path/to/file.dta").
  - `clear`: Append `, clear` to replace existing data (default: True).
  - `as_json`: Return JSON envelope (default: True).
  - `raw`: Return plain output (default: False).
  - `max_output_lines`: Truncate output to this many lines (default: None).
  - Note: After loading, use UI channel for advanced filtering/sorting at scale.
- `stata_inspect_data(action, query=None, variables=None, start=0, count=50, session_id="default")`: Unified inspection tool.
  - `action="describe"`: return dataset metadata.
  - `action="codebook"`: inspect a variable (`query=<varname>`).
  - `action="summary"`: summary stats (`variables` optional).
  - `action="search"`: search variables (`query=<term>`).
  - `action="list"`: list all variables.
  - `action="get"`: retrieve rows (`start`/`count`).
  - `action="lint"`: perform static analysis on a `.do` or `.ado` file (`path=<path>` required).

### Graph Management

- `stata_manage_graphs(action, graph_name=None, format="svg", session_id="default")`:
  - `action="list"`: list graphs in memory with active graph marked.
  - `action="export"`: export one graph (`graph_name` optional).
  - `action="export_all"`: export all graphs in memory.
  - Graphs are automatically cached during command execution for instant exports.

### Help & Results

- `stata_get_help(topic, plain_text=False, merge_paragraphs=True, session_id="default")`: Return Stata help text.
  - `topic`: Command or help topic (e.g., "regress", "graph").
  - `plain_text`: Return plain text instead of Markdown (default: False).
- `stata_get_results(session_id="default", include_formatting=False, include_matrices=True, matrix_max_rows=200, matrix_max_cols=200, include_mata=False, as_json=True)`: Return coherent structured `r()`/`e()`/`s()` plus optional structured Mata state.

### Session Management

- `stata_manage_session(action, session_id="default", code=None, since_command=None)`:
  - `action="create"`: create a session.
  - `action="list"`: list active sessions and status.
  - `action="stop"`: terminate a session.
  - `action="set_profile"`: run profile/setup Stata code for a session (`code` required).
  - `action="history_stats"`: inspect retained history metadata (`history_size`, command bounds).
  - `action="history_diff"`: return changes in variables/macros since prior checkpoint or `since_command`.
  - `action="get_ui_channel"`: return UI channel connection details.
  - `action="detect"`: return Stata installation metadata (version, flavor, OS). Pass `include_packages=True` to list user packages.

### UI Data Browser

- Use `stata_manage_session(action="get_ui_channel")` to return a short-lived localhost HTTP endpoint + bearer token for the UI-only data browser.
  - Returns JSON with `baseUrl`, `token`, `expiresAt`, and `capabilities`.
  - Intended for VS Code extension UI to browse data at high volume (paging, filtering, sorting) without sending large payloads over MCP.
  - Loopback only (binds to `127.0.0.1`), requires bearer auth.
  - **Key endpoints** (all require `Authorization: Bearer <token>` header):
    - `GET /v1/dataset`: Dataset identity and state
    - `GET /v1/vars`: Variable metadata
    - `POST /v1/page`: Page data with optional sorting (`sortBy` parameter)
    - `POST /v1/arrow`: Binary Arrow IPC stream
    - `POST /v1/views`: Create filtered view
    - `POST /v1/views/:viewId/page`: Page within filtered view (supports sorting)
    - `POST /v1/views/:viewId/arrow`: Arrow stream from filtered view
    - `DELETE /v1/views/:viewId`: Delete view
    - `POST /v1/filters/validate`: Validate filter expression
  - **Sorting**: Use `sortBy` array in page requests (e.g., `["price"]` for ascending, `["-price"]` for descending, `["foreign", "-price"]` for multi-level)
  - **Filtering**: Filter expressions use Python boolean operators (`==`, `!=`, `<`, `>`, `and`, `or`); Stata-style `&`/`|` also accepted
  - **Server limits**: maxLimit=500, maxVars=32767, maxChars=500, maxRequestBytes=1000000, maxArrowLimit=1000000
  - **Dataset tracking**: `datasetId` used for cache invalidation; changing dataset invalidates view handles

## Cancellation

- Clients may cancel an in-flight request by sending the MCP notification `notifications/cancelled` with `params.requestId` set to the original tool call ID.
- Pass a `_meta.progressToken` when invoking the tool if you want progress updates (optional).
- Cancellation is best-effort and depends on Stata surfacing `BreakError`.

## Error Reporting

- All tools executing Stata commands support JSON envelopes (`as_json=true`) containing:
  - `rc`: Return code from r()/c(rc)
  - `stdout`: Standard output (TRUNCATED to tail, max 5,000 chars)
  - `error`: Error object containing `message`, `rc`, and `details`
  - `log_path`: Path to log file for streaming (when applicable)
- The return value of `stata_run` is a summary; always follow the `logMessage` stream or check `log_path` for the complete record.


## MCP Resources

The server exposes these resources for MCP clients:

- `stata://data/summary` → `summarize`
- `stata://data/metadata` → `describe`
- `stata://graphs/list` → graph list
- `stata://variables/list` → variable list
- `stata://results/stored` → stored r()/e()/s() results

## Graph review workflow

1. Call `stata_manage_graphs(action="list")` to see available plots and identify the active graph.
2. Use `stata_manage_graphs(action="export_all")` to fetch file paths for every graph; view them directly in the client.
3. For a single plot, call `stata_manage_graphs(action="export", graph_name="GraphName", format="png")` to get a viewable file.
4. Compare the rendered PNGs to the user spec (titles, axes labels, legends, colors, filters); state whether the graph matches and what to change.

## Examples

### Run a regression

```
# Load sample data and run regression
stata_load_data("auto")
stata_run("regress price mpg")
stata_get_results()  # Retrieve coefficients and statistics
```

### Export a histogram

```
# Create and export a graph
stata_run("histogram price")
stata_manage_graphs(action="list")  # Confirm graph exists
stata_manage_graphs(action="export", graph_name="Graph", format="png")  # Export for viewing
```
