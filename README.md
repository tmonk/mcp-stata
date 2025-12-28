# Stata MCP Server

<a href="https://cursor.com/en-US/install-mcp?name=mcp-stata&config=eyJjb21tYW5kIjoidXZ4IC0tZnJvbSBtY3Atc3RhdGEgbWNwLXN0YXRhIn0%3D"><img src="https://cursor.com/deeplink/mcp-install-dark.svg" alt="Install MCP Server" height="20"></a>&nbsp;
<a href="https://pypi.org/project/mcp-stata/"><img src="https://img.shields.io/pypi/v/mcp-stata?style=flat&color=black" alt="PyPI - Version" height="20"></a>

A [Model Context Protocol](https://github.com/modelcontextprotocol) (MCP) server that connects AI agents to a local Stata installation.

> If you'd like a fully integrated VS Code extension to run Stata code without leaving your IDE, and also allow AI agent interaction, check out my other project: [<img src="https://raw.githubusercontent.com/tmonk/stata-workbench/refs/heads/main/img/icon.png" height="12px"> Stata Workbench](https://github.com/tmonk/stata-workbench/).

Built by <a href="https://tdmonk.com">Thomas Monk</a>, London School of Economics.
<!-- mcp-name: io.github.tmonk/mcp-stata -->

This server enables LLMs to:
- **Execute Stata code**: run any Stata command (e.g. `sysuse auto`, `regress price mpg`).
- **Inspect data**: retrieve dataset summaries and variable codebooks.
- **Export graphics**: generate and view Stata graphs (histograms, scatterplots).
- **Streaming graph caching**: automatically cache graphs during command execution for instant exports.
- **Verify results**: programmatically check stored results (`r()`, `e()`) for accurate validation.

## Prerequisites

- **Stata 17+** (required for `pystata` integration)
- **Python 3.12+** (required)
- **uv** (recommended for install/run)

## Installation

### Run as a published tool with `uvx`

```bash
uvx --refresh --from mcp-stata@latest mcp-stata
```

`uvx` is an alias for `uv tool run` and runs the tool in an isolated, cached environment.

## Configuration

This server attempts to automatically discover your Stata installation (supporting standard paths and StataNow).

If auto-discovery fails, set the `STATA_PATH` environment variable to your Stata executable:

```bash
# macOS example
export STATA_PATH="/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"

# Windows example (cmd.exe)
set STATA_PATH="C:\Program Files\Stata18\StataMP-64.exe"
```

If you prefer, add `STATA_PATH` to your MCP config's `env` for any IDE shown below. It's optional and only needed when discovery cannot find Stata.

Optional `env` example (add inside your MCP server entry):

```json
"env": {
  "STATA_PATH": "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"
}
```

## IDE Setup (MCP)

This MCP server uses the **stdio** transport (the IDE launches the process and communicates over stdin/stdout).

---

### Claude Desktop

Open Claude Desktop → **Settings** → **Developer** → **Edit Config**.
Config file locations include:

* macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
* Windows: `%APPDATA%\Claude\claude_desktop_config.json`

#### Published tool (uvx)

```json
{
  "mcpServers": {
    "mcp-stata": {
      "command": "uvx",
        "args": [
        "--refresh",
        "--from",
        "mcp-stata@latest",
        "mcp-stata"
      ]
    }
  }
}
```

After editing, fully quit and restart Claude Desktop to reload MCP servers.

---

### Cursor

Cursor supports MCP config at:

* Global: `~/.cursor/mcp.json`
* Project: `.cursor/mcp.json`

#### Published tool (uvx)

```json
{
  "mcpServers": {
    "mcp-stata": {
      "command": "uvx",
       "args": [
        "--refresh",
        "--from",
        "mcp-stata@latest",
        "mcp-stata"
      ]
    }
  }
}
```

---

### Windsurf

Windsurf supports MCP plugins and also allows manual editing of `mcp_config.json`. After adding/editing a server, use the UI’s refresh so it re-reads the config.

A common location is `~/.codeium/windsurf/mcp_config.json`.
#### Published tool (uvx)

```json
{
  "mcpServers": {
    "mcp-stata": {
      "command": "uvx",
        "args": [
        "--refresh",
        "--from",
        "mcp-stata@latest",
        "mcp-stata"
      ]
    }
  }
}
```

---

### Google Antigravity

In Antigravity, MCP servers are managed from the MCP store/menu; you can open **Manage MCP Servers** and then **View raw config** to edit `mcp_config.json`.

#### Published tool (uvx)

```json
{
  "mcpServers": {
    "mcp-stata": {
      "command": "uvx",
        "args": [
        "--refresh",
        "--from",
        "mcp-stata@latest",
        "mcp-stata"
      ]
    }
  }
}
```

---

### Visual Studio Code

VS Code supports MCP servers via a `.vscode/mcp.json` file. The top-level key is **`servers`** (not `mcpServers`).

Create `.vscode/mcp.json`:

#### Published tool (uvx)

```json
{
  "servers": {
    "mcp-stata": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--refresh",
        "--from",
        "mcp-stata@latest",
        "mcp-stata"
      ]
    }
  }
}
```

VS Code documents `.vscode/mcp.json` and the `servers` schema, including `type` and `command`/`args`.

---

## Skills

- Skill file (for Claude/Codex): [skill/SKILL.md](skill/SKILL.md)

## Tools Available (from server.py)

* `run_command(code, echo=True, as_json=True, trace=False, raw=False, max_output_lines=None)`: Execute Stata syntax.
  - Always writes output to a temporary log file and emits a single `notifications/logMessage` containing `{"event":"log_path","path":"..."}` so the client can tail it locally.
  - May emit `notifications/progress` when the client provides a progress token/callback.
* `read_log(path, offset=0, max_bytes=65536)`: Read a slice of a previously-provided log file (JSON: `path`, `offset`, `next_offset`, `data`).
* `load_data(source, clear=True, as_json=True, raw=False, max_output_lines=None)`: Heuristic loader (sysuse/webuse/use/path/URL) with JSON envelope unless `raw=True`. Supports output truncation.
* `get_data(start=0, count=50)`: View dataset rows (JSON response, capped to 500 rows).
* `get_ui_channel()`: Return a short-lived localhost HTTP endpoint + bearer token for the UI-only data browser.
* `describe()`: View dataset structure via Stata `describe`.
* `list_graphs()`: See available graphs in memory (JSON list with an `active` flag).
* `export_graph(graph_name=None, format="pdf")`: Export a graph to a file path (default PDF; use `format="png"` for PNG).
* `export_graphs_all()`: Export all in-memory graphs. Returns file paths by default.
* `get_help(topic, plain_text=False)`: Markdown-rendered Stata help by default; `plain_text=True` strips formatting.
* `codebook(variable, as_json=True, trace=False, raw=False, max_output_lines=None)`: Variable-level metadata (JSON envelope by default; supports `trace=True` and output truncation).
* `run_do_file(path, echo=True, as_json=True, trace=False, raw=False, max_output_lines=None)`: Execute a .do file.
  - Always writes output to a temporary log file and emits a single `notifications/logMessage` containing `{"event":"log_path","path":"..."}` so the client can tail it locally.
  - Emits incremental `notifications/progress` when the client provides a progress token/callback.
* `get_stored_results()`: Get `r()` and `e()` scalars/macros as JSON.
* `get_variable_list()`: JSON list of variables and labels.

### Cancellation

- Clients may cancel an in-flight request by sending the MCP notification `notifications/cancelled` with `params.requestId` set to the original tool call ID.
- Client guidance:
  1. Pass a `_meta.progressToken` when invoking the tool if you want progress updates (optional).
  2. If you need to cancel, send `notifications/cancelled` with the same requestId. You may also stop tailing the log file path once you receive cancellation confirmation (the tool call will return an error indicating cancellation).
  3. Be prepared for partial output in the log file; cancellation is best-effort and depends on Stata surfacing `BreakError`.

Resources exposed for MCP clients:

* `stata://data/summary` → `summarize`
* `stata://data/metadata` → `describe`
* `stata://graphs/list` → graph list (resource handler delegates to `list_graphs` tool)
* `stata://variables/list` → variable list (resource wrapper)
* `stata://results/stored` → stored r()/e() results

## UI-only Data Browser (Local HTTP API)

This server also hosts a **localhost-only HTTP API** intended for a VS Code extension UI to browse data at high volume (paging, filtering) without sending large payloads over MCP.

Important properties:

- **Loopback only**: binds to `127.0.0.1`.
- **Bearer auth**: every request requires an `Authorization: Bearer <token>` header.
- **Short-lived tokens**: clients should call `get_ui_channel()` to obtain a fresh token as needed.
- **No Stata dataset mutation** for browsing/filtering:
  - No generated variables.
  - Paging uses `sfi.Data.get`.
  - Filtering is evaluated in Python over chunked reads.

### Discovery via MCP (`get_ui_channel`)

Call the MCP tool `get_ui_channel()` and parse the JSON:

```json
{
  "baseUrl": "http://127.0.0.1:53741",
  "token": "...",
  "expiresAt": 1730000000,
  "capabilities": {
    "dataBrowser": true,
    "filtering": true,
    "sorting": true,
    "arrowStream": true
  }
}
```

Server-enforced limits (current defaults):

- **maxLimit**: 500
- **maxVars**: 32,767
- **maxChars**: 500
- **maxRequestBytes**: 1,000,000
- **maxArrowLimit**: 1,000,000 (specific to `/v1/arrow`)

### Endpoints

All endpoints are under `baseUrl` and require the bearer token.

- `GET /v1/dataset`
  - Returns dataset identity and basic state (`id`, `frame`, `n`, `k`).
- `GET /v1/vars`
  - Returns variable metadata (`name`, `type`, `label`, `format`).
- `POST /v1/page`
  - Returns a page of data for selected variables.
- `POST /v1/arrow`
  - Returns a binary Arrow IPC stream (same input as `/v1/page`).
- `POST /v1/views`
  - Creates a server-side filtered view (handle-based filtering).
- `POST /v1/views/:viewId/page`
  - Pages within a filtered view.
- `POST /v1/views/:viewId/arrow`
  - Returns a binary Arrow IPC stream from a filtered view.
- `DELETE /v1/views/:viewId`
  - Deletes a view handle.
- `POST /v1/filters/validate`
  - Validates a filter expression.

### Paging request example

```bash
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"datasetId":"...","frame":"default","offset":0,"limit":50,"vars":["price","mpg"],"includeObsNo":true,"maxChars":200}' \
  "$BASE_URL/v1/page"
```

#### Sorting

The `/v1/page` and `/v1/views/:viewId/page` endpoints support sorting via the optional `sortBy` parameter:

```bash
# Sort by price ascending
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"datasetId":"...","offset":0,"limit":50,"vars":["price","mpg"],"sortBy":["price"]}' \
  "$BASE_URL/v1/page"

# Sort by price descending
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"datasetId":"...","offset":0,"limit":50,"vars":["price","mpg"],"sortBy":["-price"]}' \
  "$BASE_URL/v1/page"

# Multi-variable sort: foreign ascending, then price descending
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"datasetId":"...","offset":0,"limit":50,"vars":["foreign","price","mpg"],"sortBy":["foreign","-price"]}' \
  "$BASE_URL/v1/page"
```

**Sort specification format:**
- `sortBy` is an array of strings (variable names with optional prefix)
- No prefix or `+` prefix = ascending order (e.g., `"price"` or `"+price"`)
- `-` prefix = descending order (e.g., `"-price"`)
- Multiple variables are supported for multi-level sorting
- Uses Stata's `gsort` command internally

**Sorting with filtered views:**
- Sorting is fully supported with filtered views
- The sort is applied to the entire dataset, then filtered indices are re-computed
- Example: Filter for `price < 5000`, then sort descending by price

```bash
# Create a filtered view
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"datasetId":"...","frame":"default","filterExpr":"price < 5000"}' \
  "$BASE_URL/v1/views"
# Returns: {"view": {"id": "view_abc123", "filteredN": 37}}

# Get sorted page from filtered view
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"offset":0,"limit":50,"vars":["price","mpg"],"sortBy":["-price"]}' \
  "$BASE_URL/v1/views/view_abc123/page"
```

Notes:

- `datasetId` is used for cache invalidation. If the dataset changes due to running Stata commands, the server will report a new dataset id and view handles become invalid.
- Filter expressions are evaluated in Python using values read from Stata via `sfi.Data.get`. Use boolean operators like `==`, `!=`, `<`, `>`, and `and`/`or` (Stata-style `&`/`|` are also accepted).
- Sorting modifies the dataset order in memory using `gsort`. When combined with views, the filtered indices are automatically re-computed after sorting.

## License

This project is licensed under the GNU Affero General Public License v3.0 or later.
See the LICENSE file for the full text.

## Error reporting

- All tools that execute Stata commands support JSON envelopes (`as_json=true`) carrying:
  - `rc` (from r()/c(rc)), `stdout`, `stderr`, `message`, optional `line` (when Stata reports it), `command`, optional `log_path` (for log-file streaming), and a `snippet` excerpt of error output.
- Stata-specific cues are preserved:
  - `r(XXX)` codes are parsed when present in output.
  - “Red text” is captured via stderr where available.
  - `trace=true` adds `set trace on` around the command/do-file to surface program-defined errors; the trace is turned off afterward.

## Logging

Set `MCP_STATA_LOGLEVEL` (e.g., `DEBUG`, `INFO`) to control server logging. Logs include discovery details (edition/path) and command-init traces for easier troubleshooting.

## Development & Contributing

For detailed information on building, testing, and contributing to this project, see [CONTRIBUTING.md](CONTRIBUTING.md).

Quick setup:

```bash
# Install dependencies
uv sync --extra dev --no-install-project

# Run tests (requires Stata)
pytest

# Run tests without Stata
pytest -v -m "not requires_stata"

# Build the package
python -m build
```

[![MCP Badge](https://lobehub.com/badge/mcp/tmonk-mcp-stata)](https://lobehub.com/mcp/tmonk-mcp-stata)
[![Tests](https://github.com/tmonk/mcp-stata/actions/workflows/build-test.yml/badge.svg)](https://github.com/tmonk/mcp-stata/actions/workflows/build-test.yml)