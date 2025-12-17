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
- **Verify results**: programmatically check stored results (`r()`, `e()`) for accurate validation.

## Prerequisites

- **Stata 17+** (required for `pystata` integration)
- **Python 3.11+** (recommended)
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

* `run_command(code, echo=True, as_json=True, trace=False, raw=False, max_output_lines=None)`: Execute Stata syntax. JSON envelope by default; `raw=True` returns plain stdout/stderr. Use `max_output_lines` to limit output.
* `load_data(source, clear=True, as_json=True, raw=False, max_output_lines=None)`: Heuristic loader (sysuse/webuse/use/path/URL) with JSON envelope unless `raw=True`. Supports output truncation.
* `get_data(start=0, count=50)`: View dataset rows (JSON response, capped to 500 rows).
* `describe()`: View dataset structure via Stata `describe`.
* `list_graphs()`: See available graphs in memory (JSON list with an `active` flag).
* `export_graph(graph_name=None, format="pdf")`: Export a graph to a file path (default PDF; use `format="png"` for PNG).
* `export_graphs_all()`: Export all in-memory graphs. Returns file paths by default.
* `get_help(topic, plain_text=False)`: Markdown-rendered Stata help by default; `plain_text=True` strips formatting.
* `codebook(variable, as_json=True, trace=False, raw=False, max_output_lines=None)`: Variable-level metadata (JSON envelope by default; supports `trace=True` and output truncation).
* `run_do_file(path, echo=True, as_json=True, trace=False, raw=False, max_output_lines=None)`: Execute a .do file with rich error capture (JSON by default). Supports output truncation.
* `get_stored_results()`: Get `r()` and `e()` scalars/macros as JSON.
* `get_variable_list()`: JSON list of variables and labels.

Resources exposed for MCP clients:

* `stata://data/summary` → `summarize`
* `stata://data/metadata` → `describe`
* `stata://graphs/list` → graph list (resource handler delegates to `list_graphs` tool)
* `stata://variables/list` → variable list (resource wrapper)
* `stata://results/stored` → stored r()/e() results

## License

This project is licensed under the GNU Affero General Public License v3.0 or later.
See the LICENSE file for the full text.

## Error reporting

- All tools that execute Stata commands support JSON envelopes (`as_json=true`) carrying:
  - `rc` (from r()/c(rc)), `stdout`, `stderr`, `message`, optional `line` (when Stata reports it), `command`, and a `snippet` excerpt of error output.
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