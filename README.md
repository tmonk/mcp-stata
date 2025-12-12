# Stata MCP Server

A [Model Context Protocol](https://github.com/modelcontextprotocol) (MCP) server that connects AI assistants to a local Stata installation.

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

### Option A: Run from a local checkout (recommended for development)

```bash
uv sync
```

### Option B: Run as a published tool with `uvx` (no cloning)

Once this project is published to PyPI, you can run it without cloning:

```bash
uvx --from stata-mcp stata-mcp
```

`uvx` is an alias for `uv tool run` and runs the tool in an isolated, cached environment.

> Tip: You can pin a version (example): `uvx --from stata-mcp==0.1.0 stata-mcp`

## Configuration

This server attempts to automatically discover your Stata installation (supporting standard paths and StataNow).

If auto-discovery fails, set the `STATA_PATH` environment variable to your Stata executable:

```bash
# macOS example
export STATA_PATH="/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"

# Windows example (cmd.exe)
set STATA_PATH="C:\Program Files\Stata18\StataMP-64.exe"
```

## Usage

### Running locally (from a clone)

```bash
uv run stata-mcp
```

## IDE Setup (MCP)

This MCP server uses the **stdio** transport (the IDE launches the process and communicates over stdin/stdout).

When using `uv` against a local checkout, we recommend starting the server with `uv run --directory ...` so `uv` runs in the folder containing your `pyproject.toml`. (`--directory` tells `uv` to change to that directory before executing.)

> **Important:** These configuration files are typically **strict JSON** (no `//` comments, no trailing commas).

---

### Claude Desktop

Open Claude Desktop → **Settings** → **Developer** → **Edit Config**.
Config file locations include:

* macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
* Windows: `%APPDATA%\Claude\claude_desktop_config.json`

#### Local checkout (uv)

```json
{
  "mcpServers": {
    "stata": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/stata-mcp", "stata-mcp"],
      "env": {
        "STATA_PATH": "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"
      }
    }
  }
}
```

#### Published tool (uvx)

```json
{
  "mcpServers": {
    "stata": {
      "command": "uvx",
      "args": ["--from", "stata-mcp", "stata-mcp"],
      "env": {
        "STATA_PATH": "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"
      }
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

#### Local checkout (uv)

```json
{
  "mcpServers": {
    "stata": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/stata-mcp", "stata-mcp"],
      "env": {
        "STATA_PATH": "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"
      }
    }
  }
}
```

#### Published tool (uvx)

```json
{
  "mcpServers": {
    "stata": {
      "command": "uvx",
      "args": ["--from", "stata-mcp", "stata-mcp"],
      "env": {
        "STATA_PATH": "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"
      }
    }
  }
}
```

---

### Windsurf

Windsurf supports MCP plugins and also allows manual editing of `mcp_config.json`. After adding/editing a server, use the UI’s refresh so it re-reads the config.

A common location is `~/.codeium/windsurf/mcp_config.json`.
#### Local checkout (uv)

```json
{
  "mcpServers": {
    "stata": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/stata-mcp", "stata-mcp"],
      "env": {
        "STATA_PATH": "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"
      }
    }
  }
}
```

#### Published tool (uvx)

```json
{
  "mcpServers": {
    "stata": {
      "command": "uvx",
      "args": ["--from", "stata-mcp", "stata-mcp"],
      "env": {
        "STATA_PATH": "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"
      }
    }
  }
}
```

---

### Google Antigravity

In Antigravity, MCP servers are managed from the MCP store/menu; you can open **Manage MCP Servers** and then **View raw config** to edit `mcp_config.json`.

#### Local checkout (uv)

```json
{
  "mcpServers": {
    "stata": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/stata-mcp", "stata-mcp"],
      "env": {
        "STATA_PATH": "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"
      }
    }
  }
}
```

#### Published tool (uvx)

```json
{
  "mcpServers": {
    "stata": {
      "command": "uvx",
      "args": ["--from", "stata-mcp", "stata-mcp"],
      "env": {
        "STATA_PATH": "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"
      }
    }
  }
}
```

---

### Visual Studio Code

VS Code supports MCP servers via a `.vscode/mcp.json` file. The top-level key is **`servers`** (not `mcpServers`).

Create `.vscode/mcp.json`:

#### Local checkout (uv)

```json
{
  "servers": {
    "stata": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/stata-mcp", "stata-mcp"],
      "env": {
        "STATA_PATH": "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"
      }
    }
  }
}
```

#### Published tool (uvx)

```json
{
  "servers": {
    "stata": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "stata-mcp", "stata-mcp"],
      "env": {
        "STATA_PATH": "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"
      }
    }
  }
}
```

VS Code documents `.vscode/mcp.json` and the `servers` schema, including `type` and `command`/`args`.

---

## Tools Available

* `run_command(code)`: Execute Stata syntax.
  - `as_json=true` returns a structured envelope with `rc`, `stdout`, `stderr`, and `error` details.
  - `trace=true` temporarily enables `set trace on` around the call for program-defined errors.
* `load_data(source, clear=True)`: Heuristic loader (sysuse/webuse/use/path/URL) with JSON envelope.
* `get_data(start, count)`: View dataset rows (JSON response).
* `describe()`: View dataset structure.
* `codebook(variable)`: Variable-level metadata (supports `as_json`).
* `run_do_file(path, trace=false, as_json=false)`: Execute a .do file with rich error capture.
* `export_graph(name)`: Export a graph as an image.
* `export_graphs_all()`: Export all in-memory graphs as base64-encoded PNGs (JSON response).
* `list_graphs()`: See available graphs in memory (JSON list with an `active` flag).
* `get_stored_results()`: Get `r()` and `e()` scalars/macros.
* `get_help(topic)`: Get help URL for a topic.
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