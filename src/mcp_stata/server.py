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
    ToolEnvelope,
    ArtifactRef,
    LogRef,
    LogReadResult,
    LogMatch,
    TaskResult,
    SCHEMA_VERSION,
)
from .sessions import SessionManager
from .linter import StataLinter
import logging
import sys
import json
import os
import mimetypes
import multiprocessing
import re
import traceback
import uuid
from functools import wraps
from pathlib import Path
from typing import Any, Optional, Dict
import threading
import time

from .ui_http import UIChannelManager
from .toolkit_catalog_data import SKILLS, SKILL_BY_ID


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
mcp = FastMCP("mcp-stata")
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
REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_CHECKLISTS: dict[str, str] = {
    "data-audit": "plugin/skills/stata-data-audit/references/checklist.md",
    "publication-qa": "plugin/skills/stata-publication-qa/references/checklist.md",
    "replication": "plugin/skills/stata-replication/references/workflow.md",
    "causal-inference": "plugin/skills/stata-causal-inference/references/designs.md",
    "data-provenance": "plugin/skills/stata-data-provenance/references/lineage.md",
    "power-analysis": "plugin/skills/stata-power-analysis/references/power-checklist.md",
    "referee-response": "plugin/skills/stata-referee-response/references/response-patterns.md",
    "environment-diagnose": "plugin/skills/stata-environment-diagnose/references/troubleshooting.md",
    "table-builder": "plugin/skills/stata-table-builder/references/table-patterns.md",
}

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


@mcp.tool(structured_output=True)
@log_call
async def stata_manage_session(
    action: str,
    session_id: str = "default",
    code: Optional[str] = None,
    since_command: Optional[int] = None,
    include_packages: bool = False,
    as_json: bool = False,
) -> ToolEnvelope | str:
    """Manage Stata sessions (create, stop, list, profile, UI channel, detect).
    
    This tool allows for orchestration of multiple Stata sessions, including their
    lifecycle management and configuration.
    
    Args:
        action: The management action to perform:
            - "create": Initializes a new Stata session.
            - "stop": Terminates an existing Stata session.
            - "list": Returns a JSON list of all active sessions.
            - "set_profile": Executes initialization code for a session.
            - "history_diff": Returns tracked session state changes.
            - "history_stats": Returns retained history window metadata.
            - "get_ui_channel": Retrieves connection details for the UI proxy.
            - "detect": Returns metadata about the Stata installation and environment.
        session_id: Unique identifier for the Stata session (defaults to "default").
        code: Stata code to execute when using the "set_profile" action.
        since_command: Optional command index for "history_diff". If omitted, compares
            to the last diff checkpoint for this session.
        include_packages: If True (for "detect"), lists all user-installed packages.
        
    Returns:
        A JSON string containing the status of the action or the requested data.
    """
    _log_tool_call("stata_manage_session")
    if action == "create":
        envelope = _build_envelope(
            tool="stata_manage_session",
            success=True,
            session_id=session_id,
            data={"action": action, "status": "created", "session_id": session_id},
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "stop":
        await session_manager.stop_session(session_id)
        envelope = _build_envelope(
            tool="stata_manage_session",
            success=True,
            session_id=session_id,
            data={"action": action, "status": "stopped", "session_id": session_id},
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "list":
        sessions = session_manager.list_sessions()
        envelope = _build_envelope(
            tool="stata_manage_session",
            success=True,
            session_id=session_id,
            data=SessionListResponse(sessions=sessions).model_dump(),
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "set_profile":
        stata_session = await session_manager.get_or_create_session(session_id)
        await stata_session.set_profile(code)
        envelope = _build_envelope(
            tool="stata_manage_session",
            success=True,
            session_id=session_id,
            data={"action": action, "status": "profile_set", "session_id": session_id},
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "history_diff":
        stata_session = await session_manager.get_or_create_session(session_id)
        payload = await stata_session.get_session_diff(since_command=since_command)
        payload["session_id"] = session_id
        envelope = _build_envelope(
            tool="stata_manage_session",
            success=True,
            session_id=session_id,
            data=payload,
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "history_stats":
        stata_session = await session_manager.get_or_create_session(session_id)
        payload = stata_session.get_history_stats()
        payload["session_id"] = session_id
        envelope = _build_envelope(
            tool="stata_manage_session",
            success=True,
            session_id=session_id,
            data=payload,
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "get_ui_channel":
        _ensure_ui_channel()
        if ui_channel is None:
            envelope = _build_envelope(
                tool="stata_manage_session",
                success=False,
                session_id=session_id,
                error=ErrorEnvelope(message="UI channel not initialized"),
            )
            return _envelope_legacy_json(envelope) if as_json else envelope
        info = ui_channel.get_channel()
        envelope = _build_envelope(
            tool="stata_manage_session",
            success=True,
            session_id=session_id,
            data={
                "action": action,
                "baseUrl": info.base_url,
                "token": info.token,
                "expiresAt": info.expires_at,
                "capabilities": ui_channel.capabilities(),
                "sessionId": session_id,
            },
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "detect":
        stata_session = await session_manager.get_or_create_session(session_id)
        vars_to_get = ["stata_version", "version", "flavor", "os", "osdtl", "machine_type"]
        info = {}
        for var in vars_to_get:
            res_dict = await stata_session.call(
                "run_command_structured",
                {"code": f"display c({var})", "strip_smcl": True, "options": {"echo": False}},
            )
            res = CommandResponse.model_validate(res_dict)
            if res.success:
                info[var] = res.stdout.strip()
        if include_packages:
            pkg_result_dict = await stata_session.call(
                "run_command_structured",
                {"code": "ado", "strip_smcl": True, "options": {"echo": False}},
            )
            pkg_result = CommandResponse.model_validate(pkg_result_dict)
            info["packages"] = pkg_result.stdout
        envelope = _build_envelope(
            tool="stata_manage_session",
            success=True,
            session_id=session_id,
            data=info,
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    else:
        envelope = _build_envelope(
            tool="stata_manage_session",
            success=False,
            session_id=session_id,
            error=ErrorEnvelope(message=f"Invalid action: {action}"),
        )
        return _envelope_legacy_json(envelope) if as_json else envelope


@mcp.tool(structured_output=True)
@log_call
async def stata_load_data(
    source: str,
    clear: bool = True,
    as_json: bool = False,
    raw: bool = False,
    strip_smcl: bool = True,
    max_output_lines: int | None = None,
    session_id: str = "default",
) -> ToolEnvelope | str:
    """Loads a dataset into a Stata session.
    
    Supports loading local .dta files or using Stata's built-in 'sysuse' and 'webuse' 
    commands. This tool ensures that the dataset is properly initialized for use 
    in subsequent analysis.
    
    Args:
        source: Path to the dataset file or a valid Stata sysuse/webuse name.
        clear: If True (default), clears any existing data in memory before loading.
        as_json: If True, returns a structured JSON response envelope.
        raw: If True, returns only the raw Stata output or error message.
        strip_smcl: If True, removes Stata SMCL tags from the output for readability.
        max_output_lines: Optional limit on the number of output lines to return.
        session_id: The ID of the Stata session to load data into.
        
    Returns:
        A JSON string (if as_json is True) or raw text containing the result of the load operation.
    """
    _log_tool_call("stata_load_data")
    session = await session_manager.get_or_create_session(session_id)
    result_dict = await session.call(
        "load_data",
        {
            "source": source,
            "strip_smcl": strip_smcl,
            "options": {"clear": clear, "max_output_lines": max_output_lines},
        },
    )
    result = CommandResponse.model_validate(result_dict)
    if raw:
        return result.stdout if result.success else (result.error.message if result.error else result.stdout)
    envelope = _command_result_envelope("stata_load_data", session_id, result)
    envelope.data = {
        **(envelope.data if isinstance(envelope.data, dict) else {}),
        "source": source,
        "clear": clear,
    }
    if as_json:
        return _envelope_legacy_json(envelope)
    return envelope


async def _noop_log(_text: str) -> None:
    return

@dataclass
class BackgroundTask:
    task_id: str
    kind: str
    task: asyncio.Task
    created_at: datetime
    session_id: str = "default"
    log_path: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    error_details: Optional[ErrorEnvelope] = None
    done: bool = False


_background_tasks: Dict[str, BackgroundTask] = {}
_request_log_paths: Dict[str, str] = {}
_read_log_paths: set[str] = set()
_read_log_offsets: Dict[str, int] = {}
_STDOUT_FILTER_INSTALLED = False

def _compact_stored_results(results: dict, include_formatting: bool = False) -> dict:
    """Drop noisy table-formatting macros from stored results by default."""
    if include_formatting:
        return results
    compact: dict[str, dict] = {}
    for cls in ("r", "e", "s"):
        source = results.get(cls, {})
        if not isinstance(source, dict):
            compact[cls] = {}
            continue
        filtered = {
            k: v for k, v in source.items()
            if not (k.startswith("PT_") or k.startswith("put_"))
        }
        compact[cls] = filtered
    return compact


def _extract_help_format(help_text: str, format: str) -> str:
    """Return concise slices of help text for syntax/options/examples modes."""
    if format == "full":
        return help_text
    lines = help_text.splitlines()
    if format == "syntax":
        out = [ln for ln in lines if ln.strip().lower().startswith("syntax")]
        if out:
            return "\n".join(out[:6]).strip()
        return "\n".join(lines[:24]).strip()
    if format in {"options", "examples"}:
        marker = "options" if format == "options" else "examples"
        start = None
        for i, ln in enumerate(lines):
            if marker in ln.strip().lower():
                start = i
                break
        if start is None:
            return "\n".join(lines[:40]).strip()
        end = min(len(lines), start + 120)
        return "\n".join(lines[start:end]).strip()
    return help_text


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


def _infer_mime_type(path: str | None, format_hint: str | None = None) -> str | None:
    if format_hint:
        guessed, _ = mimetypes.guess_type(f"artifact.{format_hint}")
        if guessed:
            return guessed
    if path:
        guessed, _ = mimetypes.guess_type(path)
        if guessed:
            return guessed
    return None


def _artifact_from_path(
    path: str | None,
    *,
    kind: str,
    title: str | None = None,
    format_hint: str | None = None,
) -> ArtifactRef | None:
    if not path:
        return None
    return ArtifactRef(
        kind=kind,
        path=path,
        title=title,
        format=format_hint,
        mime_type=_infer_mime_type(path, format_hint),
    )


def _artifact_refs_from_result(result: CommandResponse) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for item in result.artifacts or []:
        if not isinstance(item, dict):
            continue
        path = item.get("path") or item.get("file_path")
        if not path:
            continue
        refs.append(
            ArtifactRef(
                kind=str(item.get("kind", "artifact")),
                path=str(path),
                title=item.get("title") or item.get("name"),
                format=item.get("format"),
                mime_type=item.get("mime_type") or _infer_mime_type(str(path), item.get("format")),
            )
        )
    return refs


def _truncate_text(text: str | None, limit: int = 5000) -> str | None:
    if not text or len(text) <= limit:
        return text
    return (
        f"\n... [truncated: {len(text)} total characters, showing tail only. "
        "Use stata_read_log for full output] ...\n"
        + text[-limit:]
    )


def _command_data(result: CommandResponse) -> dict[str, Any]:
    return {
        "command": result.command,
        "rc": result.rc,
        "stdout": _truncate_text(result.stdout),
        "stderr": _truncate_text(result.stderr),
        "smcl_output": None,
    }


def _build_envelope(
    *,
    tool: str,
    success: bool,
    session_id: str | None = None,
    data: dict[str, Any] | list[Any] | str | None = None,
    error: ErrorEnvelope | None = None,
    artifacts: list[ArtifactRef] | None = None,
    log_path: str | None = None,
    log_offset: int | None = None,
    log_next_offset: int | None = None,
    log_tail: str | None = None,
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> ToolEnvelope:
    return ToolEnvelope(
        schema_version=SCHEMA_VERSION,
        tool=tool,
        success=success,
        session_id=session_id,
        data=data,
        error=error,
        artifacts=artifacts or [],
        log=LogRef(path=log_path, offset=log_offset, next_offset=log_next_offset, tail=log_tail)
        if any(x is not None for x in (log_path, log_offset, log_next_offset, log_tail))
        else None,
        warnings=warnings or [],
        next_actions=next_actions or [],
    )


def _envelope_legacy_json(envelope: ToolEnvelope) -> str:
    return envelope.model_dump_json(exclude_none=True)


def _command_result_envelope(tool: str, session_id: str, result: CommandResponse) -> ToolEnvelope:
    next_actions: list[str] = []
    if result.log_path:
        next_actions.append("Use stata_read_log with the returned log path for full output.")
    if not result.success:
        next_actions.append("Inspect error_details and log output before retrying.")
    return _build_envelope(
        tool=tool,
        success=result.success,
        session_id=session_id,
        data=_command_data(result),
        error=result.error,
        artifacts=_artifact_refs_from_result(result),
        log_path=result.log_path,
        next_actions=next_actions,
    )


def _format_command_result(result: CommandResponse, raw: bool, as_json: bool, session_id: str) -> ToolEnvelope | str:
    if raw:
        if result.success:
            return result.log_path or ""
        if result.error:
            msg = result.error.message
            if result.error.rc is not None:
                msg = f"{msg}\nrc={result.error.rc}"
            return msg
        return result.log_path or ""
    
    envelope = _command_result_envelope("stata_run", session_id, result)
    if envelope.error and envelope.error.details:
        envelope.error.details = _truncate_text(envelope.error.details)
    if as_json:
        return _envelope_legacy_json(envelope)
    return envelope


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
        "error_details": task_info.error_details.model_dump() if task_info.error_details else None,
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

@mcp.tool(structured_output=True)
@log_call
async def stata_task_status(
    task_id: str,
    wait: bool = False,
    timeout: float = 60.0,
    poll_interval: float = 1.0,
    tail_lines: int = 0,
    as_json: bool = False,
) -> ToolEnvelope | str:
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
            envelope = _build_envelope(
                tool="stata_task_status",
                success=False,
                data=TaskResult(task_id=task_id, status="not_found").model_dump(),
                error=ErrorEnvelope(message=f"Task {task_id} not found"),
            )
            return _envelope_legacy_json(envelope) if as_json else envelope

        if task_info.done or not wait or (time.time() - start_time >= timeout):
            status = "running"
            if task_info.done:
                status = "failed" if task_info.error else "done"
            
            res = {
                "task_id": task_id,
                "status": status,
                "kind": task_info.kind,
                "created_at": task_info.created_at.isoformat(),
                "log_path": task_info.log_path,
                "error": task_info.error,
                "error_details": task_info.error_details.model_dump() if task_info.error_details else None,
                "result": task_info.result if task_info.done else None
            }
            if tail_lines > 0:
                res["tail"] = _tail_file(task_info.log_path, tail_lines)
            
            # If it failed and no tail was requested, add a small tail anyway for visibility
            if status == "failed" and tail_lines <= 0:
                res["error_tail"] = _tail_file(task_info.log_path, 10)

            if not task_info.done and wait and (time.time() - start_time >= timeout):
                res["status"] = "timeout"
                res["error"] = f"Task did not complete within {timeout} seconds."
            envelope = _build_envelope(
                tool="stata_task_status",
                success=status in {"running", "done"},
                data=res,
                error=task_info.error_details if task_info.error_details else (
                    ErrorEnvelope(message=res["error"]) if res.get("error") and status not in {"running", "done"} else None
                ),
                log_path=task_info.log_path,
                log_tail=res.get("tail") or res.get("error_tail"),
            )
            return _envelope_legacy_json(envelope) if as_json else envelope

        await asyncio.sleep(poll_interval)


@mcp.tool(structured_output=True)
@log_call
async def stata_control(
    action: str,
    id: str,
    as_json: bool = False,
) -> ToolEnvelope | str:
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
            envelope = _build_envelope(
                tool="stata_control",
                success=True,
                session_id=id,
                data={"status": "break_sent", "session_id": id},
            )
            return _envelope_legacy_json(envelope) if as_json else envelope
        except Exception as e:
            envelope = _build_envelope(
                tool="stata_control",
                success=False,
                session_id=id,
                error=ErrorEnvelope(message=str(e)),
            )
            return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "cancel":
        task_info = _background_tasks.get(id)
        if task_info is None:
            envelope = _build_envelope(
                tool="stata_control",
                success=False,
                data={"task_id": id, "status": "not_found"},
                error=ErrorEnvelope(message=f"Task {id} not found"),
            )
            return _envelope_legacy_json(envelope) if as_json else envelope
        if task_info.task and not task_info.task.done():
            task_info.task.cancel()
            envelope = _build_envelope(
                tool="stata_control",
                success=True,
                data={"task_id": id, "status": "cancelling"},
                log_path=task_info.log_path,
            )
            return _envelope_legacy_json(envelope) if as_json else envelope
        envelope = _build_envelope(
            tool="stata_control",
            success=True,
            data={"task_id": id, "status": "done", "log_path": task_info.log_path},
            log_path=task_info.log_path,
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    else:
        envelope = _build_envelope(
            tool="stata_control",
            success=False,
            error=ErrorEnvelope(message=f"Invalid action: {action}"),
        )
        return _envelope_legacy_json(envelope) if as_json else envelope


@mcp.tool(structured_output=True)
@log_call
async def stata_run(
    code: str,
    is_file: bool = False,
    background: bool = False,
    ctx: Context | None = None,
    echo: bool = True,
    as_json: bool = False,
    trace: bool = False,
    raw: bool = False,
    max_output_lines: int = None,
    cwd: str | None = None,
    session_id: str = "default",
    strip_smcl: bool = True,
    filter_pattern: Optional[str] = None,
    exclude_pattern: Optional[str] = None,
) -> ToolEnvelope | str:
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
        For sync calls: The execution output (JSON or raw text). Note: the return 
            value is truncated to the tail (max 5,000 chars) for token efficiency. 
            Agents should follow real-time `logMessage` notifications or use 
            `stata_read_log` on the provided `log_path` for full execution details.
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
        session_id=session_id,
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
                task_info.error_details = result.error
            task_info.result = _format_command_result(result, raw=raw, as_json=False, session_id=session_id)
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
        envelope = _build_envelope(
            tool="stata_run",
            success=True,
            session_id=session_id,
            data=TaskResult(task_id=task_id, status="started").model_dump() | {"log_path": task_info.log_path},
            log_path=task_info.log_path,
            next_actions=[
                "Poll stata_task_status with the task_id to watch progress.",
                "Use stata_read_log with the returned log path for incremental output.",
            ],
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    else:
        # Sync execution
        result = await _run_logic()
        _ensure_ui_channel()
        if ui_channel:
            ui_channel.notify_potential_dataset_change(session_id)
        logger.info("stata_run sync result: %s", result)
        return _format_command_result(result, raw=raw, as_json=as_json, session_id=session_id)


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


@mcp.tool(structured_output=True)
@log_call
def stata_read_log(
    path: Optional[str] = None,
    task_id: Optional[str] = None,
    offset: int = 0,
    max_bytes: int = 262144,
    tail_lines: int = 0,
    query: Optional[str] = None,
    before: int = 2,
    after: int = 2,
    case_sensitive: bool = False,
    regex: bool = False,
    max_matches: int = 50,
    as_json: bool = False,
) -> ToolEnvelope | str:
    """Read or search Stata log files.
    
    Provides low-level access to execution logs. Supports reading specific byte 
    ranges, tailing the end of logs, and searching for patterns with context lines.
    
    Args:
        path: Optional absolute path to the log file on disk.
        task_id: Optional ID of a background task to read the log for (alternative to path).
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
    logger.info(f"stata_read_log called with path={path}, task_id={task_id}")
    
    if task_id:
        task_info = _background_tasks.get(task_id)
        if not task_info or not task_info.log_path:
            envelope = _build_envelope(
                tool="stata_read_log",
                success=False,
                error=ErrorEnvelope(message=f"Task {task_id} not found or has no log path"),
            )
            return _envelope_legacy_json(envelope) if as_json else envelope
        path = task_info.log_path

    if not path:
        envelope = _build_envelope(
            tool="stata_read_log",
            success=False,
            error=ErrorEnvelope(message="Either path or task_id must be provided"),
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    if query:
        payload = json.loads(_find_in_log_logic(path, query, offset, max_bytes, before, after, case_sensitive, regex, max_matches))
        model = LogReadResult(
            path=payload["path"],
            offset=payload.get("start_offset"),
            next_offset=payload.get("next_offset"),
            query=payload.get("query"),
            truncated=payload.get("truncated"),
            matches=[LogMatch.model_validate(match) for match in payload.get("matches", [])],
            error=payload.get("error"),
        )
        envelope = _build_envelope(
            tool="stata_read_log",
            success=model.error is None,
            data=model.model_dump(),
            error=ErrorEnvelope(message=model.error) if model.error else None,
            log_path=model.path,
            log_offset=model.offset,
            log_next_offset=model.next_offset,
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif tail_lines > 0:
        tail = _tail_file(path, tail_lines)
        model = LogReadResult(path=path, data=tail or "")
        envelope = _build_envelope(
            tool="stata_read_log",
            success=True,
            data=model.model_dump(),
            log_path=path,
            log_tail=model.data,
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    else:
        payload = json.loads(_read_log_logic(path, offset, max_bytes))
        model = LogReadResult(
            path=payload["path"],
            offset=payload.get("offset"),
            next_offset=payload.get("next_offset"),
            data=payload.get("data"),
        )
        envelope = _build_envelope(
            tool="stata_read_log",
            success=not model.data.startswith("ERROR:") if model.data else True,
            data=model.model_dump(),
            error=ErrorEnvelope(message=model.data) if model.data and model.data.startswith("ERROR:") else None,
            log_path=path,
            log_offset=model.offset,
            log_next_offset=model.next_offset,
        )
        return _envelope_legacy_json(envelope) if as_json else envelope


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


@mcp.tool(structured_output=True)
@log_call
async def stata_inspect_data(
    action: str,
    query: Optional[str] = None,
    variables: Optional[list[str]] = None,
    start: int = 0,
    count: int = 50,
    include_missing: bool = True,
    compress_numeric: bool = False,
    strip_smcl: bool = True,
    session_id: str = "default",
    path: Optional[str] = None,
    linemax: int = 80,
    indent: int = 4,
    as_json: bool = False,
    legacy_text: bool = False,
) -> ToolEnvelope | str:
    """Inspect the active dataset (describe, codebook, summarize, search, get data) or code (lint).
    
    Comprehensive tool for exploring the structure and content of the current 
    Stata dataset or performing static analysis on Stata code files.
    
    Args:
        action: The inspection action to perform:
            - "describe": Returns dataset structure and variable types.
            - "codebook": Detailed description of a specific variable's contents.
            - "summary": Descriptive statistics (mean, sd, etc.) for variables.
            - "search": Finds variables matching a name or label pattern.
            - "list": Returns a structured list of all variables in the dataset.
            - "get": Retrieves raw data observations from the dataset.
            - "lint": Performs static analysis on a .do or .ado file.
        query: Search term for the "search" action or variable name for "codebook".
        variables: Optional list of variables to include in the "summary" action.
        start: 0-indexed starting observation for the "get" action.
        count: Number of observations to retrieve for the "get" action.
        strip_smcl: If True, removes Stata SMCL tags from text-like outputs.
        session_id: The ID of the Stata session to inspect.
        path: (For "lint") Absolute path to the file to check.
        linemax: (For "lint") Maximum line length (default 80).
        indent: (For "lint") Required indentation size (default 4).
        
    Returns:
        A JSON string or formatted text containing the requested inspection data.
    """
    _log_tool_call("stata_inspect_data")
    session = await session_manager.get_or_create_session(session_id)
    if action == "describe":
        result_dict = await session.call(
            "run_command_structured",
            {"code": "describe", "strip_smcl": strip_smcl, "options": {"echo": True}},
        )
        result = CommandResponse.model_validate(result_dict)
        if legacy_text:
            return result.stdout if result.success else (result.error.message if result.error else "")
        variables_dict = await session.call("list_variables_structured", {})
        variables_resp = VariablesResponse.model_validate(variables_dict)
        envelope = _build_envelope(
            tool="stata_inspect_data",
            success=result.success,
            session_id=session_id,
            data={
                "action": action,
                "rendered": result.stdout,
                "variables": variables_resp.model_dump()["variables"],
            },
            error=result.error,
            log_path=result.log_path,
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "codebook":
        result_dict = await session.call(
            "codebook",
            {"variable": query, "strip_smcl": strip_smcl, "options": {}},
        )
        result = CommandResponse.model_validate(result_dict)
        envelope = _command_result_envelope("stata_inspect_data", session_id, result)
        envelope.data = {**(envelope.data if isinstance(envelope.data, dict) else {}), "action": action, "query": query}
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "summary":
        summary_data = await session.call("get_data_summary", {"variables": variables})
        envelope = _build_envelope(
            tool="stata_inspect_data",
            success=True,
            session_id=session_id,
            data={"action": action, "summary": summary_data},
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "search":
        variables_dict = await session.call("find_variables", {"query": query})
        variables_resp = VariablesResponse.model_validate(variables_dict)
        envelope = _build_envelope(
            tool="stata_inspect_data",
            success=True,
            session_id=session_id,
            data={"action": action, **variables_resp.model_dump()},
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "list":
        variables_dict = await session.call("list_variables_structured", {})
        variables_resp = VariablesResponse.model_validate(variables_dict)
        envelope = _build_envelope(
            tool="stata_inspect_data",
            success=True,
            session_id=session_id,
            data={"action": action, **variables_resp.model_dump()},
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "get":
        data = await session.call(
            "get_data",
            {
                "start": start,
                "count": count,
                "variables": variables,
                "include_missing": include_missing,
                "compress_numeric": compress_numeric,
            },
        )
        resp = DataResponse(start=start, count=count, data=data)
        envelope = _build_envelope(
            tool="stata_inspect_data",
            success=True,
            session_id=session_id,
            data={"action": action, **resp.model_dump()},
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "lint":
        if not path:
            envelope = _build_envelope(
                tool="stata_inspect_data",
                success=False,
                session_id=session_id,
                error=ErrorEnvelope(message="Path must be provided for lint action"),
            )
            return _envelope_legacy_json(envelope) if as_json else envelope
        linter = StataLinter(linemax=linemax, indent=indent)
        try:
            results = linter.lint_file(path)
            envelope = _build_envelope(
                tool="stata_inspect_data",
                success=True,
                session_id=session_id,
                data={
                    "action": action,
                    "path": path,
                    "violations": results,
                    "count": len(results),
                },
            )
            return _envelope_legacy_json(envelope) if as_json else envelope
        except Exception as e:
            envelope = _build_envelope(
                tool="stata_inspect_data",
                success=False,
                session_id=session_id,
                error=ErrorEnvelope(message=str(e)),
            )
            return _envelope_legacy_json(envelope) if as_json else envelope
    else:
        envelope = _build_envelope(
            tool="stata_inspect_data",
            success=False,
            session_id=session_id,
            error=ErrorEnvelope(message=f"Invalid action: {action}"),
        )
        return _envelope_legacy_json(envelope) if as_json else envelope

@mcp.tool(structured_output=True)
@log_call
async def stata_manage_graphs(
    action: str,
    graph_name: Optional[str] = None,
    format: str = "svg",
    session_id: str = "default",
    as_json: bool = False,
) -> ToolEnvelope | str:
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
        envelope = _build_envelope(
            tool="stata_manage_graphs",
            success=True,
            session_id=session_id,
            data={"action": action, **graphs.model_dump()},
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    elif action == "export":
        try:
            export_path = await session.call("export_graph", {"graph_name": graph_name, "format": format})
            export = GraphExport(
                name=graph_name or "",
                file_path=export_path,
                format=format,
                mime_type=_infer_mime_type(export_path, format),
            )
            artifact = _artifact_from_path(export_path, kind="graph", title=graph_name, format_hint=format)
            envelope = _build_envelope(
                tool="stata_manage_graphs",
                success=True,
                session_id=session_id,
                data={"action": action, "graphs": [export.model_dump()]},
                artifacts=[artifact] if artifact else [],
            )
            return _envelope_legacy_json(envelope) if as_json else envelope
        except Exception as e:
            raise RuntimeError(f"[mcp-stata] Failed to export graph: {e}")
    elif action == "export_all":
        exports_dict = await session.call("export_graphs_all", {})
        exports = GraphExportResponse.model_validate(exports_dict)
        artifact_refs = [
            _artifact_from_path(item.file_path, kind="graph", title=item.name, format_hint=item.format)
            for item in exports.graphs
        ]
        envelope = _build_envelope(
            tool="stata_manage_graphs",
            success=True,
            session_id=session_id,
            data={"action": action, **exports.model_dump(exclude_none=False)},
            artifacts=[item for item in artifact_refs if item is not None],
        )
        return _envelope_legacy_json(envelope) if as_json else envelope
    else:
        envelope = _build_envelope(
            tool="stata_manage_graphs",
            success=False,
            session_id=session_id,
            error=ErrorEnvelope(message=f"Invalid action: {action}"),
        )
        return _envelope_legacy_json(envelope) if as_json else envelope

@mcp.tool(structured_output=True)
@log_call
async def stata_get_results(
    session_id: str = "default",
    include_formatting: bool = False,
    include_matrices: bool = True,
    matrix_max_rows: int = 200,
    matrix_max_cols: int = 200,
    include_mata: bool = False,
    as_json: bool = False,
) -> ToolEnvelope | str:
    """Returns coherent structured result state across r()/e()/s(), with optional MATA snapshot."""
    _log_tool_call("stata_get_results")
    session = await session_manager.get_or_create_session(session_id)
    results = await session.call(
        "get_stored_results",
        {
            "include_matrices": include_matrices,
            "matrix_max_rows": matrix_max_rows,
            "matrix_max_cols": matrix_max_cols,
            "force_fresh": True,
        },
    )
    payload = _compact_stored_results(results, include_formatting=include_formatting)
    if include_mata:
        payload["mata"] = await session.call(
            "get_mata_state",
            {
                "include_values": True,
                "max_objects": 200,
                "matrix_max_rows": matrix_max_rows,
                "matrix_max_cols": matrix_max_cols,
                "max_functions": 200,
            },
        )
    envelope = _build_envelope(
        tool="stata_get_results",
        success=True,
        session_id=session_id,
        data=payload,
    )
    if as_json:
        return _envelope_legacy_json(envelope)
    return envelope

@mcp.tool(structured_output=True)
@log_call
async def stata_get_help(
    topic: str,
    plain_text: bool = False,
    merge_paragraphs: bool = True,
    format: str = "full",
    session_id: str = "default",
    as_json: bool = False,
    legacy_text: bool = False,
) -> ToolEnvelope | str:
    """Returns help for a Stata command.
    
    Args:
        topic: The command or topic to get help for.
        plain_text: If True, returns plain text instead of Markdown.
        merge_paragraphs: If True, merges fixed-width split paragraphs.
        session_id: The ID of the Stata session.
    """
    _log_tool_call("stata_get_help")
    session = await session_manager.get_or_create_session(session_id)
    help_text = await session.call(
        "get_help",
        {"topic": topic, "plain_text": plain_text, "merge_paragraphs": merge_paragraphs},
    )
    rendered = _extract_help_format(help_text, format=format)
    if legacy_text:
        return rendered
    envelope = _build_envelope(
        tool="stata_get_help",
        success=True,
        session_id=session_id,
        data={
            "topic": topic,
            "format": format,
            "plain_text": plain_text,
            "rendered": rendered,
        },
    )
    return _envelope_legacy_json(envelope) if as_json else envelope


def _project_manifest_data() -> dict[str, Any]:
    supported_agents = sorted({agent for item in SKILLS for agent in item.get("supported_agents", [])})
    return {
        "name": "mcp-stata",
        "server_version": SERVER_VERSION,
        "repo_root": str(REPO_ROOT),
        "skills_count": len(SKILLS),
        "skills": [
            {
                "id": item["id"],
                "description": item["description"],
                "invocation_type": item["invocation_type"],
            }
            for item in SKILLS
        ],
        "supported_agents": supported_agents,
    }


def _read_reference_text(topic: str) -> str:
    rel_path = RESEARCH_CHECKLISTS.get(topic)
    if rel_path is None:
        raise ValueError(f"Unknown checklist topic: {topic}")
    return (REPO_ROOT / rel_path).read_text()


async def _list_variables_for_session(session_id: str) -> list[dict[str, Any]]:
    session = await session_manager.get_or_create_session(session_id)
    variables_dict = await session.call("list_variables_structured", {})
    return VariablesResponse.model_validate(variables_dict).model_dump()["variables"]


def _numeric_candidate_names(variables: list[dict[str, Any]], limit: int = 8) -> list[str]:
    numeric = []
    for var in variables:
        vtype = (var.get("type") or "").lower()
        if vtype and not vtype.startswith("str"):
            numeric.append(var["name"])
        if len(numeric) >= limit:
            break
    return numeric


async def _summary_for_variables(session_id: str, variables: list[str]) -> dict[str, Any]:
    session = await session_manager.get_or_create_session(session_id)
    return await session.call("get_data_summary", {"variables": variables})


async def _run_structured_command(
    session_id: str,
    code: str,
    *,
    strip_smcl: bool = True,
    echo: bool = True,
) -> CommandResponse:
    session = await session_manager.get_or_create_session(session_id)
    result_dict = await session.call(
        "run_command_structured",
        {"code": code, "strip_smcl": strip_smcl, "options": {"echo": echo}},
    )
    return CommandResponse.model_validate(result_dict)


async def _estimation_snapshot(session_id: str) -> dict[str, Any]:
    session = await session_manager.get_or_create_session(session_id)
    stored = await session.call(
        "get_stored_results",
        {
            "include_matrices": True,
            "matrix_max_rows": 20,
            "matrix_max_cols": 20,
            "force_fresh": True,
        },
    )
    payload = _compact_stored_results(stored, include_formatting=False)
    e_part = payload.get("e", {}) if isinstance(payload, dict) else {}
    summary = {
        "cmd": e_part.get("cmd"),
        "depvar": e_part.get("depvar"),
        "N": e_part.get("N"),
        "r2": e_part.get("r2"),
        "r2_a": e_part.get("r2_a"),
        "rmse": e_part.get("rmse"),
        "vce": e_part.get("vce"),
        "vcetype": e_part.get("vcetype"),
    }
    matrices = e_part.get("_matrices", {})
    if isinstance(matrices, dict):
        summary["matrices"] = {}
        for name in ("b", "V", "beta"):
            if name in matrices:
                summary["matrices"][name] = matrices[name]
    return summary


async def _recent_session_logs(session_id: str) -> list[dict[str, Any]]:
    items = []
    for task in sorted(_background_tasks.values(), key=lambda item: item.created_at, reverse=True):
        if task.session_id != session_id:
            continue
        items.append(
            {
                "task_id": task.task_id,
                "status": "failed" if task.error else ("done" if task.done else "running"),
                "log_path": task.log_path,
                "created_at": task.created_at.isoformat(),
                "kind": task.kind,
            }
        )
    return items[:20]


@mcp.tool(structured_output=True)
@log_call
async def stata_research_audit(
    session_id: str = "default",
    key_variables: Optional[list[str]] = None,
    candidate_id_vars: Optional[list[str]] = None,
    include_publication_checks: bool = False,
    as_json: bool = False,
) -> ToolEnvelope | str:
    """Run a compact structured dataset audit for empirical research workflows."""
    variables = await _list_variables_for_session(session_id)
    numeric_candidates = key_variables or _numeric_candidate_names(variables)
    summary = await _summary_for_variables(session_id, numeric_candidates) if numeric_candidates else {}
    unlabeled = [var["name"] for var in variables if not var.get("label")]
    string_vars = [var["name"] for var in variables if (var.get("type") or "").startswith("str")]

    id_checks = []
    for var in candidate_id_vars or []:
        result = await _run_structured_command(session_id, f"capture noisily duplicates report {var}", strip_smcl=True)
        id_checks.append(
            {
                "variable": var,
                "success": result.success,
                "rc": result.rc,
                "stdout": _truncate_text(result.stdout, limit=1500),
            }
        )

    warnings = []
    if unlabeled:
        warnings.append(f"{len(unlabeled)} variables are missing labels.")
    if len(string_vars) > max(3, len(variables) // 2):
        warnings.append("The dataset contains many string variables; verify encoded analysis fields.")
    if not candidate_id_vars:
        warnings.append("No candidate identifier variables were supplied for duplicate checks.")

    checklist = [
        "Confirm panel/unit identifiers and duplicate handling.",
        "Review missingness and outlier patterns for core variables.",
        "Verify labels, units, and sample restriction logic before estimation.",
    ]
    if include_publication_checks:
        checklist.append("Review table notes, graph labels, and export formats for paper-readiness.")

    envelope = _build_envelope(
        tool="stata_research_audit",
        success=True,
        session_id=session_id,
        data={
            "variables": variables,
            "summary": summary,
            "unlabeled_variables": unlabeled,
            "candidate_id_checks": id_checks,
            "checklist": checklist,
        },
        warnings=warnings,
        next_actions=[
            "Use stata_data_audit guidance to investigate flagged variables in more detail.",
            "Run stata_publication_check after estimation outputs are ready.",
        ],
    )
    return _envelope_legacy_json(envelope) if as_json else envelope


@mcp.tool(structured_output=True)
@log_call
async def stata_estimation_plan(
    dependent_var: str,
    independent_vars: list[str],
    session_id: str = "default",
    estimator: str = "regress",
    fixed_effects: Optional[list[str]] = None,
    cluster_var: Optional[str] = None,
    controls: Optional[list[str]] = None,
    as_json: bool = False,
) -> ToolEnvelope | str:
    """Build a structured estimation plan and recommended Stata command."""
    variables = await _list_variables_for_session(session_id)
    available = {item["name"] for item in variables}
    requested = [dependent_var, *independent_vars, *(fixed_effects or []), *(controls or [])]
    if cluster_var:
        requested.append(cluster_var)
    missing = sorted({name for name in requested if name not in available})

    rhs = independent_vars + (controls or [])
    if fixed_effects and estimator == "reghdfe":
        command = f"{estimator} {dependent_var} {' '.join(rhs)}, absorb({' '.join(fixed_effects)})"
    else:
        command = f"{estimator} {dependent_var} {' '.join(rhs)}"
        if fixed_effects:
            command += " " + " ".join(f"i.{item}" for item in fixed_effects)
    if cluster_var:
        command += f", vce(cluster {cluster_var})"

    warnings = []
    if missing:
        warnings.append(f"Missing variables in the active dataset: {', '.join(missing)}")
    if estimator == "regress" and fixed_effects and len(fixed_effects) > 1:
        warnings.append("Multiple high-dimensional fixed effects may require reghdfe instead of regress.")
    if not cluster_var:
        warnings.append("No cluster variable supplied; confirm whether robust or clustered SEs are needed.")

    envelope = _build_envelope(
        tool="stata_estimation_plan",
        success=not missing,
        session_id=session_id,
        data={
            "command": command.strip(),
            "dependent_var": dependent_var,
            "independent_vars": independent_vars,
            "controls": controls or [],
            "fixed_effects": fixed_effects or [],
            "cluster_var": cluster_var,
            "missing_variables": missing,
            "preflight_checks": [
                "Verify sample restrictions and missingness for all regressors.",
                "Confirm the intended standard error estimator and cluster level.",
                "Inspect coefficient units and sign expectations before interpreting output.",
            ],
        },
        warnings=warnings,
        next_actions=["Run the returned command with stata_run and then inspect stata_get_results."],
    )
    return _envelope_legacy_json(envelope) if as_json else envelope


@mcp.tool(structured_output=True)
@log_call
async def stata_compare_specs(
    base_command: str,
    alternative_commands: list[str],
    session_id: str = "default",
    as_json: bool = False,
) -> ToolEnvelope | str:
    """Run multiple estimation commands and compare their stored result summaries."""
    commands = [base_command, *alternative_commands]
    comparisons = []
    artifacts: list[ArtifactRef] = []

    for idx, command in enumerate(commands):
        result = await _run_structured_command(session_id, command, strip_smcl=True)
        item = {
            "label": "baseline" if idx == 0 else f"alternative_{idx}",
            "command": command,
            "success": result.success,
            "rc": result.rc,
            "stdout": _truncate_text(result.stdout, limit=1500),
            "log_path": result.log_path,
        }
        if result.success:
            item["results"] = await _estimation_snapshot(session_id)
        else:
            item["error"] = result.error.model_dump() if result.error else None
        comparisons.append(item)
        artifact = _artifact_from_path(result.log_path, kind="log", title=item["label"])
        if artifact:
            artifacts.append(artifact)

    envelope = _build_envelope(
        tool="stata_compare_specs",
        success=all(item["success"] for item in comparisons),
        session_id=session_id,
        data={"comparisons": comparisons},
        artifacts=artifacts,
        warnings=["Review coefficient comparability manually when commands change samples or estimators."],
        next_actions=["Use stata_publication_check on the preferred specification before write-up."],
    )
    return _envelope_legacy_json(envelope) if as_json else envelope


@mcp.tool(structured_output=True)
@log_call
async def stata_publication_check(
    session_id: str = "default",
    graph_names: Optional[list[str]] = None,
    as_json: bool = False,
) -> ToolEnvelope | str:
    """Review active estimation results and graphs for publication readiness."""
    graphs_payload = GraphListResponse.model_validate(
        await (await session_manager.get_or_create_session(session_id)).call("list_graphs", {})
    ).model_dump()
    results_envelope = await stata_get_results(session_id=session_id, include_matrices=False, as_json=False)
    results_data = results_envelope.data if isinstance(results_envelope, ToolEnvelope) else {}

    warnings = []
    if not graphs_payload["graphs"]:
        warnings.append("No graphs are currently in memory.")
    if graph_names:
        present = {item["name"] for item in graphs_payload["graphs"]}
        missing = sorted(set(graph_names) - present)
        if missing:
            warnings.append(f"Requested graphs not in memory: {', '.join(missing)}")
    e_part = results_data.get("e", {}) if isinstance(results_data, dict) else {}
    if not e_part.get("depvar"):
        warnings.append("No active estimation results were found in e().")

    envelope = _build_envelope(
        tool="stata_publication_check",
        success=True,
        session_id=session_id,
        data={
            "stored_results": results_data,
            "graphs": graphs_payload["graphs"],
            "checklist": [
                "Confirm table notes, units, and significance notation.",
                "Check graph titles, axis labels, legends, and export formats.",
                "Document sample restrictions, clustering, and fixed effects in notes.",
            ],
        },
        warnings=warnings,
        next_actions=["Export the final figures with stata_manage_graphs once labels and notes are final."],
    )
    return _envelope_legacy_json(envelope) if as_json else envelope


@mcp.tool(structured_output=True)
@log_call
async def stata_project_reproducibility_report(
    session_id: str = "default",
    project_root: Optional[str] = None,
    as_json: bool = False,
) -> ToolEnvelope | str:
    """Summarize project reproducibility signals, environment state, and recent task history."""
    detect = await stata_manage_session(action="detect", include_packages=True, session_id=session_id, as_json=False)
    sessions = await stata_manage_session(action="list", session_id=session_id, as_json=False)
    manifest = _project_manifest_data()
    logs = await _recent_session_logs(session_id)
    root = str(Path(project_root).resolve()) if project_root else str(REPO_ROOT)

    envelope = _build_envelope(
        tool="stata_project_reproducibility_report",
        success=True,
        session_id=session_id,
        data={
            "project_root": root,
            "manifest": manifest,
            "environment": detect.data if isinstance(detect, ToolEnvelope) else detect,
            "sessions": sessions.data if isinstance(sessions, ToolEnvelope) else sessions,
            "recent_logs": logs,
            "startup_env": {
                "STATA_PATH": os.getenv("STATA_PATH"),
                "MCP_STATA_STARTUP_DO_FILE": os.getenv("MCP_STATA_STARTUP_DO_FILE"),
                "MCP_STATA_TEMP": os.getenv("MCP_STATA_TEMP"),
            },
        },
        next_actions=[
            "Archive this report alongside replication notes before sharing with coauthors.",
            "Run the scored eval suite after major workflow changes.",
        ],
    )
    return _envelope_legacy_json(envelope) if as_json else envelope


@mcp.prompt(name="replicate_result", description="Prompt template for replication and robustness checks.")
def replicate_result_prompt(claim: str, dataset_path: str = "", target_table: str = "") -> str:
    return (
        "Replicate the requested empirical result with mcp-stata.\n"
        f"Claim: {claim}\n"
        f"Dataset: {dataset_path or '[active dataset or supplied path]'}\n"
        f"Target table/figure: {target_table or '[unspecified]'}\n"
        "Establish the baseline, record any sample differences, compare alternative specifications, "
        "and report whether the claim fully replicates, partially matches, or fails."
    )


@mcp.prompt(name="audit_dataset", description="Prompt template for structured dataset audits.")
def audit_dataset_prompt(dataset_context: str = "", focus_variables: str = "") -> str:
    return (
        "Audit the dataset with mcp-stata before estimation.\n"
        f"Context: {dataset_context or '[unspecified]'}\n"
        f"Focus variables: {focus_variables or '[all core analysis variables]'}\n"
        "Check structure, labels, missingness, suspicious values, duplicate identifiers, and documentation readiness."
    )


@mcp.prompt(name="review_table", description="Prompt template for publication-quality table review.")
def review_table_prompt(table_goal: str, specification_notes: str = "") -> str:
    return (
        "Review the table or regression output for publication readiness.\n"
        f"Goal: {table_goal}\n"
        f"Specification notes: {specification_notes or '[none supplied]'}\n"
        "Focus on labels, notes, standard errors, fixed effects disclosure, and whether the output can go into a paper draft."
    )


@mcp.prompt(name="debug_do_file", description="Prompt template for debugging failing Stata code.")
def debug_do_file_prompt(file_path: str, failure_context: str = "") -> str:
    return (
        "Debug the Stata script with mcp-stata.\n"
        f"File: {file_path}\n"
        f"Failure context: {failure_context or '[not provided]'}\n"
        "Reproduce the failure, identify the root cause, inspect the log, and propose the smallest safe fix."
    )


@mcp.prompt(name="design_causal_spec", description="Prompt template for causal design review.")
def design_causal_spec_prompt(research_question: str, design: str = "", treatment: str = "") -> str:
    return (
        "Design or critique the causal specification with mcp-stata.\n"
        f"Research question: {research_question}\n"
        f"Design: {design or '[unspecified]'}\n"
        f"Treatment/outcome: {treatment or '[unspecified]'}\n"
        "Clarify identification, diagnostics, threats to validity, and the right sequence of estimation and robustness checks."
    )


@mcp.prompt(name="prepare_referee_response", description="Prompt template for referee-response reruns.")
def prepare_referee_response_prompt(referee_comment: str, requested_output: str = "") -> str:
    return (
        "Prepare a referee-response workflow with mcp-stata.\n"
        f"Comment: {referee_comment}\n"
        f"Requested output: {requested_output or '[unspecified]'}\n"
        "Plan the reruns, evidence collection, and concise explanation needed to answer the critique defensibly."
    )


@mcp.resource("stata://data/summary")
async def get_summary() -> str:
    """Returns output of summarize."""
    result = await _run_structured_command("default", "summarize", strip_smcl=True, echo=True)
    envelope = _command_result_envelope("resource:data_summary", "default", result)
    return envelope.model_dump_json(exclude_none=True)

@mcp.resource("stata://data/metadata")
async def get_metadata() -> str:
    """Returns output of describe."""
    result = await _run_structured_command("default", "describe", strip_smcl=True, echo=True)
    envelope = _command_result_envelope("resource:data_metadata", "default", result)
    return envelope.model_dump_json(exclude_none=True)

@mcp.resource("stata://graphs/list")
@log_call
async def list_graphs_resource() -> str:
    """Resource wrapper for the graph list."""
    return await stata_manage_graphs(action="list", session_id="default", as_json=True)

@mcp.resource("stata://variables/list")
async def get_variable_list_resource() -> str:
    """Resource wrapper for the variable list."""
    return await stata_inspect_data(action="list", session_id="default", as_json=True)

@mcp.resource("stata://results/stored")
async def get_stored_results_resource() -> str:
    """Returns stored r() and e() results."""
    return await stata_get_results(session_id="default", as_json=True)

@mcp.resource("stata://project/manifest")
async def project_manifest_resource() -> str:
    """Returns project-level metadata for the current mcp-stata installation."""
    return json.dumps(_project_manifest_data())

@mcp.resource("stata://session/{session_id}/state")
async def session_state_resource(session_id: str) -> str:
    """Returns a composite snapshot of the requested session state."""
    history = await stata_manage_session(action="history_stats", session_id=session_id, as_json=False)
    variables = await stata_inspect_data(action="list", session_id=session_id, as_json=False)
    results = await stata_get_results(session_id=session_id, include_matrices=False, as_json=False)
    payload = {
        "session_id": session_id,
        "history": history.data if isinstance(history, ToolEnvelope) else history,
        "variables": variables.data if isinstance(variables, ToolEnvelope) else variables,
        "stored_results": results.data if isinstance(results, ToolEnvelope) else results,
    }
    return json.dumps(payload)

@mcp.resource("stata://session/{session_id}/logs")
async def session_logs_resource(session_id: str) -> str:
    """Returns recent background log references for the requested session."""
    return json.dumps({"session_id": session_id, "logs": await _recent_session_logs(session_id)})

@mcp.resource("stata://session/{session_id}/graphs")
async def session_graphs_resource(session_id: str) -> str:
    """Returns graph metadata for the requested session."""
    return await stata_manage_graphs(action="list", session_id=session_id, as_json=True)

@mcp.resource("stata://research/checklists/{topic}")
async def research_checklist_resource(topic: str) -> str:
    """Returns a packaged checklist or workflow reference for a research topic."""
    return _read_reference_text(topic)

@mcp.resource("stata://evals/report/latest")
async def eval_latest_resource() -> str:
    """Returns the most recent eval report if one has been generated."""
    reports_dir = REPO_ROOT / "plugin" / "evals" / "reports"
    if not reports_dir.exists():
        return json.dumps({"status": "missing", "message": "No eval reports have been generated yet."})
    candidates = sorted(reports_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return json.dumps({"status": "missing", "message": "No eval reports have been generated yet."})
    latest = candidates[0]
    return json.dumps({"status": "ok", "path": str(latest), "report": json.loads(latest.read_text())})

@mcp.resource("stata://skills/list")
async def list_skills_resource() -> str:
    """Returns manifest-backed metadata for packaged mcp-stata skills."""
    skills = []
    for item in SKILLS:
        skills.append(
            {
                "id": item["id"],
                "name": item["name"],
                "description": item["description"],
                "version": item["version"],
                "supported_agents": item["supported_agents"],
                "trigger_text": item["trigger_text"],
                "invocation_type": item["invocation_type"],
                "resource_uri": f"stata://skills/{item['id']}",
            }
        )
    return json.dumps({"skills": skills, "count": len(skills)})

@mcp.resource("stata://skills/{skill_path}")
async def get_skill_content(skill_path: str) -> str:
    """Returns the full Markdown content of a specific packaged skill."""
    if ".." in skill_path or skill_path.startswith("/"):
        raise ValueError("Invalid skill path")
    doc = SKILL_BY_ID.get(skill_path)
    if not doc:
        raise ValueError(f"Skill not found: {skill_path}")
    return doc["content"]

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
