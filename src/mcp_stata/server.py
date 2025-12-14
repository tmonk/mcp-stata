from mcp.server.fastmcp import FastMCP
import mcp.types as types
from .stata_client import StataClient
from .models import (
    DataResponse,
    GraphListResponse,
    VariablesResponse,
    GraphExportResponse,
)
import logging
import json
import os

LOG_LEVEL = os.getenv("STATA_MCP_LOGLEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

# Initialize FastMCP
mcp = FastMCP("stata")
client = StataClient()

@mcp.tool()
def run_command(code: str, echo: bool = True, as_json: bool = True, trace: bool = False, raw: bool = False) -> str:
    """
    Executes a specific Stata command.

    This is the primary tool for interacting with Stata. You can run any valid Stata syntax.
    
    Args:
        code: The detailed Stata command(s) to execute (e.g., "sysuse auto", "regress price mpg", "summarize").
        echo: If True, the command itself is included in the output. Default is True.
        as_json: If True, returns a JSON envelope with rc/stdout/stderr/error.
        trace: If True, enables `set trace on` for deeper error diagnostics (automatically disabled after).
    """
    result = client.run_command_structured(code, echo=echo, trace=trace)
    if raw:
        if result.success:
            return result.stdout
        if result.error:
            msg = result.error.message
            if result.error.rc is not None:
                msg = f"{msg}\nrc={result.error.rc}"
            return msg
        return result.stdout
    if as_json:
        return result.model_dump_json(indent=2)
    # Default structured string for compatibility when as_json is False but raw is also False
    return result.model_dump_json(indent=2)

@mcp.tool()
def get_data(start: int = 0, count: int = 50) -> str:
    """
    Returns a slice of the active dataset as a JSON-formatted list of dictionaries.

    Use this to inspect the actual data values in memory. Useful for checking data quality or content.
    
    Args:
        start: The zero-based index of the first observation to retrieve.
        count: The number of observations to retrieve. Defaults to 50.
    """
    data = client.get_data(start, count)
    resp = DataResponse(start=start, count=count, data=data)
    return resp.model_dump_json(indent=2)

@mcp.tool()
def describe() -> str:
    """
    Returns variable descriptions, storage types, and labels (equivalent to Stata's `describe` command).

    Use this to understand the structure of the dataset, variable names, and their formats before running analysis.
    """
    return client.run_command("describe")

@mcp.tool()
def list_graphs() -> str:
    """
    Lists the names of all graphs currently stored in Stata's memory.

    Use this to see which graphs are available for export via `export_graph`. The
    response marks the active graph so the agent knows which one will export by
    default.
    """
    graphs = client.list_graphs_structured()
    return graphs.model_dump_json(indent=2)

@mcp.tool()
def export_graph(graph_name: str = None, format: str = "pdf") -> str:
    """
    Exports a stored Stata graph to a file and returns its path.
    
    Args:
        graph_name: The name of the graph to export (as seen in `list_graphs`). 
                   If None, exports the currently active graph.
        format: Output format, defaults to "pdf". Supported: "pdf", "png". Use
                "png" to view the plot directly so the agent can visually check
                titles, labels, legends, colors, and other user requirements.
    """
    try:
        return client.export_graph(graph_name, format=format)
    except Exception as e:
        raise RuntimeError(f"Failed to export graph: {e}")

@mcp.tool()
def get_help(topic: str, plain_text: bool = False) -> str:
    """
    Returns the official Stata help text for a given command or topic.

    Args:
        topic: The command name or help topic (e.g., "regress", "graph", "options").
               Returns Markdown by default, or plain text when plain_text=True.
    """
    return client.get_help(topic, plain_text=plain_text)

@mcp.tool()
def get_stored_results() -> str:
    """
    Returns the current stored results (r-class and e-class scalars/macros) as a JSON-formatted string.

    Use this after running a command (like `summarize` or `regress`) to programmatically retrieve 
    specific values (e.g., means, coefficients, sample sizes) for validation or further calculation.
    """
    import json
    return json.dumps(client.get_stored_results(), indent=2)

@mcp.tool()
def load_data(source: str, clear: bool = True, as_json: bool = True, raw: bool = False) -> str:
    """
    Loads data using sysuse/webuse/use heuristics based on the source string.
    Automatically appends , clear unless clear=False.
    """
    result = client.load_data(source, clear=clear)
    if raw:
        return result.stdout if result.success else (result.error.message if result.error else result.stdout)
    return result.model_dump_json(indent=2) if as_json else result.model_dump_json(indent=2)

@mcp.tool()
def codebook(variable: str, as_json: bool = True, trace: bool = False, raw: bool = False) -> str:
    """
    Returns codebook/summary for a specific variable.
    """
    result = client.codebook(variable, trace=trace)
    if raw:
        return result.stdout if result.success else (result.error.message if result.error else result.stdout)
    return result.model_dump_json(indent=2) if as_json else result.model_dump_json(indent=2)

@mcp.tool()
def run_do_file(path: str, echo: bool = True, as_json: bool = True, trace: bool = False, raw: bool = False) -> str:
    """
    Executes a .do file with optional trace output and JSON envelope.
    """
    result = client.run_do_file(path, echo=echo, trace=trace)
    if raw:
        return result.stdout if result.success else (result.error.message if result.error else result.stdout)
    return result.model_dump_json(indent=2) if as_json else result.model_dump_json(indent=2)

@mcp.resource("stata://data/summary")
def get_summary() -> str:
    """
    Returns the output of the `summarize` command for the dataset in memory.
    Provides descriptive statistics (obs, mean, std. dev, min, max) for all variables.
    """
    return client.run_command("summarize")

@mcp.resource("stata://data/metadata")
def get_metadata() -> str:
    """
    Returns the output of the `describe` command.
    Provides metadata about the dataset, including variable names, storage types, display formats, and labels.
    """
    return client.run_command("describe")

@mcp.resource("stata://graphs/list")
def get_graph_list() -> str:
    """Returns list of active graphs."""
    return client.list_graphs_structured().model_dump_json(indent=2)

@mcp.tool()
def get_variable_list() -> str:
    """Returns JSON list of all variables."""
    variables = client.list_variables_structured()
    return variables.model_dump_json(indent=2)

@mcp.resource("stata://variables/list")
def get_variable_list_resource() -> str:
    """Resource wrapper for the variable list."""
    return get_variable_list()

@mcp.resource("stata://results/stored")
def get_stored_results_resource() -> str:
    """Returns stored r() and e() results."""
    import json
    return json.dumps(client.get_stored_results(), indent=2)

@mcp.tool()
def export_graphs_all() -> str:
    """
    Exports all graphs in memory to base64-encoded PNGs.
    Returns a JSON envelope listing graph names and images so the agent can open
    them directly and verify visuals (titles/labels/colors/legends) against the
    user's requested spec without an extra fetch.
    """
    exports = client.export_graphs_all()
    return exports.model_dump_json(indent=2)

def main():
    mcp.run()

if __name__ == "__main__":
    main()
