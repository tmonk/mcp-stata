import anyio
import asyncio
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from mcp.server.fastmcp import Context, FastMCP
import mcp.types as types
from .stata_client import StataClient
from .models import (
    DataResponse,
    GraphListResponse,
    VariablesResponse,
    GraphExportResponse,
)
import logging
import sys
import json
import os
import re
import uuid
from typing import Optional, Dict

from .ui_http import UIChannelManager


# Configure logging
logger = logging.getLogger("mcp_stata")

def setup_logging():
    # Configure logging to stderr with immediate flush for MCP transport
    log_level = os.getenv("MCP_STATA_LOGLEVEL", "DEBUG").upper()
    
    # Create a handler that flushes immediately
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(getattr(logging, log_level, logging.DEBUG))
    handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers = []
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level, logging.DEBUG))
    
    # Also configure the mcp_stata logger explicitly
    logger.setLevel(getattr(logging, log_level, logging.DEBUG))
    logger.handlers = []
    logger.addHandler(handler)
    logger.propagate = False

    try:
        _mcp_stata_version = version("mcp-stata")
    except PackageNotFoundError:
        _mcp_stata_version = "unknown"

    logger.info("=== mcp-stata server starting ===")
    logger.info("mcp-stata version: %s", _mcp_stata_version)
    logger.info("STATA_PATH env at startup: %s", os.getenv("STATA_PATH", "<not set>"))
    logger.info("LOG_LEVEL: %s", log_level)

# Initialize FastMCP
mcp = FastMCP("mcp_stata")
client = StataClient()
ui_channel = UIChannelManager(client)


@dataclass
class BackgroundTask:
    task_id: str
    kind: str
    task: asyncio.Task
    created_at: datetime
    log_path: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    done: bool = False


_background_tasks: Dict[str, BackgroundTask] = {}


def _register_task(task_info: BackgroundTask, max_tasks: int = 100) -> None:
    _background_tasks[task_info.task_id] = task_info
    if len(_background_tasks) <= max_tasks:
        return
    completed = [task for task in _background_tasks.values() if task.done]
    completed.sort(key=lambda item: item.created_at)
    for task in completed[: max(0, len(_background_tasks) - max_tasks)]:
        _background_tasks.pop(task.task_id, None)


def _format_command_result(result, raw: bool, as_json: bool) -> str:
    if raw:
        if result.success:
            return result.log_path or ""
        if result.error:
            msg = result.error.message
            if result.error.rc is not None:
                msg = f"{msg}\nrc={result.error.rc}"
            return msg
        return result.log_path or ""
    if as_json:
        return result.model_dump_json()
    return result.model_dump_json()


async def _wait_for_log_path(task_info: BackgroundTask) -> None:
    while task_info.log_path is None and not task_info.done:
        await anyio.sleep(0.01)


async def _notify_task_done(session: object | None, task_info: BackgroundTask, request_id: object | None) -> None:
    if session is None:
        return
    payload = {
        "event": "task_done",
        "task_id": task_info.task_id,
        "status": "done" if task_info.done else "unknown",
        "log_path": task_info.log_path,
        "error": task_info.error,
    }
    try:
        await session.send_log_message(level="info", data=json.dumps(payload), related_request_id=request_id)
    except Exception:
        return


@mcp.tool()
async def run_do_file_background(
    path: str,
    ctx: Context | None = None,
    echo: bool = True,
    as_json: bool = True,
    trace: bool = False,
    raw: bool = False,
    max_output_lines: int = None,
    cwd: str | None = None,
) -> str:
    """Run a Stata do-file in the background and return a task id.

    Notifications:
      - logMessage: {"event":"log_path","path":"..."}
      - logMessage: {"event":"task_done","task_id":"...","status":"done","log_path":"...","error":null}
    """
    session = ctx.request_context.session if ctx is not None else None
    request_id = ctx.request_id if ctx is not None else None
    task_id = uuid.uuid4().hex
    task_info = BackgroundTask(
        task_id=task_id,
        kind="do_file",
        task=None,
        created_at=datetime.utcnow(),
    )

    async def notify_log(text: str) -> None:
        if session is not None:
            await session.send_log_message(level="info", data=text, related_request_id=ctx.request_id)
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and payload.get("event") == "log_path":
                task_info.log_path = payload.get("path")
        except Exception:
            return

    progress_token = None
    if ctx is not None and ctx.request_context.meta is not None:
        progress_token = ctx.request_context.meta.progressToken

    async def notify_progress(progress: float, total: float | None, message: str | None) -> None:
        if session is None or progress_token is None:
            return
        await session.send_progress_notification(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
            related_request_id=ctx.request_id,
        )

    async def _run() -> None:
        try:
            result = await client.run_do_file_streaming(
                path,
                notify_log=notify_log,
                notify_progress=notify_progress if progress_token is not None else None,
                echo=echo,
                trace=trace,
                max_output_lines=max_output_lines,
                cwd=cwd,
            )
            ui_channel.notify_potential_dataset_change()
            task_info.result = _format_command_result(result, raw=raw, as_json=as_json)
            if result.error:
                task_info.error = result.error.message
        except Exception as exc:  # pragma: no cover - defensive
            task_info.error = str(exc)
        finally:
            task_info.done = True
            await _notify_task_done(session, task_info, request_id)

    task_info.task = asyncio.create_task(_run())
    _register_task(task_info)
    await _wait_for_log_path(task_info)
    return json.dumps({"task_id": task_id, "status": "started", "log_path": task_info.log_path})


@mcp.tool()
def get_task_status(task_id: str) -> str:
    """Return task status for background executions."""
    task_info = _background_tasks.get(task_id)
    if task_info is None:
        return json.dumps({"task_id": task_id, "status": "not_found"})
    return json.dumps({
        "task_id": task_id,
        "status": "done" if task_info.done else "running",
        "kind": task_info.kind,
        "created_at": task_info.created_at.isoformat(),
        "log_path": task_info.log_path,
        "error": task_info.error,
    })


@mcp.tool()
def get_task_result(task_id: str) -> str:
    """Return task result for background executions."""
    task_info = _background_tasks.get(task_id)
    if task_info is None:
        return json.dumps({"task_id": task_id, "status": "not_found"})
    if not task_info.done:
        return json.dumps({"task_id": task_id, "status": "running", "log_path": task_info.log_path})
    return json.dumps({
        "task_id": task_id,
        "status": "done",
        "log_path": task_info.log_path,
        "error": task_info.error,
        "result": task_info.result,
    })


@mcp.tool()
def cancel_task(task_id: str) -> str:
    """Request cancellation of a background task."""
    task_info = _background_tasks.get(task_id)
    if task_info is None:
        return json.dumps({"task_id": task_id, "status": "not_found"})
    if task_info.task and not task_info.task.done():
        task_info.task.cancel()
        return json.dumps({"task_id": task_id, "status": "cancelling"})
    return json.dumps({"task_id": task_id, "status": "done", "log_path": task_info.log_path})


@mcp.tool()
async def run_command_background(
    code: str,
    ctx: Context | None = None,
    echo: bool = True,
    as_json: bool = True,
    trace: bool = False,
    raw: bool = False,
    max_output_lines: int = None,
    cwd: str | None = None,
) -> str:
    """Run a Stata command in the background and return a task id.

    Notifications:
      - logMessage: {"event":"log_path","path":"..."}
      - logMessage: {"event":"task_done","task_id":"...","status":"done","log_path":"...","error":null}
    """
    session = ctx.request_context.session if ctx is not None else None
    request_id = ctx.request_id if ctx is not None else None
    task_id = uuid.uuid4().hex
    task_info = BackgroundTask(
        task_id=task_id,
        kind="command",
        task=None,
        created_at=datetime.utcnow(),
    )

    async def notify_log(text: str) -> None:
        if session is not None:
            await session.send_log_message(level="info", data=text, related_request_id=ctx.request_id)
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and payload.get("event") == "log_path":
                task_info.log_path = payload.get("path")
        except Exception:
            return

    progress_token = None
    if ctx is not None and ctx.request_context.meta is not None:
        progress_token = ctx.request_context.meta.progressToken

    async def notify_progress(progress: float, total: float | None, message: str | None) -> None:
        if session is None or progress_token is None:
            return
        await session.send_progress_notification(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
            related_request_id=ctx.request_id,
        )

    async def _run() -> None:
        try:
            result = await client.run_command_streaming(
                code,
                notify_log=notify_log,
                notify_progress=notify_progress if progress_token is not None else None,
                echo=echo,
                trace=trace,
                max_output_lines=max_output_lines,
                cwd=cwd,
            )
            ui_channel.notify_potential_dataset_change()
            task_info.result = _format_command_result(result, raw=raw, as_json=as_json)
            if result.error:
                task_info.error = result.error.message
        except Exception as exc:  # pragma: no cover - defensive
            task_info.error = str(exc)
        finally:
            task_info.done = True
            await _notify_task_done(session, task_info, request_id)

    task_info.task = asyncio.create_task(_run())
    _register_task(task_info)
    await _wait_for_log_path(task_info)
    return json.dumps({"task_id": task_id, "status": "started", "log_path": task_info.log_path})

@mcp.tool()
async def run_command(
    code: str,
    ctx: Context | None = None,
    echo: bool = True,
    as_json: bool = True,
    trace: bool = False,
    raw: bool = False,
    max_output_lines: int = None,
    cwd: str | None = None,
) -> str:
    """
    Executes Stata code.

    This is the primary tool for interacting with Stata.

    Stata output is written to a temporary log file on disk.
    The server emits a single `notifications/logMessage` event containing the log file path
    (JSON payload: {"event":"log_path","path":"..."}) so the client can tail it locally.
    If the client supplies a progress callback/token, progress updates may also be emitted
    via `notifications/progress`.

    Args:
        code: The Stata command(s) to execute (e.g., "sysuse auto", "regress price mpg", "summarize").
        ctx: FastMCP-injected request context (used to send MCP notifications). Optional for direct Python calls.
        echo: If True, the command itself is included in the output. Default is True.
        as_json: If True, returns a JSON envelope with rc/stdout/stderr/error.
        trace: If True, enables `set trace on` for deeper error diagnostics (automatically disabled after).
        raw: If True, return raw output/error message rather than a JSON envelope.
        max_output_lines: If set, truncates stdout to this many lines for token efficiency.
                         Useful for verbose commands (regress, codebook, etc.).
        Note: This tool always uses log-file streaming semantics; there is no non-streaming mode.
    """
    session = ctx.request_context.session if ctx is not None else None

    async def notify_log(text: str) -> None:
        if session is None:
            return
        await session.send_log_message(level="info", data=text, related_request_id=ctx.request_id)

    progress_token = None
    if ctx is not None and ctx.request_context.meta is not None:
        progress_token = ctx.request_context.meta.progressToken

    async def notify_progress(progress: float, total: float | None, message: str | None) -> None:
        if session is None or progress_token is None:
            return
        await session.send_progress_notification(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
            related_request_id=ctx.request_id,
        )

    async def _noop_log(_text: str) -> None:
        return

    result = await client.run_command_streaming(
        code,
        notify_log=notify_log if session is not None else _noop_log,
        notify_progress=notify_progress if progress_token is not None else None,
        echo=echo,
        trace=trace,
        max_output_lines=max_output_lines,
        cwd=cwd,
    )

    # Conservative invalidation: arbitrary Stata commands may change data.
    ui_channel.notify_potential_dataset_change()
    if raw:
        if result.success:
            return result.log_path or ""
        if result.error:
            msg = result.error.message
            if result.error.rc is not None:
                msg = f"{msg}\nrc={result.error.rc}"
            return msg
        return result.log_path or ""
    if as_json:
        return result.model_dump_json()


@mcp.tool()
def read_log(path: str, offset: int = 0, max_bytes: int = 65536) -> str:
    """Read a slice of a log file.

    Intended for clients that want to display a terminal-like view without pushing MBs of
    output through MCP log notifications.

    Args:
        path: Absolute path to the log file previously provided by the server.
        offset: Byte offset to start reading from.
        max_bytes: Maximum bytes to read.

    Returns a compact JSON string: {"path":..., "offset":..., "next_offset":..., "data":...}
    """
    try:
        if offset < 0:
            offset = 0
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(max_bytes)
            next_offset = f.tell()
        text = data.decode("utf-8", errors="replace")
        return json.dumps({"path": path, "offset": offset, "next_offset": next_offset, "data": text})
    except FileNotFoundError:
        return json.dumps({"path": path, "offset": offset, "next_offset": offset, "data": ""})
    except Exception as e:
        return json.dumps({"path": path, "offset": offset, "next_offset": offset, "data": f"ERROR: {e}"})


@mcp.tool()
def find_in_log(
    path: str,
    query: str,
    start_offset: int = 0,
    max_bytes: int = 5_000_000,
    before: int = 2,
    after: int = 2,
    case_sensitive: bool = False,
    regex: bool = False,
    max_matches: int = 50,
) -> str:
    """Find text within a log file and return context windows.

    Args:
        path: Absolute path to the log file previously provided by the server.
        query: Text or regex pattern to search for.
        start_offset: Byte offset to start searching from.
        max_bytes: Maximum bytes to read from the log.
        before: Number of context lines to include before each match.
        after: Number of context lines to include after each match.
        case_sensitive: If True, match case-sensitively.
        regex: If True, treat query as a regular expression.
        max_matches: Maximum number of matches to return.

    Returns a JSON string with matches and offsets:
        {"path":..., "query":..., "start_offset":..., "next_offset":..., "truncated":..., "matches":[...]}.
    """
    try:
        if start_offset < 0:
            start_offset = 0
        if max_bytes <= 0:
            return json.dumps({
                "path": path,
                "query": query,
                "start_offset": start_offset,
                "next_offset": start_offset,
                "truncated": False,
                "matches": [],
            })
        with open(path, "rb") as f:
            f.seek(start_offset)
            data = f.read(max_bytes)
            next_offset = f.tell()

        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()

        if regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(query, flags=flags)
            def is_match(line: str) -> bool:
                return pattern.search(line) is not None
        else:
            needle = query if case_sensitive else query.lower()
            def is_match(line: str) -> bool:
                haystack = line if case_sensitive else line.lower()
                return needle in haystack

        matches = []
        for idx, line in enumerate(lines):
            if not is_match(line):
                continue
            start_idx = max(0, idx - max(0, before))
            end_idx = min(len(lines), idx + max(0, after) + 1)
            context = lines[start_idx:end_idx]
            matches.append({
                "line_index": idx,
                "context_start": start_idx,
                "context_end": end_idx,
                "context": context,
            })
            if len(matches) >= max_matches:
                break

        truncated = len(matches) >= max_matches
        return json.dumps({
            "path": path,
            "query": query,
            "start_offset": start_offset,
            "next_offset": next_offset,
            "truncated": truncated,
            "matches": matches,
        })
    except FileNotFoundError:
        return json.dumps({
            "path": path,
            "query": query,
            "start_offset": start_offset,
            "next_offset": start_offset,
            "truncated": False,
            "matches": [],
        })
    except Exception as e:
        return json.dumps({
            "path": path,
            "query": query,
            "start_offset": start_offset,
            "next_offset": start_offset,
            "truncated": False,
            "matches": [],
            "error": f"ERROR: {e}",
        })


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
    return resp.model_dump_json()


@mcp.tool()
def get_ui_channel() -> str:
    """Return localhost HTTP endpoint + bearer token for the extension UI data plane."""
    info = ui_channel.get_channel()
    payload = {
        "baseUrl": info.base_url,
        "token": info.token,
        "expiresAt": info.expires_at,
        "capabilities": ui_channel.capabilities(),
    }
    return json.dumps(payload)

@mcp.tool()
def describe() -> str:
    """
    Returns variable descriptions, storage types, and labels (equivalent to Stata's `describe` command).

    Use this to understand the structure of the dataset, variable names, and their formats before running analysis.
    """
    result = client.run_command_structured("describe", echo=True)
    if result.success:
        return result.stdout
    if result.error:
        return result.error.message
    return ""

@mcp.tool()
def list_graphs() -> str:
    """
    Lists the names of all graphs currently stored in Stata's memory.

    Use this to see which graphs are available for export via `export_graph`. The
    response marks the active graph so the agent knows which one will export by
    default.
    """
    graphs = client.list_graphs_structured()
    return graphs.model_dump_json()

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
    return json.dumps(client.get_stored_results())

@mcp.tool()
def load_data(source: str, clear: bool = True, as_json: bool = True, raw: bool = False, max_output_lines: int = None) -> str:
    """
    Loads data using sysuse/webuse/use heuristics based on the source string.
    Automatically appends , clear unless clear=False.

    Args:
        source: Dataset source (e.g., "auto", "auto.dta", "/path/to/file.dta").
        clear: If True, clears data in memory before loading.
        as_json: If True, returns JSON envelope.
        raw: If True, returns raw output only.
        max_output_lines: If set, truncates stdout to this many lines for token efficiency.
    """
    result = client.load_data(source, clear=clear, max_output_lines=max_output_lines)
    ui_channel.notify_potential_dataset_change()
    if raw:
        return result.stdout if result.success else (result.error.message if result.error else result.stdout)
    return result.model_dump_json()

@mcp.tool()
def codebook(variable: str, as_json: bool = True, trace: bool = False, raw: bool = False, max_output_lines: int = None) -> str:
    """
    Returns codebook/summary for a specific variable.

    Args:
        variable: The variable name to analyze.
        as_json: If True, returns JSON envelope.
        trace: If True, enables trace mode.
        raw: If True, returns raw output only.
        max_output_lines: If set, truncates stdout to this many lines for token efficiency.
    """
    result = client.codebook(variable, trace=trace, max_output_lines=max_output_lines)
    if raw:
        return result.stdout if result.success else (result.error.message if result.error else result.stdout)
    return result.model_dump_json()

@mcp.tool()
async def run_do_file(
    path: str,
    ctx: Context | None = None,
    echo: bool = True,
    as_json: bool = True,
    trace: bool = False,
    raw: bool = False,
    max_output_lines: int = None,
    cwd: str | None = None,
) -> str:
    """
    Executes a .do file.

    Stata output is written to a temporary log file on disk.
    The server emits a single `notifications/logMessage` event containing the log file path
    (JSON payload: {"event":"log_path","path":"..."}) so the client can tail it locally.
    If the client supplies a progress callback/token, progress updates are emitted via
    `notifications/progress`.

    Args:
        path: Path to the .do file to execute.
        ctx: FastMCP-injected request context (used to send MCP notifications). Optional for direct Python calls.
        echo: If True, includes command in output.
        as_json: If True, returns JSON envelope.
        trace: If True, enables trace mode.
        raw: If True, returns raw output only.
        max_output_lines: If set, truncates stdout to this many lines for token efficiency.
        Note: This tool always uses log-file streaming semantics; there is no non-streaming mode.
    """
    session = ctx.request_context.session if ctx is not None else None

    async def notify_log(text: str) -> None:
        if session is None:
            return
        await session.send_log_message(level="info", data=text, related_request_id=ctx.request_id)

    progress_token = None
    if ctx is not None and ctx.request_context.meta is not None:
        progress_token = ctx.request_context.meta.progressToken

    async def notify_progress(progress: float, total: float | None, message: str | None) -> None:
        if session is None or progress_token is None:
            return
        await session.send_progress_notification(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
            related_request_id=ctx.request_id,
        )

    async def _noop_log(_text: str) -> None:
        return

    result = await client.run_do_file_streaming(
        path,
        notify_log=notify_log if session is not None else _noop_log,
        notify_progress=notify_progress if progress_token is not None else None,
        echo=echo,
        trace=trace,
        max_output_lines=max_output_lines,
        cwd=cwd,
    )

    ui_channel.notify_potential_dataset_change()

    if raw:
        if result.success:
            return result.log_path or ""
        if result.error:
            return result.error.message
        return result.log_path or ""
    return result.model_dump_json()

@mcp.resource("stata://data/summary")
def get_summary() -> str:
    """
    Returns the output of the `summarize` command for the dataset in memory.
    Provides descriptive statistics (obs, mean, std. dev, min, max) for all variables.
    """
    result = client.run_command_structured("summarize", echo=True)
    if result.success:
        return result.stdout
    if result.error:
        return result.error.message
    return ""

@mcp.resource("stata://data/metadata")
def get_metadata() -> str:
    """
    Returns the output of the `describe` command.
    Provides metadata about the dataset, including variable names, storage types, display formats, and labels.
    """
    result = client.run_command_structured("describe", echo=True)
    if result.success:
        return result.stdout
    if result.error:
        return result.error.message
    return ""

@mcp.resource("stata://graphs/list")
def list_graphs_resource() -> str:
    """Resource wrapper for the graph list (uses tool list_graphs)."""
    return list_graphs()

@mcp.tool()
def get_variable_list() -> str:
    """Returns JSON list of all variables."""
    variables = client.list_variables_structured()
    return variables.model_dump_json()

@mcp.resource("stata://variables/list")
def get_variable_list_resource() -> str:
    """Resource wrapper for the variable list."""
    return get_variable_list()

@mcp.resource("stata://results/stored")
def get_stored_results_resource() -> str:
    """Returns stored r() and e() results."""
    import json
    return json.dumps(client.get_stored_results())

@mcp.tool()
def export_graphs_all(use_base64: bool = False) -> str:
    """
    Exports all graphs in memory to file paths (default) or base64-encoded SVGs.

    Args:
        use_base64: If True, returns base64-encoded images (token-intensive).
                   If False (default), returns file paths to SVG files (token-efficient).
                   Use file paths unless you need to embed images directly.

    Returns a JSON envelope listing graph names and either file paths or base64 images.
    The agent can open SVG files directly to verify visuals (titles/labels/colors/legends).
    """
    exports = client.export_graphs_all(use_base64=use_base64)
    return exports.model_dump_json(exclude_none=False)

def main():
    if "--version" in sys.argv:
        try:
            from importlib.metadata import version
            print(version("mcp-stata"))
        except Exception:
            print("unknown")
        return

    setup_logging()
    
    # Initialize Stata here on the main thread to ensure any issues are logged early.
    # On Windows, this is critical for COM registration. On other platforms, it helps
    # catch license or installation errors before the first tool call.
    try:
        client.init()
    except BaseException as e:
        # Use sys.stderr.write and flush to ensure visibility before exit
        msg = f"\n{'='*60}\n[mcp_stata] FATAL: STATA INITIALIZATION FAILED\n{'='*60}\nError: {repr(e)}\n"
        sys.stderr.write(msg)
        if isinstance(e, SystemExit):
            sys.stderr.write(f"Stata triggered a SystemExit (code: {e.code}). This is usually a license error.\n")
        sys.stderr.write(f"{'='*60}\n\n")
        sys.stderr.flush()
        
        # We exit here because the user wants a clear failure when Stata cannot be loaded.
        sys.exit(1)

    mcp.run()

if __name__ == "__main__":
    main()