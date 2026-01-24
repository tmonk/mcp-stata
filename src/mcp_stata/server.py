from __future__ import annotations
import anyio
import asyncio
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
import re
import traceback
import uuid
from functools import wraps
from typing import Optional, Dict
import threading

from .ui_http import UIChannelManager


# Configure logging
logger = logging.getLogger("mcp_stata")
payload_logger = logging.getLogger("mcp_stata.payloads")
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
                    import re
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
    app_handler = logging.StreamHandler(sys.stderr)
    app_handler.setLevel(getattr(logging, log_level, logging.DEBUG))
    app_handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))

    mcp_handler = logging.StreamHandler(sys.stderr)
    mcp_handler.setLevel(getattr(logging, log_level, logging.DEBUG))
    mcp_handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))

    payload_handler = logging.StreamHandler(sys.stderr)
    payload_handler.setLevel(getattr(logging, log_level, logging.DEBUG))
    payload_handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))

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

    logger.info("=== mcp-stata server starting ===")
    logger.info("mcp-stata version: %s", SERVER_VERSION)
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

def _ensure_ui_channel():
    global ui_channel
    if ui_channel is None:
        try:
            from .ui_http import UIChannelManager
            ui_channel = UIChannelManager(client)
        except Exception:
            logger.exception("Failed to initialize UI channel")

@mcp.tool()
async def create_session(session_id: str) -> str:
    """Create a new Stata session.
    
    Args:
        session_id: A unique identifier for the new session.
    """
    await session_manager.get_or_create_session(session_id)
    return json.dumps({"status": "created", "session_id": session_id})

@mcp.tool()
async def stop_session(session_id: str) -> str:
    """Stop and terminate a Stata session.
    
    Args:
        session_id: The identifier of the session to stop.
    """
    await session_manager.stop_session(session_id)
    return json.dumps({"status": "stopped", "session_id": session_id})

@mcp.tool()
def list_sessions() -> str:
    """List all active Stata sessions and their status."""
    sessions = session_manager.list_sessions()
    return SessionListResponse(sessions=sessions).model_dump_json()


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
        task_id = getattr(meta, "task_id", None) or getattr(meta, "taskId", None)
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
    if asyncio.iscoroutinefunction(func):
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
async def run_do_file_background(
    path: str,
    ctx: Context | None = None,
    echo: bool = True,
    as_json: bool = True,
    trace: bool = False,
    raw: bool = False,
    max_output_lines: int = None,
    cwd: str | None = None,
    session_id: str = "default",
) -> str:
    """Run a Stata do-file in the background and return a task id.

    Notifications:
      - logMessage: {"event":"log_path","path":"..."}
      - logMessage: {"event":"task_done","task_id":"...","status":"done","log_path":"...","error":null}
    """
    session = getattr(getattr(ctx, "request_context", None), "session", None) if ctx is not None else None
    request_id = ctx.request_id if ctx is not None else None
    task_id = uuid.uuid4().hex
    _attach_task_id(ctx, task_id)
    task_info = BackgroundTask(
        task_id=task_id,
        kind="do_file",
        task=None,
        created_at=datetime.now(timezone.utc),
    )

    async def notify_log(text: str) -> None:
        if session is not None:
            if not _should_stream_smcl_chunk(text, ctx.request_id):
                return
            _debug_notification("logMessage", text, ctx.request_id)
            try:
                await session.send_log_message(level="info", data=text, related_request_id=ctx.request_id)
            except Exception as e:
                logger.warning("Failed to send logMessage notification: %s", e)
                sys.stderr.write(f"[mcp_stata] ERROR: logMessage send failed: {e!r}\n")
                sys.stderr.flush()
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and payload.get("event") == "log_path":
                task_info.log_path = payload.get("path")
                if ctx.request_id is not None and task_info.log_path:
                    _request_log_paths[str(ctx.request_id)] = task_info.log_path
        except Exception:
            return

    progress_token = None
    if ctx is not None and getattr(ctx, "request_context", None) is not None and getattr(ctx.request_context, "meta", None) is not None:
        progress_token = getattr(ctx.request_context.meta, "progressToken", None)

    async def notify_progress(progress: float, total: float | None, message: str | None) -> None:
        if session is None or progress_token is None:
            return
        _debug_notification(
            "progress",
            {"progress": progress, "total": total, "message": message},
            ctx.request_id,
        )
        try:
            await session.send_progress_notification(
                progress_token=progress_token,
                progress=progress,
                total=total,
                message=message,
                related_request_id=ctx.request_id,
            )
        except Exception as exc:
            logger.debug("Progress notification failed: %s", exc)

    async def _run() -> None:
        try:
            stata_session = await session_manager.get_or_create_session(session_id)
            result_dict = await stata_session.call(
                "run_do_file",
                {
                    "path": path,
                    "options": {
                        "echo": echo,
                        "trace": trace,
                        "max_output_lines": max_output_lines,
                        "cwd": cwd,
                        "emit_graph_ready": True,
                        "graph_ready_task_id": task_id,
                        "graph_ready_format": "svg",
                    }
                },
                notify_log=notify_log,
                notify_progress=notify_progress if progress_token is not None else None,
            )
            result = CommandResponse.model_validate(result_dict)
            if not task_info.log_path and result.log_path:
                task_info.log_path = result.log_path
            if result.error:
                task_info.error = result.error.message
            task_info.result = _format_command_result(result, raw=raw, as_json=as_json)
            task_info.done = True
            await _notify_task_done(session, task_info, request_id)

            _ensure_ui_channel()
            if ui_channel:
                ui_channel.notify_potential_dataset_change(session_id)
        except Exception as exc:  # pragma: no cover - defensive
            task_info.done = True
            task_info.error = str(exc)
            await _notify_task_done(session, task_info, request_id)

    if session is None:
        await _run()
        task_info.task = None
    else:
        task_info.task = asyncio.create_task(_run())
    _register_task(task_info)
    await _wait_for_log_path(task_info)
    return json.dumps({"task_id": task_id, "status": "started", "log_path": task_info.log_path})


@mcp.tool()
@log_call
def get_task_status(task_id: str, allow_polling: bool = False) -> str:
    """Return task status for background executions.

    Polling is disabled by default; set allow_polling=True for legacy callers.
    """
    notice = "Prefer task_done logMessage notifications over polling get_task_status."
    if not allow_polling:
        logger.warning(
            "get_task_status called without allow_polling; clients must use task_done logMessage notifications"
        )
        return json.dumps({
            "task_id": task_id,
            "status": "polling_not_allowed",
            "error": "Polling is disabled; use task_done logMessage notifications.",
            "notice": notice,
        })
    logger.warning("get_task_status called; clients should use task_done logMessage notifications instead of polling")
    task_info = _background_tasks.get(task_id)
    if task_info is None:
        return json.dumps({"task_id": task_id, "status": "not_found", "notice": notice})
    return json.dumps({
        "task_id": task_id,
        "status": "done" if task_info.done else "running",
        "kind": task_info.kind,
        "created_at": task_info.created_at.isoformat(),
        "log_path": task_info.log_path,
        "error": task_info.error,
        "notice": notice,
    })


@mcp.tool()
@log_call
def get_task_result(task_id: str, allow_polling: bool = False) -> str:
    """Return task result for background executions.

    Polling is disabled by default; set allow_polling=True for legacy callers.
    """
    notice = "Prefer task_done logMessage notifications over polling get_task_result."
    if not allow_polling:
        logger.warning(
            "get_task_result called without allow_polling; clients must use task_done logMessage notifications"
        )
        return json.dumps({
            "task_id": task_id,
            "status": "polling_not_allowed",
            "error": "Polling is disabled; use task_done logMessage notifications.",
            "notice": notice,
        })
    logger.warning("get_task_result called; clients should use task_done logMessage notifications instead of polling")
    task_info = _background_tasks.get(task_id)
    if task_info is None:
        return json.dumps({"task_id": task_id, "status": "not_found", "notice": notice})
    if not task_info.done:
        return json.dumps({
            "task_id": task_id,
            "status": "running",
            "log_path": task_info.log_path,
            "notice": notice,
        })
    return json.dumps({
        "task_id": task_id,
        "status": "done",
        "log_path": task_info.log_path,
        "error": task_info.error,
        "notice": notice,
        "result": task_info.result,
    })


@mcp.tool()
@log_call
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
@log_call
async def run_command_background(
    code: str,
    ctx: Context | None = None,
    echo: bool = True,
    as_json: bool = True,
    trace: bool = False,
    raw: bool = False,
    max_output_lines: int = None,
    cwd: str | None = None,
    session_id: str = "default",
) -> str:
    """Run a Stata command in the background and return a task id.

    Notifications:
      - logMessage: {"event":"log_path","path":"..."}
      - logMessage: {"event":"task_done","task_id":"...","status":"done","log_path":"...","error":null}
    """
    session = getattr(getattr(ctx, "request_context", None), "session", None) if ctx is not None else None
    request_id = ctx.request_id if ctx is not None else None
    task_id = uuid.uuid4().hex
    _attach_task_id(ctx, task_id)
    task_info = BackgroundTask(
        task_id=task_id,
        kind="command",
        task=None,
        created_at=datetime.now(timezone.utc),
    )

    async def notify_log(text: str) -> None:
        if session is not None:
            if not _should_stream_smcl_chunk(text, ctx.request_id):
                return
            _debug_notification("logMessage", text, ctx.request_id)
            await session.send_log_message(level="info", data=text, related_request_id=ctx.request_id)
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and payload.get("event") == "log_path":
                task_info.log_path = payload.get("path")
                if ctx.request_id is not None and task_info.log_path:
                    _request_log_paths[str(ctx.request_id)] = task_info.log_path
        except Exception:
            return

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

    async def _run() -> None:
        try:
            stata_session = await session_manager.get_or_create_session(session_id)
            result_dict = await stata_session.call(
                "run_command",
                {
                    "code": code,
                    "options": {
                        "echo": echo,
                        "trace": trace,
                        "max_output_lines": max_output_lines,
                        "cwd": cwd,
                        "emit_graph_ready": True,
                        "graph_ready_task_id": task_id,
                        "graph_ready_format": "svg",
                    }
                },
                notify_log=notify_log,
                notify_progress=notify_progress if progress_token is not None else None,
            )
            result = CommandResponse.model_validate(result_dict)
            if not task_info.log_path and result.log_path:
                task_info.log_path = result.log_path
            if result.error:
                task_info.error = result.error.message
            task_info.result = _format_command_result(result, raw=raw, as_json=as_json)
            task_info.done = True
            await _notify_task_done(session, task_info, request_id)

            _ensure_ui_channel()
            if ui_channel:
                ui_channel.notify_potential_dataset_change(session_id)
        except Exception as exc:  # pragma: no cover - defensive
            task_info.done = True
            task_info.error = str(exc)
            await _notify_task_done(session, task_info, request_id)

    if session is None:
        await _run()
        task_info.task = None
    else:
        task_info.task = asyncio.create_task(_run())
    _register_task(task_info)
    await _wait_for_log_path(task_info)
    return json.dumps({"task_id": task_id, "status": "started", "log_path": task_info.log_path})

@mcp.tool()
@log_call
async def run_command(
    code: str,
    ctx: Context | None = None,
    echo: bool = True,
    as_json: bool = True,
    trace: bool = False,
    raw: bool = False,
    max_output_lines: int = None,
    cwd: str | None = None,
    session_id: str = "default",
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
    session = getattr(getattr(ctx, "request_context", None), "session", None) if ctx is not None else None

    async def notify_log(text: str) -> None:
        if session is None:
            return
        if not _should_stream_smcl_chunk(text, ctx.request_id):
            return
        _debug_notification("logMessage", text, ctx.request_id)
        await session.send_log_message(level="info", data=text, related_request_id=ctx.request_id)
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and payload.get("event") == "log_path":
                if ctx.request_id is not None:
                    _request_log_paths[str(ctx.request_id)] = payload.get("path")
        except Exception:
            return

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


    stata_session = await session_manager.get_or_create_session(session_id)
    result_dict = await stata_session.call(
        "run_command",
        {
            "code": code,
            "options": {
                "echo": echo,
                "trace": trace,
                "max_output_lines": max_output_lines,
                "cwd": cwd,
                "emit_graph_ready": True,
                "graph_ready_task_id": ctx.request_id if ctx else None,
                "graph_ready_format": "svg",
            }
        },
        notify_log=notify_log if session is not None else _noop_log,
        notify_progress=notify_progress if progress_token is not None else None,
    )
    
    result = CommandResponse.model_validate(result_dict)
    _ensure_ui_channel()
    if ui_channel:
        ui_channel.notify_potential_dataset_change(session_id)
    return _format_command_result(result, raw=raw, as_json=as_json)

@mcp.tool()
@log_call
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


@mcp.tool()
@log_call
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
@log_call
async def get_data(start: int = 0, count: int = 50, session_id: str = "default") -> str:
    """
    Returns a slice of the active dataset as a JSON-formatted list of dictionaries.

    Use this to inspect the actual data values in memory. Useful for checking data quality or content.
    
    Args:
        start: The zero-based index of the first observation to retrieve.
        count: The number of observations to retrieve. Defaults to 50.
        session_id: The ID of the Stata session.
    """
    session = await session_manager.get_or_create_session(session_id)
    data = await session.call("get_data", {"start": start, "count": count})
    resp = DataResponse(start=start, count=count, data=data)
    return resp.model_dump_json()

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
def get_ui_channel(session_id: str = "default") -> str:
    """Return localhost HTTP endpoint + bearer token for the extension UI data plane.
    
    Args:
        session_id: Stata session ID to connect the UI to (default is "default").
    """
    _ensure_ui_channel()
    if ui_channel is None:
        return json.dumps({"error": "UI channel not initialized"})
    info = ui_channel.get_channel()
    payload = {
        "baseUrl": info.base_url,
        "token": info.token,
        "expiresAt": info.expires_at,
        "capabilities": ui_channel.capabilities(),
        "sessionId": session_id,
    }
    return json.dumps(payload)

@mcp.tool()
@log_call
async def describe(session_id: str = "default") -> str:
    """Returns the descriptive metadata of the dataset."""
    session = await session_manager.get_or_create_session(session_id)
    result_dict = await session.call("run_command_structured", {"code": "describe", "options": {"echo": True}})
    
    result = CommandResponse.model_validate(result_dict)
    if result.success:
        return result.stdout
    if result.error:
        return result.error.message
    return ""

@mcp.tool()
@log_call
async def list_graphs(session_id: str = "default") -> str:
    """Lists graphs in memory."""
    session = await session_manager.get_or_create_session(session_id)
    graphs_dict = await session.call("list_graphs", {})
    
    graphs = GraphListResponse.model_validate(graphs_dict)
    return graphs.model_dump_json()

@mcp.tool()
@log_call
async def export_graph(graph_name: str = None, format: str = "pdf", session_id: str = "default") -> str:
    """Exports a graph to a file."""
    session = await session_manager.get_or_create_session(session_id)
    try:
        return await session.call("export_graph", {"graph_name": graph_name, "format": format})
    except Exception as e:
        raise RuntimeError(f"Failed to export graph: {e}")

@mcp.tool()
@log_call
async def get_help(topic: str, plain_text: bool = False, session_id: str = "default") -> str:
    """Returns help for a Stata command."""
    session = await session_manager.get_or_create_session(session_id)
    return await session.call("get_help", {"topic": topic, "plain_text": plain_text})

@mcp.tool()
async def get_stored_results(session_id: str = "default") -> str:
    """Returns stored r() and e() results."""
    import json
    session = await session_manager.get_or_create_session(session_id)
    results = await session.call("get_stored_results", {})
    return json.dumps(results)

@mcp.tool()
async def load_data(source: str, clear: bool = True, as_json: bool = True, raw: bool = False, max_output_lines: int | None = None, session_id: str = "default") -> str:
    """Loads a dataset."""
    session = await session_manager.get_or_create_session(session_id)
    result_dict = await session.call("load_data", {"source": source, "options": {"clear": clear, "max_output_lines": max_output_lines}})
    
    result = CommandResponse.model_validate(result_dict)
    # ui_channel.notify_potential_dataset_change()
    if raw:
        return result.stdout if result.success else (result.error.message if result.error else result.stdout)
    return result.model_dump_json()

@mcp.tool()
async def codebook(variable: str, as_json: bool = True, trace: bool = False, raw: bool = False, max_output_lines: int | None = None, session_id: str = "default") -> str:
    """Returns codebook for a variable."""
    session = await session_manager.get_or_create_session(session_id)
    result_dict = await session.call("codebook", {"variable": variable, "options": {"trace": trace, "max_output_lines": max_output_lines}})
    
    result = CommandResponse.model_validate(result_dict)
    if raw:
        return result.stdout if result.success else (result.error.message if result.error else result.stdout)
    return result.model_dump_json()

@mcp.tool()
@log_call
async def run_do_file(
    path: str,
    ctx: Context | None = None,
    echo: bool = True,
    as_json: bool = True,
    trace: bool = False,
    raw: bool = False,
    max_output_lines: int = None,
    cwd: str | None = None,
    session_id: str = "default",
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
    session = getattr(getattr(ctx, "request_context", None), "session", None) if ctx is not None else None

    async def notify_log(text: str) -> None:
        if session is None:
            return
        if not _should_stream_smcl_chunk(text, ctx.request_id):
            return
        await session.send_log_message(level="info", data=text, related_request_id=ctx.request_id)
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and payload.get("event") == "log_path":
                if ctx.request_id is not None:
                    _request_log_paths[str(ctx.request_id)] = payload.get("path")
        except Exception:
            return

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

    stata_session = await session_manager.get_or_create_session(session_id)
    result_dict = await stata_session.call(
        "run_do_file",
        {
            "path": path,
            "options": {
                "echo": echo,
                "trace": trace,
                "max_output_lines": max_output_lines,
                "cwd": cwd,
                "emit_graph_ready": True,
                "graph_ready_task_id": ctx.request_id if ctx else None,
                "graph_ready_format": "svg",
            }
        },
        notify_log=notify_log if session is not None else _noop_log,
        notify_progress=notify_progress if progress_token is not None else None,
    )
    
    result = CommandResponse.model_validate(result_dict)

    # ui_channel.notify_potential_dataset_change()

    return _format_command_result(result, raw=raw, as_json=as_json)

@mcp.resource("stata://data/summary")
async def get_summary() -> str:
    """Returns output of summarize."""
    session = await session_manager.get_or_create_session("default")
    result_dict = await session.call("run_command_structured", {"code": "summarize", "options": {"echo": True}})
    
    result = CommandResponse.model_validate(result_dict)
    if result.success:
        return result.stdout
    if result.error:
        return result.error.message
    return ""

@mcp.resource("stata://data/metadata")
async def get_metadata() -> str:
    """Returns output of describe."""
    session = await session_manager.get_or_create_session("default")
    result_dict = await session.call("run_command_structured", {"code": "describe", "options": {"echo": True}})
    
    result = CommandResponse.model_validate(result_dict)
    if result.success:
        return result.stdout
    if result.error:
        return result.error.message
    return ""

@mcp.resource("stata://graphs/list")
@log_call
async def list_graphs_resource() -> str:
    """Resource wrapper for the graph list (uses tool list_graphs)."""
    return await list_graphs("default")

@mcp.tool()
async def get_variable_list(session_id: str = "default") -> str:
    """Returns JSON list of all variables."""
    session = await session_manager.get_or_create_session(session_id)
    variables_dict = await session.call("list_variables_structured", {})
    
    variables = VariablesResponse.model_validate(variables_dict)
    return variables.model_dump_json()

@mcp.resource("stata://variables/list")
async def get_variable_list_resource() -> str:
    """Resource wrapper for the variable list."""
    return await get_variable_list("default")

@mcp.resource("stata://results/stored")
async def get_stored_results_resource() -> str:
    """Returns stored r() and e() results."""
    session = await session_manager.get_or_create_session("default")
    results = await session.call("get_stored_results", {})
    return json.dumps(results)

@mcp.tool()
async def export_graphs_all(session_id: str = "default") -> str:
    """
    Exports all graphs in memory to file paths.

    Returns a JSON envelope listing graph names and file paths.
    The agent can open SVG files directly to verify visuals (titles/labels/colors/legends).
    """
    session = await session_manager.get_or_create_session(session_id)
    exports_dict = await session.call("export_graphs_all", {})
    
    exports = GraphExportResponse.model_validate(exports_dict)
    return exports.model_dump_json(exclude_none=False)

def main():
    if "--version" in sys.argv:
        print(SERVER_VERSION)
        return

    # Filter non-JSON output off stdout to keep stdio transport clean.
    _install_stdout_filter()

    setup_logging()
    
    # Initialize UI channel with default session proxy logic if needed
    # (Simplified for now, UI might only show default session)
    global ui_channel
    
    async def init_sessions():
        await session_manager.start()
        # We need a client-like object for UIChannelManager.
        # This is a bit tricky since it's now multi-session.
        # For now, we'll try to find a way to make UIChannelManager work or disable it.
        # Let's use the default session's worker proxy if it was a real client.
        # But for now, we'll skip UIChannelManager integration or keep it limited.
        pass

    asyncio.run(init_sessions())

    mcp.run()

if __name__ == "__main__":
    main()