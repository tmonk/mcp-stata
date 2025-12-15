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
uvx --from mcp-stata mcp-stata
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
        "args": ["--from", "mcp-stata", "mcp-stata"]
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
        "args": ["--from", "mcp-stata", "mcp-stata"]
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
        "args": ["--from", "mcp-stata", "mcp-stata"]
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
        "args": ["--from", "mcp-stata", "mcp-stata"]
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
      "args": ["--from", "mcp-stata", "mcp-stata"],
    }
  }
}
```

VS Code documents `.vscode/mcp.json` and the `servers` schema, including `type` and `command`/`args`.

---

## Skills

- Skill file (for Claude/Codex): [skill/SKILL.md](skill/SKILL.md)

## Tools Available

* `run_command(code, raw=false)`: Execute Stata syntax. Returns a structured JSON envelope by default; set `raw=true` for plain stdout/stderr. `trace=true` temporarily enables `set trace on`.
* `load_data(source, clear=True, raw=false)`: Heuristic loader (sysuse/webuse/use/path/URL) with JSON envelope.
* `get_data(start, count)`: View dataset rows (JSON response, capped to 500 rows).
* `describe()`: View dataset structure.
* `codebook(variable, raw=false)`: Variable-level metadata (JSON envelope by default).
* `run_do_file(path, trace=false, raw=false)`: Execute a .do file with rich error capture (JSON by default).
* `export_graph(name, format="pdf")`: Export a graph to a file path (default PDF; use `format="png"` for PNG).
* `export_graphs_all()`: Export all in-memory graphs as base64-encoded PNGs (JSON response).
* `list_graphs()`: See available graphs in memory (JSON list with an `active` flag).
* `get_stored_results()`: Get `r()` and `e()` scalars/macros.
* `get_help(topic, plain_text=false)`: Returns Markdown-rendered Stata help (default). Use `plain_text=true` for stripped text. Falls back to the Stata online help URL if missing.
* `get_variable_list()`: JSON list of variables and labels.

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

Set `STATA_MCP_LOGLEVEL` (e.g., `DEBUG`, `INFO`) to control server logging. Logs include discovery details (edition/path) and command-init traces for easier troubleshooting.

## Development

To set up the development environment, synchronize dependencies using the following commands:

- `uv sync --no-install-project`: Installs the main dependencies listed in `pyproject.toml` without installing the project itself.
- `uv sync --extra dev --no-install-project`: Installs the main dependencies plus any additional development dependencies (such as testing or linting tools), again without installing the project itself.
