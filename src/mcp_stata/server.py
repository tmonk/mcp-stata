from __future__ import annotations
import anyio
import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.utilities import logging as fastmcp_logging
import mcp.types as types
from .stata_client import StataClient
from .models import (
    ErrorEnvelope,
    CommandResponse,
    DataResponse,
    GraphListResponse,
    VariableInfo,
    VariablesResponse,
    GraphInfo,
    GraphExport,
    GraphExportResponse,
    SessionInfo,
    SessionListResponse,
)
from .sessions import SessionManager
import logging
import sys
import json
import os
import multiprocessing
import re
import traceback
import uuid
from functools import wraps
from typing import Optional, Dict
import threading
import time

from .ui_http import UIChannelManager


# Configure logging
logger = logging.getLogger("mcp-stata")
payload_logger = logging.getLogger("mcp-stata.payloads")
_LOGGING_CONFIGURED = False

def get_server_version() -> str:
    """Determine the server version from package metadata or fallback."""
    try:
        return version("mcp-stata")
    except PackageNotFoundError:
        # If not installed, try to find version in pyproject.toml near this file
        try:
            # We are in src/mcp_stata/server.py, pyproject.toml is at ../../pyproject.toml
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            pyproject_path = os.path.join(base_dir, "pyproject.toml")
            if os.path.exists(pyproject_path):
                with open(pyproject_path, "r") as f:
                    content = f.read()
                    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
                    if match:
                        return match.group(1)
        except Exception:
            pass
        return "unknown"

SERVER_VERSION = get_server_version()

def setup_logging():
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    _LOGGING_CONFIGURED = True
    log_level = os.getenv("MCP_STATA_LOGLEVEL", "DEBUG").upper()
    fmt = logging.Formatter("[mcp-stata] [%(name)s] %(levelname)s: %(message)s")
    app_handler = logging.StreamHandler(sys.stderr)
    app_handler.setLevel(getattr(logging, log_level, logging.DEBUG))
    app_handler.setFormatter(fmt)

    mcp_handler = logging.StreamHandler(sys.stderr)
    mcp_handler.setLevel(getattr(logging, log_level, logging.DEBUG))
    mcp_handler.setFormatter(fmt)

    payload_handler = logging.StreamHandler(sys.stderr)
    payload_handler.setLevel(getattr(logging, log_level, logging.DEBUG))
    payload_handler.setFormatter(fmt)

    root_logger = logging.getLogger()
    root_logger.handlers = []
    root_logger.setLevel(logging.WARNING)

    for name, item in logging.root.manager.loggerDict.items():
        if not isinstance(item, logging.Logger):
            continue
        item.handlers = []
        item.propagate = False
        if item.level == logging.NOTSET:
            item.setLevel(getattr(logging, log_level, logging.DEBUG))

    logger.handlers = [app_handler]
    logger.propagate = False

    payload_logger.handlers = [payload_handler]
    payload_logger.propagate = False

    mcp_logger = logging.getLogger("mcp.server")
    mcp_logger.handlers = [mcp_handler]
    mcp_logger.propagate = False
    mcp_logger.setLevel(getattr(logging, log_level, logging.DEBUG))

    mcp_lowlevel = logging.getLogger("mcp.server.lowlevel.server")
    mcp_lowlevel.handlers = [mcp_handler]
    mcp_lowlevel.propagate = False
    mcp_lowlevel.setLevel(getattr(logging, log_level, logging.DEBUG))

    mcp_root = logging.getLogger("mcp")
    mcp_root.handlers = [mcp_handler]
    mcp_root.propagate = False
    mcp_root.setLevel(getattr(logging, log_level, logging.DEBUG))
    if logger.level == logging.NOTSET:
        logger.setLevel(getattr(logging, log_level, logging.DEBUG))

    logger.info("server starting")
    logger.info("version: %s", SERVER_VERSION)
    logger.info("STATA_PATH env at startup: %s", os.getenv("STATA_PATH", "<not set>"))
    logger.info("LOG_LEVEL: %s", log_level)



# Initialize FastMCP
mcp = FastMCP("mcp_stata")
# Set version on the underlying server to expose it in InitializeResult
mcp._mcp_server.version = SERVER_VERSION

session_manager = SessionManager()

class StataClientProxy:
    """Proxy for StataClient that routes calls to a StataSession (via worker process)."""
    def __init__(self, session_id: str = "default"):
        self.session_id = session_id

    def _call_sync(self, method: str, args: dict[str, Any]) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        async def _run():
            session = await session_manager.get_or_create_session(self.session_id)
            return await session.call(method, args)

        if loop and loop.is_running():
            # If we're in a thread different from the loop's thread
            # (which is true for UI HTTP handler threads)
            import threading
            if threading.current_thread() != threading.main_thread(): # Simplified check
                future = asyncio.run_coroutine_threadsafe(_run(), loop)
                return future.result()
            else:
                # If we're on the main thread but in a loop, we can't block.
                # This case shouldn't happen for UIChannelManager but might for tests.
                # For tests, we'll try anyio.from_thread.run if available or just run it.
                return anyio.from_thread.run(_run)
        else:
            return asyncio.run(_run())

    def get_dataset_state(self) -> dict[str, Any]:
        return self._call_sync("get_dataset_state", {})
    
    def get_stata_missing_threshold(self) -> float:
        return self._call_sync("get_stata_missing_threshold", {})

    def get_arrow_stream(self, **kwargs) -> bytes:
        return self._call_sync("get_arrow_stream", kwargs)

    def list_variables_rich(self) -> list[dict[str, Any]]:
        return self._call_sync("list_variables_rich", {})

    def compute_view_indices(self, filter_expr: str) -> list[int]:
        return self._call_sync("compute_view_indices", {"filter_expr": filter_expr})

    def validate_filter_expr(self, filter_expr: str):
        return self._call_sync("validate_filter_expr", {"filter_expr": filter_expr})

    def get_page(self, **kwargs):
        return self._call_sync("get_page", kwargs)

client = StataClientProxy()
ui_channel = None

def _log_tool_call(tool_name: str, ctx: Context | None = None) -> None:
    request_id = None
    if ctx is not None:
        request_id = getattr(ctx, "request_id", None)
    logger.info("MCP tool call: %s request_id=%s", tool_name, request_id)

def _should_stream_smcl_chunk(text: str, request_id: object | None) -> bool:
    if request_id is None:
        return True
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and payload.get("event"):
            return True
    except Exception:
        pass
    log_path = _request_log_paths.get(str(request_id))
    if log_path and log_path in _read_log_paths:
        return False
    return True


def _attach_task_id(ctx: Context | None, task_id: str) -> None:
    if ctx is None:
        return
    meta = ctx.request_context.meta
    if meta is None:
        meta = types.RequestParams.Meta()
        ctx.request_context.meta = meta
    try:
        setattr(meta, "task_id", task_id)
    except Exception:
        logger.debug("Unable to attach task_id to request meta", exc_info=True)


def _extract_ctx(args: tuple[object, ...], kwargs: dict[str, object]) -> Context | None:
    ctx = kwargs.get("ctx")
    if isinstance(ctx, Context):
        return ctx
    for arg in args:
        if isinstance(arg, Context):
            return arg
    return None


def log_call(func):
    """Decorator to log tool and resource calls."""
    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def async_inner(*args, **kwargs):
            ctx = _extract_ctx(args, kwargs)
            _log_tool_call(func.__name__, ctx)
            return await func(*args, **kwargs)
        return async_inner
    else:
        @wraps(func)
        def sync_inner(*args, **kwargs):
            ctx = _extract_ctx(args, kwargs)
            _log_tool_call(func.__name__, ctx)
            return func(*args, **kwargs)
        return sync_inner


@mcp.tool()
@log_call
async def stata_manage_session(
    action: str,
    session_id: str = "default",
    code: Optional[str] = None,
) -> str:
    """Manage Stata sessions (create, stop, list, profile, UI channel).
    
    This tool allows for orchestration of multiple Stata sessions, including their
    lifecycle management and configuration.
    
    Args:
        action: The management action to perform:
            - "create": Initializes a new Stata session.
            - "stop": Terminates an existing Stata session.
            - "list": Returns a JSON list of all active sessions.
            - "set_profile": Executes initialization code for a session.
            - "get_ui_channel": Retrieves connection details for the UI proxy.
        session_id: Unique identifier for the Stata session (defaults to "default").
        code: Stata code to execute when using the "set_profile" action.
        
    Returns:
        A JSON string containing the status of the action or the requested data.
    """
    _log_tool_call("stata_manage_session")
    if action == "create":
        await session_manager.get_or_create_session(session_id)
        return json.dumps({"status": "created", "session_id": session_id})
    elif action == "stop":
        await session_manager.stop_session(session_id)
        return json.dumps({"status": "stopped", "session_id": session_id})
    elif action == "list":
        sessions = session_manager.list_sessions()
        return SessionListResponse(sessions=sessions).model_dump_json()
    elif action == "set_profile":
        stata_session = await session_manager.get_or_create_session(session_id)
        await stata_session.set_profile(code)
        return json.dumps({"status": "profile_set", "session_id": session_id})
    elif action == "get_ui_channel":
        _ensure_ui_channel()
        if ui_channel is None:
            return json.dumps({"error": "UI channel not initialized"})
        info = ui_channel.get_channel()
        return json.dumps({
            "baseUrl": info.base_url,
            "token": info.token,
            "expiresAt": info.expires_at,
            "capabilities": ui_channel.capabilities(),
            "sessionId": session_id,
        })
    else:
        return json.dumps({"error": f"Invalid action: {action}"})


@mcp.tool()
@log_call
async def stata_load_data(
    source: str,
    clear: bool = True,
    as_json: bool = True,
    raw: bool = False,
    max_output_lines: int | None = None,
    session_id: str = "default",
) -> str:
    """Loads a dataset into a Stata session.
    
    Supports loading local .dta files or using Stata's built-in 'sysuse' and 'webuse' 
    commands. This tool ensures that the dataset is properly initialized for use 
    in subsequent analysis.
    
    Args:
        source: Path to the dataset file or a valid Stata sysuse/webuse name.
        clear: If True (default), clears any existing data in memory before loading.
        as_json: If True, returns a structured JSON response envelope.
        raw: If True, returns only the raw Stata output or error message.
        max_output_lines: Optional limit on the number of output lines to return.
        session_id: The ID of the Stata session to load data into.
        
    Returns:
        A JSON string (if as_json is True) or raw text containing the result of the load operation.
    """
    _log_tool_call("stata_load_data")
    session = await session_manager.get_or_create_session(session_id)
    result_dict = await session.call("load_data", {"source": source, "options": {"clear": clear, "max_output_lines": max_output_lines}})
    result = CommandResponse.model_validate(result_dict)
    if raw:
        return result.stdout if result.success else (result.error.message if result.error else result.stdout)
    return result.model_dump_json()


async def _noop_log(_text: str) -> None:
    return

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
_request_log_paths: Dict[str, str] = {}
_read_log_paths: set[str] = set()
_read_log_offsets: Dict[str, int] = {}
_STDOUT_FILTER_INSTALLED = False


def _install_stdout_filter() -> None:
    """
    Redirect process stdout to a pipe and forward only JSON-RPC lines to the
    original stdout. Any non-JSON output (e.g., Stata noise) is sent to stderr.
    """
    global _STDOUT_FILTER_INSTALLED
    if _STDOUT_FILTER_INSTALLED:
        return
    _STDOUT_FILTER_INSTALLED = True

    try:
        # Flush any pending output before redirecting.
        try:
            sys.stdout.flush()
        except Exception:
            pass

        original_stdout_fd = os.dup(1)
        read_fd, write_fd = os.pipe()
        os.dup2(write_fd, 1)
        os.close(write_fd)

        def _forward_stdout() -> None:
            buffer = b""
            while True:
                try:
                    chunk = os.read(read_fd, 4096)
                except Exception:
                    break
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line_with_nl = line + b"\n"
                    stripped = line.lstrip()
                    if stripped:
                        try:
                            payload = json.loads(stripped)
                            if isinstance(payload, dict) and payload.get("jsonrpc"):
                                os.write(original_stdout_fd, line_with_nl)
                            elif isinstance(payload, list) and any(
                                isinstance(item, dict) and item.get("jsonrpc") for item in payload
                            ):
                                os.write(original_stdout_fd, line_with_nl)
                            else:
                                os.write(2, line_with_nl)
                        except Exception:
                            os.write(2, line_with_nl)
            if buffer:
                stripped = buffer.lstrip()
                if stripped:
                    try:
                        payload = json.loads(stripped)
                        if isinstance(payload, dict) and payload.get("jsonrpc"):
                            os.write(original_stdout_fd, buffer)
                        elif isinstance(payload, list) and any(
                            isinstance(item, dict) and item.get("jsonrpc") for item in payload
                        ):
                            os.write(original_stdout_fd, buffer)
                        else:
                            os.write(2, buffer)
                    except Exception:
                        os.write(2, buffer)

            try:
                os.close(read_fd)
            except Exception:
                pass

        t = threading.Thread(target=_forward_stdout, name="mcp-stdout-filter", daemon=True)
        t.start()
    except Exception:
        _STDOUT_FILTER_INSTALLED = False


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
    
    # Note: we used to clear result.stdout here for token efficiency,
    # but that conflicts with requirements and breaks E2E tests that 
    # expect results in the return value.
    
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


def _debug_notification(kind: str, payload: object, request_id: object | None = None) -> None:
    try:
        serialized = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    except Exception:
        serialized = str(payload)
    payload_logger.info("MCP notify %s request_id=%s payload=%s", kind, request_id, serialized)


async def _notify_tool_error(ctx: Context | None, tool_name: str, exc: Exception) -> None:
    if ctx is None:
        return
    session = ctx.request_context.session
    if session is None:
        return
    task_id = None
    meta = ctx.request_context.meta
    if meta is not None:
        task_id = getattr(meta, "task_id", None)
    payload = {
        "event": "tool_error",
        "tool": tool_name,
        "error": str(exc),
        "traceback": traceback.format_exc(),
    }
    if task_id is not None:
        payload["task_id"] = task_id
    try:
        await session.send_log_message(
            level="error",
            data=json.dumps(payload),
            related_request_id=ctx.request_id,
        )
    except Exception:
        logger.exception("Failed to emit tool_error notification for %s", tool_name)








def _tail_file(path: str, lines: int) -> str | None:
    """Read the last N lines of a file."""
    if not path or not os.path.exists(path) or lines <= 0:
        return None
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            # Read at most 100kb or enough for requested lines
            read_size = min(size, max(102400, lines * 500))
            f.seek(max(0, size - read_size))
            content = f.read().decode("utf-8", errors="replace")
            split_lines = content.splitlines()
            return "\n".join(split_lines[-lines:])
    except Exception:
        return None

@mcp.tool()
@log_call
async def stata_task_status(
    task_id: str,
    wait: bool = False,
    timeout: float = 60.0,
    poll_interval: float = 1.0,
    tail_lines: int = 0,
) -> str:
    """Return task status for background executions.
    
    Provides detailed information about the state of a background task initiated 
    via `stata_run` with `background=True`. Supports optional blocking wait for 
    task completion.
    
    Args:
        task_id: The unique identifier of the background task to query.
        wait: If True, the call will block until the task finishes or the timeout is reached.
        timeout: Maximum duration (in seconds) to wait if `wait` is True (defaults to 60.0).
        poll_interval: Delay between checks (in seconds) when waiting for completion.
        tail_lines: If > 0, includes the last N lines of the task's execution log.
        
    Returns:
        A JSON string containing task details: status (started, running, done, error, 
        not_found), timestamps, log path, and the final result if completed.
    """
    _log_tool_call("stata_task_status")
    start_time = time.time()
    while True:
        task_info = _background_tasks.get(task_id)
        if task_info is None:
            return json.dumps({"task_id": task_id, "status": "not_found"})

        if task_info.done or not wait or (time.time() - start_time >= timeout):
            res = {
                "task_id": task_id,
                "status": "done" if task_info.done else "running",
                "kind": task_info.kind,
                "created_at": task_info.created_at.isoformat(),
                "log_path": task_info.log_path,
                "error": task_info.error,
                "result": task_info.result if task_info.done else None
            }
            if tail_lines > 0:
                res["tail"] = _tail_file(task_info.log_path, tail_lines)
            if not task_info.done and wait and (time.time() - start_time >= timeout):
                res["status"] = "timeout"
                res["error"] = f"Task did not complete within {timeout} seconds."
            return json.dumps(res)

        await asyncio.sleep(poll_interval)


@mcp.tool()
@log_call
async def stata_control(
    action: str,
    id: str,
) -> str:
    """Interrupt a session or cancel a background task.
    
    Allows for immediate control over running operations, either by sending a 
    break signal to an active Stata session or by cancelling a queued background task.
    
    Args:
        action: The control action to perform:
            - "break": Sends a BREAK signal to the specified Stata session.
            - "cancel": Terminates the execution of a background task.
        id: Either the `session_id` (for "break") or the `task_id` (for "cancel").
        
    Returns:
        A JSON string indicating the result of the control operation.
    """
    _log_tool_call("stata_control")
    if action == "break":
        try:
            session = session_manager.get_session(id)
            await session.send_break()
            return json.dumps({"status": "break_sent", "session_id": id})
        except Exception as e:
            return json.dumps({"error": str(e), "session_id": id})
    elif action == "cancel":
        task_info = _background_tasks.get(id)
        if task_info is None:
            return json.dumps({"task_id": id, "status": "not_found"})
        if task_info.task and not task_info.task.done():
            task_info.task.cancel()
            return json.dumps({"task_id": id, "status": "cancelling"})
        return json.dumps({"task_id": id, "status": "done", "log_path": task_info.log_path})
    else:
        return json.dumps({"error": f"Invalid action: {action}"})


@mcp.tool()
@log_call
async def stata_run(
    code: str,
    is_file: bool = False,
    background: bool = False,
    ctx: Context | None = None,
    echo: bool = True,
    as_json: bool = True,
    trace: bool = False,
    raw: bool = False,
    max_output_lines: int = None,
    cwd: str | None = None,
    session_id: str = "default",
    strip_smcl: bool = True,
    filter_pattern: Optional[str] = None,
    exclude_pattern: Optional[str] = None,
) -> str:
    """Executes Stata code or a .do file.

    This is the primary tool for interacting with Stata. It supports both 
    synchronous execution and background processing for long-running scripts.

    Stata output is captured in real-time and written to a temporary log file.
    The server emits `notifications/logMessage` events as output is generated.
    If `background=True`, the tool returns a `task_id` immediately, and the 
    actual execution continues in a separate process.

    Args:
        code: The Stata command string or the absolute path to a .do file.
        is_file: If True, the `code` parameter is treated as a path to a script file.
        background: If True, runs the operation in the background.
        ctx: FastMCP-injected request context for session and notification routing.
        echo: If True, includes the original command in the captured output.
        as_json: If True, returns a structured JSON response envelope.
        trace: If True, enables Stata trace mode for debugging.
        raw: If True, returns only the raw text output or error message.
        max_output_lines: Optional limit for the number of lines returned in synchronous mode.
        cwd: Optional working directory for the Stata process during execution.
        session_id: The ID of the Stata session to use (defaults to "default").
        strip_smcl: If True, removes Stata SMCL tags from the output for readability.
        filter_pattern: Optional regex to include only matching lines in the output.
        exclude_pattern: Optional regex to omit matching lines from the output.
        
    Returns:
        For sync calls: The execution output (JSON or raw text).
        For background calls: A JSON string containing the `task_id` and initial status.
    """
    session = getattr(getattr(ctx, "request_context", None), "session", None) if ctx is not None else None
    request_id = ctx.request_id if ctx is not None else None
    task_id = uuid.uuid4().hex
    _attach_task_id(ctx, task_id)
    
    task_info = BackgroundTask(
        task_id=task_id,
        kind="do_file" if is_file else "command",
        task=None,
        created_at=datetime.now(timezone.utc),
    )

    async def notify_log(text: str) -> None:
        if session is not None:
            if not _should_stream_smcl_chunk(text, ctx.request_id):
                return
            
            try:
                # Try to see if it's already structured JSON
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "event" in parsed:
                    if background and "task_id" not in parsed:
                        parsed["task_id"] = task_id
                    payload_to_send = json.dumps(parsed)
                else:
                    raise ValueError("Not an event")
            except Exception:
                # Wrap raw output in JSON event if in background or just forward
                if background:
                    payload_to_send = json.dumps({
                        "event": "output",
                        "text": text,
                        "task_id": task_id
                    }, ensure_ascii=False)
                else:
                    payload_to_send = text

            _debug_notification("logMessage", payload_to_send, ctx.request_id)
            try:
                await session.send_log_message(level="info", data=payload_to_send, related_request_id=ctx.request_id)
            except Exception as e:
                logger.warning("Failed to send logMessage notification: %s", e)

        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and payload.get("event") == "log_path":
                task_info.log_path = payload.get("path")
                if ctx.request_id is not None and task_info.log_path:
                    _request_log_paths[str(ctx.request_id)] = task_info.log_path
        except Exception:
            pass

    progress_token = None
    if ctx is not None and getattr(ctx, "request_context", None) is not None and getattr(ctx.request_context, "meta", None) is not None:
        progress_token = getattr(ctx.request_context.meta, "progressToken", None)

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

    async def _run_logic() -> CommandResponse:
        stata_session = await session_manager.get_or_create_session(session_id)
        method = "run_do_file" if is_file else "run_command"
        params = {
            "path" if is_file else "code": code,
            "strip_smcl": strip_smcl,
            "filter_pattern": filter_pattern,
            "exclude_pattern": exclude_pattern,
            "options": {
                "echo": echo,
                "trace": trace,
                "max_output_lines": max_output_lines,
                "cwd": cwd,
                "emit_graph_ready": True,
                "graph_ready_task_id": task_id if background else request_id,
                "graph_ready_format": "svg",
            }
        }
        
        result_dict = await stata_session.call(
            method,
            params,
            notify_log=notify_log if session is not None else _noop_log,
            notify_progress=notify_progress if progress_token is not None else None,
        )
        return CommandResponse.model_validate(result_dict)

    async def _run_task() -> None:
        try:
            result = await _run_logic()
            if not task_info.log_path and result.log_path:
                task_info.log_path = result.log_path
            if result.error:
                task_info.error = result.error.message
            task_info.result = _format_command_result(result, raw=raw, as_json=as_json)
            _ensure_ui_channel()
            if ui_channel:
                ui_channel.notify_potential_dataset_change(session_id)
        except asyncio.CancelledError:
            task_info.error = "Operation cancelled"
            raise
        except Exception as exc:
            task_info.error = str(exc)
        finally:
            task_info.done = True
            if background:
                await _notify_task_done(session, task_info, request_id)

    if background:
        if session is None:
            # Fallback if no session/context available for background task tracking
            # but usually background tools are called via MCP
            await _run_task()
            task_info.task = None
        else:
            task_info.task = asyncio.create_task(_run_task())
        _register_task(task_info)
        await _wait_for_log_path(task_info)
        return json.dumps({
            "task_id": task_id, 
            "status": "started", 
            "log_path": task_info.log_path
        })
    else:
        # Sync execution
        result = await _run_logic()
        _ensure_ui_channel()
        if ui_channel:
            ui_channel.notify_potential_dataset_change(session_id)
        return _format_command_result(result, raw=raw, as_json=as_json)


def _read_log_logic(path: str, offset: int = 0, max_bytes: int = 65536) -> str:
    try:
        if path:
            _read_log_paths.add(path)
        if offset < 0:
            offset = 0
        if path:
            last_offset = _read_log_offsets.get(path, 0)
            if offset < last_offset:
                offset = last_offset
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(max_bytes)
            next_offset = f.tell()
        if path:
            _read_log_offsets[path] = next_offset
        text = data.decode("utf-8", errors="replace")
        return json.dumps({"path": path, "offset": offset, "next_offset": next_offset, "data": text})
    except FileNotFoundError:
        return json.dumps({"path": path, "offset": offset, "next_offset": offset, "data": ""})
    except Exception as e:
        return json.dumps({"path": path, "offset": offset, "next_offset": offset, "data": f"ERROR: {e}"})


def _find_in_log_logic(
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
    try:
        if start_offset < 0:
            start_offset = 0
        if max_bytes <= 0:
            return json.dumps({
                "path": path, "query": query, "start_offset": start_offset,
                "next_offset": start_offset, "truncated": False, "matches": []
            })
        
        with open(path, "rb") as f:
            f.seek(start_offset)
            data = f.read(max_bytes)
            next_offset = f.tell()
        
        content = data.decode("utf-8", errors="replace")
        lines = content.splitlines()
        
        matches = []
        flags = 0 if case_sensitive else re.IGNORECASE
        
        for i, line in enumerate(lines):
            if regex:
                matched = re.search(query, line, flags)
            else:
                if case_sensitive:
                    matched = query in line
                else:
                    matched = query.lower() in line.lower()
            
            if matched:
                start_idx = max(0, i - before)
                end_idx = min(len(lines), i + after + 1)
                context = lines[start_idx:end_idx]
                matches.append({
                    "line": i + 1,
                    "content": line,
                    "context": context,
                })
                if len(matches) >= max_matches:
                    break
                    
        return json.dumps({
            "path": path,
            "query": query,
            "start_offset": start_offset,
            "next_offset": next_offset,
            "truncated": next_offset < os.path.getsize(path) if os.path.exists(path) else False,
            "matches": matches,
        })
    except Exception as e:
        return json.dumps({
            "path": path, "query": query, "start_offset": start_offset,
            "next_offset": start_offset, "truncated": False, "matches": [],
            "error": f"ERROR: {e}"
        })


@mcp.tool()
@log_call
def stata_read_log(
    path: str,
    offset: int = 0,
    max_bytes: int = 262144,
    tail_lines: int = 0,
    query: Optional[str] = None,
    before: int = 2,
    after: int = 2,
    case_sensitive: bool = False,
    regex: bool = False,
    max_matches: int = 50,
) -> str:
    """Read or search Stata log files.
    
    Provides low-level access to execution logs. Supports reading specific byte 
    ranges, tailing the end of logs, and searching for patterns with context lines.
    
    Args:
        path: Absolute path to the log file on disk.
        offset: Starting byte position for the read operation.
        max_bytes: Maximum number of bytes to read from the log (defaults to 256kb).
        tail_lines: If > 0, returns the last N lines of the log, overriding offset.
        query: Search string or regular expression to find within the log file.
        before: Number of lines before a match to include as context.
        after: Number of lines after a match to include as context.
        case_sensitive: If True, performs a case-sensitive search.
        regex: If True, treats the `query` as a regular expression.
        max_matches: Limit on the number of search results returned.
        
    Returns:
        A JSON string containing the read data, current offset, and any search matches.
    """
    _log_tool_call("stata_read_log")
    if query:
        return _find_in_log_logic(path, query, offset, max_bytes, before, after, case_sensitive, regex, max_matches)
    elif tail_lines > 0:
        tail = _tail_file(path, tail_lines)
        return json.dumps({"path": path, "data": tail or ""})
    else:
        return _read_log_logic(path, offset, max_bytes)


def _ensure_ui_channel():
    global ui_channel
    if ui_channel is None:
        try:
            from .ui_http import UIChannelManager
            # Pass the default client proxy. UIChannelManager will create 
            # session-specific proxies as needed.
            ui_channel = UIChannelManager(client)
        except Exception:
            logger.exception("Failed to initialize UI channel")


@mcp.tool()
@log_call
async def stata_inspect_data(
    action: str,
    query: Optional[str] = None,
    variables: Optional[list[str]] = None,
    start: int = 0,
    count: int = 50,
    session_id: str = "default",
) -> str:
    """Inspect the active dataset (describe, codebook, summarize, search, get data).
    
    Comprehensive tool for exploring the structure and content of the current 
    Stata dataset. Supports metadata inspection, summary statistics, and 
    variable searching.
    
    Args:
        action: The inspection action to perform:
            - "describe": Returns dataset structure and variable types.
            - "codebook": Detailed description of a specific variable's contents.
            - "summary": Descriptive statistics (mean, sd, etc.) for variables.
            - "search": Finds variables matching a name or label pattern.
            - "list": Returns a structured list of all variables in the dataset.
            - "get": Retrieves raw data observations from the dataset.
        query: Search term for the "search" action or variable name for "codebook".
        variables: Optional list of variables to include in the "summary" action.
        start: 0-indexed starting observation for the "get" action.
        count: Number of observations to retrieve for the "get" action.
        session_id: The ID of the Stata session to inspect.
        
    Returns:
        A JSON string or formatted text containing the requested inspection data.
    """
    _log_tool_call("stata_inspect_data")
    session = await session_manager.get_or_create_session(session_id)
    if action == "describe":
        result_dict = await session.call("run_command_structured", {"code": "describe", "options": {"echo": True}})
        result = CommandResponse.model_validate(result_dict)
        return result.stdout if result.success else (result.error.message if result.error else "")
    elif action == "codebook":
        result_dict = await session.call("codebook", {"variable": query, "options": {}})
        result = CommandResponse.model_validate(result_dict)
        return result.model_dump_json()
    elif action == "summary":
        summary_data = await session.call("get_data_summary", {"variables": variables})
        return json.dumps(summary_data)
    elif action == "search":
        variables_dict = await session.call("find_variables", {"query": query})
        variables_resp = VariablesResponse.model_validate(variables_dict)
        return variables_resp.model_dump_json()
    elif action == "list":
        variables_dict = await session.call("list_variables_structured", {})
        variables_resp = VariablesResponse.model_validate(variables_dict)
        return variables_resp.model_dump_json()
    elif action == "get":
        data = await session.call("get_data", {"start": start, "count": count})
        resp = DataResponse(start=start, count=count, data=data)
        return resp.model_dump_json()
    else:
        return json.dumps({"error": f"Invalid action: {action}"})

@mcp.tool()
@log_call
async def stata_manage_graphs(
    action: str,
    graph_name: Optional[str] = None,
    format: str = "svg",
    session_id: str = "default",
) -> str:
    """Manage Stata graphs (list, export).
    
    Enables interaction with Stata's graph memory, allowing for listing open 
    figures and exporting them to various file formats on disk.
    
    Args:
        action: The graph management action:
            - "list": Returns a JSON list of all graphs currently in memory.
            - "export": Saves a specific graph to a file.
            - "export_all": Exports all graphs in memory to files.
        graph_name: The name of the specific graph to export (used with "export").
        format: The file format for export (svg, pdf, png). Defaults to "svg".
        session_id: The ID of the Stata session to manage graphs from.
        
    Returns:
        A JSON string containing the list of graphs or export confirmation details.
    """
    _log_tool_call("stata_manage_graphs")
    session = await session_manager.get_or_create_session(session_id)
    if action == "list":
        graphs_dict = await session.call("list_graphs", {})
        graphs = GraphListResponse.model_validate(graphs_dict)
        return graphs.model_dump_json()
    elif action == "export":
        try:
            return await session.call("export_graph", {"graph_name": graph_name, "format": format})
        except Exception as e:
            raise RuntimeError(f"[mcp-stata] Failed to export graph: {e}")
    elif action == "export_all":
        exports_dict = await session.call("export_graphs_all", {})
        exports = GraphExportResponse.model_validate(exports_dict)
        return exports.model_dump_json(exclude_none=False)
    else:
        return json.dumps({"error": f"Invalid action: {action}"})

@mcp.tool()
@log_call
async def stata_inspect_results(session_id: str = "default") -> str:
    """Returns all scalars and macros currently stored in r(), e(), and s()."""
    _log_tool_call("stata_inspect_results")
    session = await session_manager.get_or_create_session(session_id)
    results = await session.call("get_stored_results", {})
    return json.dumps(results)

@mcp.tool()
@log_call
async def stata_get_help(topic: str, plain_text: bool = False, merge_paragraphs: bool = True, session_id: str = "default") -> str:
    """Returns help for a Stata command.
    
    Args:
        topic: The command or topic to get help for.
        plain_text: If True, returns plain text instead of Markdown.
        merge_paragraphs: If True, merges fixed-width split paragraphs.
        session_id: The ID of the Stata session.
    """
    _log_tool_call("stata_get_help")
    session = await session_manager.get_or_create_session(session_id)
    return await session.call("get_help", {"topic": topic, "plain_text": plain_text, "merge_paragraphs": merge_paragraphs})

@mcp.resource("stata://data/summary")
async def get_summary() -> str:
    """Returns output of summarize."""
    session = await session_manager.get_or_create_session("default")
    result_dict = await session.call("run_command_structured", {"code": "summarize", "options": {"echo": True}})
    
    result = CommandResponse.model_validate(result_dict)
    return result.stdout if result.success else (result.error.message if result.error else "")

@mcp.resource("stata://data/metadata")
async def get_metadata() -> str:
    """Returns output of describe."""
    session = await session_manager.get_or_create_session("default")
    result_dict = await session.call("run_command_structured", {"code": "describe", "options": {"echo": True}})
    
    result = CommandResponse.model_validate(result_dict)
    return result.stdout if result.success else (result.error.message if result.error else "")

@mcp.resource("stata://graphs/list")
@log_call
async def list_graphs_resource() -> str:
    """Resource wrapper for the graph list."""
    return await stata_manage_graphs(action="list", session_id="default")

@mcp.resource("stata://variables/list")
async def get_variable_list_resource() -> str:
    """Resource wrapper for the variable list."""
    return await stata_inspect_data(action="list", session_id="default")

@mcp.resource("stata://results/stored")
async def get_stored_results_resource() -> str:
    """Returns stored r() and e() results."""
    return await stata_inspect_results(session_id="default")

def main():
    if "--version" in sys.argv:
        print(SERVER_VERSION)
        return

    # Fix for macOS environments where sys.executable might be a shim that calls 'realpath'.
    # On some macOS versions (pre-Monterey) or minimal environments, 'realpath' is missing,
    # causing shims (like those from uv or pyenv) to fail.
    if sys.platform == "darwin":
        try:
            real_py = os.path.realpath(sys.executable)
            if real_py != sys.executable:
                multiprocessing.set_executable(real_py)
        except Exception:
            pass

    # Filter non-JSON output off stdout to keep stdio transport clean.
    _install_stdout_filter()

    setup_logging()
    
    # Initialize UI channel with default session proxy logic if needed
    # (Simplified for now, UI might only show default session)
    global ui_channel
    
    async def init_sessions():
        await session_manager.start()

    asyncio.run(init_sessions())

    mcp.run()

if __name__ == "__main__":
    main()