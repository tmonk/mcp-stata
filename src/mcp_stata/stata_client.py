from __future__ import annotations
import asyncio
import io
import inspect
import json
import logging
import os
import pathlib
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import functools
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from importlib.metadata import PackageNotFoundError, version
from io import StringIO
from typing import Any, Awaitable, Callable, Dict, Generator, List, Optional, Tuple

import anyio
from anyio import get_cancelled_exc_class

from .discovery import find_stata_candidates
from .config import MAX_LIMIT
from .models import (
    CommandResponse,
    ErrorEnvelope,
    GraphExport,
    GraphExportResponse,
    GraphInfo,
    GraphListResponse,
    VariableInfo,
    VariablesResponse,
)
from .smcl.smcl2html import smcl_to_markdown
from .streaming_io import FileTeeIO, TailBuffer
from .graph_detector import StreamingGraphCache
from .native_ops import fast_scan_log, compute_filter_indices
from .utils import get_writable_temp_dir, register_temp_file, register_temp_dir, is_windows

logger = logging.getLogger("mcp_stata")

_POLARS_AVAILABLE: Optional[bool] = None
_GRAPH_NAME_PATTERN = re.compile(r"name\(\s*(\"[^\"]+\"|'[^']+'|[^,\)\s]+)", re.IGNORECASE)

def _check_polars_available() -> bool:
    """
    Check if Polars can be safely imported.
    Must detect problematic platforms BEFORE attempting import,
    since the crash is a fatal signal, not a catchable exception.
    """
    if sys.platform == "win32" and platform.machine().lower() in ("arm64", "aarch64"):
        return False
    
    try:
        import polars  # noqa: F401
        return True
    except ImportError:
        return False


def _get_polars_available() -> bool:
    global _POLARS_AVAILABLE
    if _POLARS_AVAILABLE is None:
        _POLARS_AVAILABLE = _check_polars_available()
    return _POLARS_AVAILABLE

# ============================================================================
# MODULE-LEVEL DISCOVERY CACHE
# ============================================================================
# This cache ensures Stata discovery runs exactly once per process lifetime
_discovery_lock = threading.Lock()
_discovery_result: Optional[Tuple[str, str]] = None  # (path, edition)
_discovery_candidates: Optional[List[Tuple[str, str]]] = None
_discovery_attempted = False
_discovery_error: Optional[Exception] = None


def _get_discovery_candidates() -> List[Tuple[str, str]]:
    """
    Get ordered discovery candidates, running discovery only once.
    
    Returns:
        List of (stata_executable_path, edition) ordered by preference.
    
    Raises:
        RuntimeError: If Stata discovery fails
    """
    global _discovery_result, _discovery_candidates, _discovery_attempted, _discovery_error
    
    with _discovery_lock:
        # If we've already successfully discovered Stata, return cached result
        if _discovery_result is not None:
            return _discovery_candidates or [_discovery_result]
        
        if _discovery_candidates is not None:
            return _discovery_candidates
        
        # If we've already attempted and failed, re-raise the cached error
        if _discovery_attempted and _discovery_error is not None:
            raise RuntimeError(f"Stata binary not found: {_discovery_error}") from _discovery_error
        
        # This is the first attempt - run discovery
        _discovery_attempted = True
        
        try:
            # Log environment state once at first discovery
            env_path = os.getenv("STATA_PATH")
            if env_path:
                logger.info("STATA_PATH env provided (raw): %s", env_path)
            else:
                logger.info("STATA_PATH env not set; attempting auto-discovery")
            
            # Run discovery
            candidates = find_stata_candidates()
            
            # Cache the successful result
            _discovery_candidates = candidates
            if candidates:
                _discovery_result = candidates[0]
                logger.info("Discovery found Stata at: %s (%s)", _discovery_result[0], _discovery_result[1])
            else:
                raise FileNotFoundError("No Stata candidates discovered")
            
            return candidates
            
        except FileNotFoundError as e:
            _discovery_error = e
            raise RuntimeError(f"Stata binary not found: {e}") from e
        except PermissionError as e:
            _discovery_error = e
            raise RuntimeError(
                f"Stata binary is not executable: {e}. "
                "Point STATA_PATH directly to the Stata binary (e.g., .../Contents/MacOS/stata-mp)."
            ) from e


def _get_discovered_stata() -> Tuple[str, str]:
    """
    Preserve existing API: return the highest-priority discovered Stata candidate.
    """
    candidates = _get_discovery_candidates()
    if not candidates:
        raise RuntimeError("Stata binary not found: no candidates discovered")
    return candidates[0]


class StataClient:
    _initialized = False
    _exec_lock: threading.Lock
    _cache_init_lock = threading.Lock()  # Class-level lock for cache initialization
    _is_executing = False  # Flag to prevent recursive Stata calls
    MAX_DATA_ROWS = MAX_LIMIT
    MAX_GRAPH_BYTES = 50 * 1024 * 1024  # Maximum graph exports (~50MB)
    MAX_CACHE_SIZE = 100  # Maximum number of graphs to cache
    MAX_CACHE_BYTES = 500 * 1024 * 1024  # Maximum cache size in bytes (~500MB)
    LIST_GRAPHS_TTL = 0.075  # TTL for list_graphs cache (75ms)

    def __init__(self):
        self._exec_lock = threading.RLock()
        self._is_executing = False
        self._command_idx = 0  # Counter for user-initiated commands
        self._initialized = False
        self._persistent_log_path = None
        self._persistent_log_name = None
        self._last_emitted_graph_signatures: Dict[str, str] = {}
        self._graph_signature_cache: Dict[str, str] = {}
        self._graph_signature_cache_cmd_idx: Optional[int] = None
        self._last_results = None
        from .graph_detector import GraphCreationDetector
        self._graph_detector = GraphCreationDetector(self)

    def __new__(cls):
        inst = super(StataClient, cls).__new__(cls)
        inst._exec_lock = threading.RLock()
        inst._is_executing = False
        inst._command_idx = 0
        inst._initialized = False
        inst._persistent_log_path = None
        inst._persistent_log_name = None
        inst._graph_signature_cache = {}
        inst._graph_signature_cache_cmd_idx = None
        inst._last_results = None
        from .graph_detector import GraphCreationDetector
        inst._graph_detector = GraphCreationDetector(inst)
        return inst

    def _increment_command_idx(self) -> int:
        """Increment and return the command counter."""
        self._command_idx += 1
        self._graph_signature_cache = {}
        self._graph_signature_cache_cmd_idx = self._command_idx
        return self._command_idx

    @contextmanager
    def _redirect_io(self, out_buf, err_buf):
        """Safely redirect stdout/stderr for the duration of a Stata call."""
        backup_stdout, backup_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out_buf, err_buf
        try:
            yield
        finally:
            sys.stdout, sys.stderr = backup_stdout, backup_stderr


    @staticmethod
    def _stata_quote(value: str) -> str:
        """Return a Stata double-quoted string literal for value."""
        # Stata uses doubled quotes to represent a quote character inside a string.
        v = (value or "")
        v = v.replace('"', '""')
        # Use compound double quotes to avoid tokenization issues with spaces and
        # punctuation in contexts like graph names.
        return f'`"{v}"\''

    @contextmanager
    def _redirect_io_streaming(self, out_stream, err_stream):
        backup_stdout, backup_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out_stream, err_stream
        try:
            yield
        finally:
            sys.stdout, sys.stderr = backup_stdout, backup_stderr

    @staticmethod
    def _safe_unlink(path: str) -> None:
        if not path:
            return
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass

    def _create_smcl_log_path(
        self,
        *,
        prefix: str = "mcp_smcl_",
        max_hex: Optional[int] = None,
        base_dir: Optional[str] = None,
    ) -> str:
        hex_id = uuid.uuid4().hex if max_hex is None else uuid.uuid4().hex[:max_hex]
        # Use provided base_dir if any, otherwise fall back to validated temp dir
        base = pathlib.Path(base_dir) if base_dir else pathlib.Path(get_writable_temp_dir())
        smcl_path = base / f"{prefix}{hex_id}.smcl"
        register_temp_file(smcl_path)
        self._safe_unlink(str(smcl_path))
        return str(smcl_path)

    @staticmethod
    def _make_smcl_log_name() -> str:
        return f"_mcp_smcl_{uuid.uuid4().hex[:8]}"

    def _run_internal(self, code: str, echo: bool = False) -> str:
        """Run Stata code while strictly ensuring NO output reaches stdout."""
        if not self._initialized:
            self.init()
        with self._exec_lock:
            with redirect_stdout(sys.stderr), redirect_stderr(sys.stderr):
                return self.stata.run(code, echo=echo)

    def _open_smcl_log(self, smcl_path: str, log_name: str, *, quiet: bool = False, append: bool = False) -> bool:
        path_for_stata = smcl_path.replace("\\", "/")
        mode = "append" if append else "replace"
        base_cmd = f"log using \"{path_for_stata}\", {mode} smcl name({log_name})"
        
        # In multi-threaded environments (like pytest-xdist), we must be extremely
        # careful with the singleton Stata instance.
        from sfi import Scalar
        
        try:
            # Bundle both close and open to minimize roundtrips
            # Use a unique scalar to capture the RC of the log using command
            log_rc_scalar = f"_mcp_log_rc_{uuid.uuid4().hex[:8]}"
            bundle = (
                f"capture quietly log close {log_name}\n"
                f"capture {'quietly ' if quiet else ''}{base_cmd}\n"
                f"scalar {log_rc_scalar} = _rc"
            )
            logger.debug(f"Opening SMCL log with bundle: {bundle}")
            self._run_internal(bundle, echo=False)
            
            try:
                rc_val = Scalar.getValue(log_rc_scalar)
                logger.debug(f"Log RC: {rc_val}")
                # Clean up scalar
                self._run_internal(f"capture scalar drop {log_rc_scalar}", echo=False)
                if rc_val == 0:
                    self._last_smcl_log_named = True
                    return True
            except Exception as e:
                logger.debug(f"Failed to get log scalar {log_rc_scalar}: {e}")
                pass
            
            # If still not open, try clearing other logs and retry
            log_rc_scalar = f"_mcp_log_rc_retry_{uuid.uuid4().hex[:8]}"
            bundle = (
                "capture quietly log close\n"
                f"capture {'quietly ' if quiet else ''}{base_cmd}\n"
                f"scalar {log_rc_scalar} = _rc"
            )
            logger.debug(f"Retrying SMCL log with bundle: {bundle}")
            self._run_internal(bundle, echo=False)
            
            try:
                rc_val = Scalar.getValue(log_rc_scalar)
                logger.debug(f"Retry Log RC: {rc_val}")
                # Clean up scalar
                self._run_internal(f"capture scalar drop {log_rc_scalar}", echo=False)
                if rc_val == 0:
                    self._last_smcl_log_named = True
                    return True
            except Exception as e:
                logger.debug(f"Failed to get retry log scalar {log_rc_scalar}: {e}")
                pass
                
        except Exception as e:
            logger.warning("SMCL log open exception: %s", e)
            
        return False
            
        # Fallback to unnamed log
        try:
            unnamed_cmd = f"{'quietly ' if quiet else ''}log using \"{path_for_stata}\", replace smcl"
            self._run_internal(f"capture quietly log close", echo=False)
            self._run_internal(f"capture {unnamed_cmd}", echo=False)
            try:
                if Scalar.getValue("c(log)") == "on":
                    self._last_smcl_log_named = False
                    return True
            except:
                pass
        except Exception:
            pass
        return False

    def _close_smcl_log(self, log_name: str) -> None:
        if log_name == "_mcp_session":
            return
        try:
            use_named = getattr(self, "_last_smcl_log_named", None)
            if use_named is False:
                self._run_internal("capture quietly log close", echo=False)
            else:
                self._run_internal(f"capture quietly log close {log_name}", echo=False)
        except Exception:
            pass

    def _restore_results_from_hold(self, hold_attr: str) -> None:
        if not hasattr(self, hold_attr):
            return
        hold_name = getattr(self, hold_attr)
        try:
            self._run_internal(f"capture _return restore {hold_name}", echo=False)
            self._last_results = None # Invalidate cache instead of fetching
        except Exception:
            pass
        finally:
            try:
                delattr(self, hold_attr)
            except Exception:
                pass

    def _create_streaming_log(self, *, trace: bool) -> tuple[tempfile.NamedTemporaryFile, str, TailBuffer, FileTeeIO]:
        log_file = tempfile.NamedTemporaryFile(
            prefix="mcp_stata_",
            suffix=".log",
            dir=get_writable_temp_dir(),
            delete=False,
            mode="w",
            encoding="utf-8",
            errors="replace",
            buffering=1,
        )
        log_path = log_file.name
        register_temp_file(log_path)
        tail = TailBuffer(max_chars=200000 if trace else 20000)
        tee = FileTeeIO(log_file, tail)
        return log_file, log_path, tail, tee

    def _init_streaming_graph_cache(
        self,
        auto_cache_graphs: bool,
        on_graph_cached: Optional[Callable[[str, bool], Awaitable[None]]],
        notify_log: Callable[[str], Awaitable[None]],
    ) -> Optional[StreamingGraphCache]:
        if not auto_cache_graphs:
            return None
        graph_cache = StreamingGraphCache(self, auto_cache=True)
        graph_cache_callback = self._create_graph_cache_callback(on_graph_cached, notify_log)
        graph_cache.add_cache_callback(graph_cache_callback)
        return graph_cache

    def _capture_graph_state(
        self,
        graph_cache: Optional[StreamingGraphCache],
        emit_graph_ready: bool,
    ) -> Optional[dict[str, str]]:
        # Capture initial graph state BEFORE execution starts
        self._graph_signature_cache = {}
        self._graph_signature_cache_cmd_idx = None
        graph_names: List[str] = []
        if graph_cache or emit_graph_ready:
            try:
                graph_names = list(self.list_graphs(force_refresh=True))
            except Exception as e:
                logger.debug("Failed to capture initial graph state: %s", e)
                graph_names = []

        if graph_cache:
            # Clear detection state for the new command (detected/removed sets)
            # but preserve _last_graph_state signatures for modification detection.
            graph_cache.detector.clear_detection_state()
            graph_cache._initial_graphs = set(graph_names)
            logger.debug(f"Initial graph state captured: {graph_cache._initial_graphs}")

        graph_ready_initial = None
        if emit_graph_ready:
            graph_ready_initial = {name: self._get_graph_signature(name) for name in graph_names}
            logger.debug("Graph-ready initial state captured: %s", set(graph_ready_initial))
        return graph_ready_initial

    async def _cache_new_graphs(
        self,
        graph_cache: Optional[StreamingGraphCache],
        *,
        notify_progress: Optional[Callable[[float, Optional[float], Optional[str]], Awaitable[None]]],
        total_lines: int,
        completed_label: str,
    ) -> None:
        if not graph_cache or not graph_cache.auto_cache:
            return
        try:
            cached_graphs = []
            # Use detector to find new OR modified graphs
            pystata_detected = await anyio.to_thread.run_sync(graph_cache.detector._detect_graphs_via_pystata)
            
            # Combine with any pending graphs in queue
            with graph_cache._lock:
                to_process = set(pystata_detected) | set(graph_cache._graphs_to_cache)
                graph_cache._graphs_to_cache.clear()
            
            if to_process:
                logger.info(f"Detected {len(to_process)} new or modified graph(s): {sorted(to_process)}")

            for graph_name in to_process:
                if graph_name in graph_cache._cached_graphs:
                    continue
                    
                try:
                    cache_result = await anyio.to_thread.run_sync(
                        self.cache_graph_on_creation,
                        graph_name,
                    )
                    if cache_result:
                        cached_graphs.append(graph_name)
                        graph_cache._cached_graphs.add(graph_name)

                    for callback in graph_cache._cache_callbacks:
                        try:
                            result = callback(graph_name, cache_result)
                            if inspect.isawaitable(result):
                                await result
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"Error caching graph {graph_name}: {e}")

            if cached_graphs and notify_progress:
                await notify_progress(
                    float(total_lines) if total_lines > 0 else 1,
                    float(total_lines) if total_lines > 0 else 1,
                    f"{completed_label} completed. Cached {len(cached_graphs)} graph(s): {', '.join(cached_graphs)}",
                )
        except Exception as e:
            logger.error(f"Post-execution graph detection failed: {e}")

    def _emit_graph_ready_task(
        self,
        *,
        emit_graph_ready: bool,
        graph_ready_initial: Optional[dict[str, str]],
        notify_log: Callable[[str], Awaitable[None]],
        graph_ready_task_id: Optional[str],
        graph_ready_format: str,
    ) -> None:
        if emit_graph_ready and graph_ready_initial is not None:
            try:
                asyncio.create_task(
                    self._emit_graph_ready_events(
                        graph_ready_initial,
                        notify_log,
                        graph_ready_task_id,
                        graph_ready_format,
                    )
                )
            except Exception as e:
                logger.warning("graph_ready emission failed to start: %s", e)

    async def _stream_smcl_log(
        self,
        *,
        smcl_path: str,
        notify_log: Callable[[str], Awaitable[None]],
        done: anyio.Event,
        on_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
        start_offset: int = 0,
        tee: Optional[FileTeeIO] = None,
    ) -> None:
        last_pos = start_offset
        emitted_debug_chunks = 0
        # Wait for Stata to create the SMCL file
        while not done.is_set() and not os.path.exists(smcl_path):
            await anyio.sleep(0.05)

        try:
            def _read_content() -> str:
                try:
                    with open(smcl_path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_pos)
                        return f.read()
                except PermissionError:
                    if is_windows():
                        try:
                            # Use 'type' on Windows to bypass exclusive lock
                            res = subprocess.run(f'type "{smcl_path}"', shell=True, capture_output=True)
                            full_content = res.stdout.decode("utf-8", errors="replace")
                            if len(full_content) > last_pos:
                                return full_content[last_pos:]
                            return ""
                        except Exception:
                            return ""
                    return ""
                except FileNotFoundError:
                    return ""

            while not done.is_set():
                chunk = await anyio.to_thread.run_sync(_read_content)
                if chunk:
                    is_first_chunk = last_pos == start_offset
                    last_pos += len(chunk)
                    # Clean chunk before sending to log channel to suppress maintenance leakage
                    cleaned_chunk = self._clean_internal_smcl(
                        chunk,
                        strip_output=False,
                        strip_leading_boilerplate=is_first_chunk,
                    )
                    if cleaned_chunk:
                        try:
                            await notify_log(cleaned_chunk)
                        except Exception as exc:
                            logger.debug("notify_log failed: %s", exc)
                        
                        if tee:
                            try:
                                # Write cleaned SMCL to tee to satisfy requirements 
                                # for clean logs with preserved markup. 
                                tee.write(cleaned_chunk)
                            except Exception:
                                pass

                    if on_chunk is not None:
                        try:
                            await on_chunk(chunk)
                        except Exception as exc:
                            logger.debug("on_chunk callback failed: %s", exc)
                await anyio.sleep(0.05)

            # Final check for any remaining content
            chunk = await anyio.to_thread.run_sync(_read_content)
            if chunk:
                last_pos += len(chunk)
                cleaned_chunk = self._clean_internal_smcl(
                    chunk,
                    strip_output=False,
                    strip_leading_boilerplate=False,
                )
                if cleaned_chunk:
                    try:
                        await notify_log(cleaned_chunk)
                    except Exception as exc:
                        logger.debug("final notify_log failed: %s", exc)
                    
                    if tee:
                        try:
                            # Write cleaned SMCL to tee
                            tee.write(cleaned_chunk)
                        except Exception:
                            pass
            
            if on_chunk is not None:
                # Final check even if last chunk is empty, to ensure 
                # graphs created at the very end are detected.
                try:
                    await on_chunk(chunk or "")
                except Exception as exc:
                    logger.debug("final on_chunk check failed: %s", exc)

        except Exception as e:
            logger.warning(f"Log streaming failed: {e}")

    def _run_streaming_blocking(
        self,
        *,
        command: str,
        tee: FileTeeIO,
        cwd: Optional[str],
        trace: bool,
        echo: bool,
        smcl_path: str,
        smcl_log_name: str,
        hold_attr: str,
        require_smcl_log: bool = False,
    ) -> tuple[int, Optional[Exception]]:
        rc = -1
        exc: Optional[Exception] = None
        with self._exec_lock:
            self._is_executing = True
            self._last_results = None # Invalidate results cache
            try:
                from sfi import Scalar, SFIToolkit  # Import SFI tools
                with self._temp_cwd(cwd):
                    logger.debug(
                        "opening SMCL log name=%s path=%s cwd=%s",
                        smcl_log_name,
                        smcl_path,
                        os.getcwd(),
                    )
                    try:
                        if self._persistent_log_path and smcl_path == self._persistent_log_path:
                            # Re-open or resume global session log in append mode to ensure it's active
                            log_opened = self._open_smcl_log(smcl_path, smcl_log_name, quiet=True, append=True)
                        else:
                            log_opened = self._open_smcl_log(smcl_path, smcl_log_name, quiet=True)
                    except Exception as e:
                        log_opened = False
                        logger.warning("_open_smcl_log raised: %r", e)
                    logger.info("SMCL log_opened=%s path=%s", log_opened, smcl_path)
                    if require_smcl_log and not log_opened:
                        exc = RuntimeError("Failed to open SMCL log")
                        logger.error("SMCL log open failed for %s", smcl_path)
                        rc = 1
                    if exc is None:
                        try:
                            # Use an internal buffer to capture the direct output of pystata
                            # rather than writing it raw to the 'tee' (and log_path). 
                            # We rely on _stream_smcl_log to populate the 'tee' with 
                            # cleaned content from the SMCL log.
                            direct_buf = io.StringIO()
                            with self._redirect_io_streaming(direct_buf, direct_buf):
                                try:
                                    if trace:
                                        self.stata.run("set trace on")
                                    
                                    # Hybrid execution: Single-line commands run natively for perfect echoing.
                                    # Multi-line commands use the bundle for error handling and stability.
                                    is_multi_line = "\n" in command.strip()
                                    
                                    if not is_multi_line:
                                        logger.debug("running Stata natively echo=%s", echo)
                                        self._hold_name_stream = f"mcp_hold_{uuid.uuid4().hex[:8]}"
                                        # Reset RC to 0 before running
                                        self._run_internal("scalar _mcp_rc = 0", echo=False)
                                        ret = self.stata.run(command, echo=echo)
                                        # Use _rc if we were in a capture, but here we are native.
                                        # Stata sets c(rc) to the return code of the last command.
                                        self._run_internal(f"scalar _mcp_rc = c(rc)", echo=False)
                                        self._run_internal(f"capture _return hold {self._hold_name_stream}", echo=False)
                                        self._run_internal(f"capture quietly log flush {smcl_log_name}", echo=False)
                                        
                                        # Retrieve RC via SFI
                                        try:
                                            rc_val = Scalar.getValue("_mcp_rc")
                                            rc = int(float(rc_val)) if rc_val is not None else 0
                                        except:
                                            rc = 0
                                    else:
                                        # Optimization: Combined bundle for streaming too.
                                        # Consolidates hold and potentially flush into one call.
                                        self._hold_name_stream = f"mcp_hold_{uuid.uuid4().hex[:8]}"
                                        
                                        # Initialization logic for locals can be sensitive.
                                        # Since each run() in pystata starts a new context for locals unless it's a file,
                                        # we use a global scalar for the return code.
                                        # We use noisily inside the capture block to force echo of commands if requested.
                                        bundle = (
                                            f"capture noisily {{\n"
                                            f"{'noisily {' if echo else ''}\n"
                                            f"{command}\n"
                                            f"{'}' if echo else ''}\n"
                                            f"}}\n"
                                            f"scalar _mcp_rc = _rc\n"
                                            f"capture _return hold {self._hold_name_stream}\n"
                                            f"capture quietly log flush {smcl_log_name}"
                                        )
                                        
                                        logger.debug("running Stata bundle echo=%s", echo)
                                        # Using direct stata.run because tee redirection is already active
                                        ret = self.stata.run(bundle, echo=echo)
                                        
                                        # Retrieve RC via SFI for accuracy
                                        try:
                                            rc_val = Scalar.getValue("_mcp_rc")
                                            rc = int(float(rc_val)) if rc_val is not None else 0
                                        except:
                                            rc = 0
                                        
                                    if isinstance(ret, str) and ret:
                                        # If for some reason SMCL log wasn't working, we can 
                                        # fall back to the raw output, but otherwise we 
                                        # avoid writing raw data to the tee.
                                        pass
                                except Exception as e:
                                    exc = e
                                    logger.error("stata.run bundle failed: %r", e)
                                    if rc in (-1, 0):
                                        parsed_rc = self._parse_rc_from_text(str(e))
                                        if parsed_rc is None:
                                            try:
                                                parsed_rc = self._parse_rc_from_text(direct_buf.getvalue())
                                            except Exception:
                                                parsed_rc = None
                                        rc = parsed_rc if parsed_rc is not None else 1
                                finally:
                                    if trace:
                                        try:
                                            self._run_internal("set trace off")
                                        except Exception:
                                            pass
                        finally:
                            # Only close if it's NOT the persistent session log
                            if not self._persistent_log_name or smcl_log_name != self._persistent_log_name:
                                self._close_smcl_log(smcl_log_name)
                            
                            self._restore_results_from_hold(hold_attr)
                            
                            # Final state restoration (invisibility)
                            try:
                                # Set c(rc) for the environment
                                self._run_internal(f"capture error {rc}" if rc > 0 else "capture", echo=False)
                            except Exception:
                                pass
                        return rc, exc
                    # If we get here, SMCL log failed and we're required to stop.
                    return rc, exc
            finally:
                self._is_executing = False
        return rc, exc

    def _resolve_do_file_path(
        self,
        path: str,
        cwd: Optional[str],
    ) -> tuple[Optional[str], Optional[str], Optional[CommandResponse]]:
        if cwd is not None and not os.path.isdir(cwd):
            return None, None, CommandResponse(
                command=f'do "{path}"',
                rc=601,
                stdout="",
                stderr=None,
                success=False,
                error=ErrorEnvelope(
                    message=f"cwd not found: {cwd}",
                    rc=601,
                    command=path,
                ),
            )

        effective_path = path
        if not os.path.isabs(path):
            effective_path = os.path.abspath(os.path.join(cwd or os.getcwd(), path))

        if not os.path.exists(effective_path):
            return None, None, CommandResponse(
                command=f'do "{effective_path}"',
                rc=601,
                stdout="",
                stderr=None,
                success=False,
                error=ErrorEnvelope(
                    message=f"Do-file not found: {effective_path}",
                    rc=601,
                    command=effective_path,
                ),
            )

        path_for_stata = effective_path.replace("\\", "/")
        command = f'do "{path_for_stata}"'
        return effective_path, command, None

    @contextmanager
    def _smcl_log_capture(self) -> "Generator[Tuple[str, str], None, None]":
        """
        Context manager that wraps command execution in a named SMCL log.
        
        This runs alongside any user logs (named logs can coexist).
        Yields (log_name, log_path) tuple for use within the context.
        The SMCL file is NOT deleted automatically - caller should clean up.
        
        Usage:
            with self._smcl_log_capture() as (log_name, smcl_path):
                self.stata.run(cmd)
            # After context, read smcl_path for raw SMCL output
        """
        # Use a unique name but DO NOT join start with mkstemp to avoid existing file locks.
        # Stata will create the file.
        smcl_path = self._create_smcl_log_path()
        # Unique log name to avoid collisions with user logs
        log_name = self._make_smcl_log_name()

        try:
            # Open named SMCL log (quietly to avoid polluting output)
            log_opened = self._open_smcl_log(smcl_path, log_name, quiet=True)
            if not log_opened:
                # Still yield, consumer might see empty file or handle error,
                # but we can't do much if Stata refuses to log.
                pass

            yield log_name, smcl_path
        finally:
            # Always close our named log
            self._close_smcl_log(log_name)
            # Ensure the persistent session log is still active after our capture.
            if self._persistent_log_path and self._persistent_log_name:
                try:
                    path_for_stata = self._persistent_log_path.replace("\\", "/")
                    mode = "append" if os.path.exists(self._persistent_log_path) else "replace"
                    reopen_cmd = (
                        f"capture quietly log using \"{path_for_stata}\", {mode} smcl name({self._persistent_log_name})"
                    )
                    self._run_internal(reopen_cmd, echo=False)
                except Exception:
                    pass

    def _read_smcl_file(self, path: str, start_offset: int = 0) -> str:
        """Read SMCL file contents, handling encoding issues, offsets and Windows file locks."""
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                if start_offset > 0:
                    f.seek(start_offset)
                return f.read()
        except PermissionError:
            if is_windows():
                # Windows Fallback: Try to use 'type' command to bypass exclusive lock
                try:
                    res = subprocess.run(f'type "{path}"', shell=True, capture_output=True)
                    if res.returncode == 0:
                        content = res.stdout.decode('utf-8', errors='replace')
                        if start_offset > 0 and len(content) > start_offset:
                            return content[start_offset:]
                        return content
                except Exception as e:
                    logger.debug(f"Combined fallback read failed: {e}")
            logger.warning(f"Failed to read SMCL file {path} due to lock")
            return ""
        except Exception as e:
            logger.warning(f"Failed to read SMCL file {path}: {e}")
            return ""

    def _read_persistent_log_chunk(self, start_offset: int) -> str:
        """Read fresh chunk from persistent SMCL log starting at offset."""
        if not self._persistent_log_path:
            return ""
        try:
            with open(self._persistent_log_path, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(start_offset)
                content = f.read()

            if not content:
                return ""

            # Use refined cleaning logic to strip internal headers and maintenance
            return self._clean_internal_smcl(content)
        except PermissionError:
            if is_windows():
                try:
                    # Windows fallback for locked persistent log
                    res = subprocess.run(f'type "{self._persistent_log_path}"', shell=True, capture_output=True)
                    if res.returncode == 0:
                        full_content = res.stdout.decode('utf-8', errors='replace')
                        if len(full_content) > start_offset:
                            return full_content[start_offset:]
                        return ""
                except Exception:
                    pass
            return ""
        except Exception:
            return ""

    def _extract_error_from_smcl(self, smcl_content: str, rc: int) -> Tuple[str, str]:
        """
        Extract error message and context from raw SMCL output.
        
        Uses {err} tags as the authoritative source for error detection.
        
        Returns:
            Tuple of (error_message, context_string)
        """
        if not smcl_content:
            return f"Stata error r({rc})", ""
        
        # Try Rust optimization
        native_res = fast_scan_log(smcl_content, rc)
        if native_res:
            error_msg, context, _ = native_res
            # If native result is specific, return it. Otherwise fall through to recover
            # a more descriptive error message from SMCL/text.
            if error_msg and error_msg != f"Stata error r({rc})":
                return error_msg, context

        lines = smcl_content.splitlines()
        
        # Search backwards for {err} tags - they indicate error lines
        error_lines = []
        error_start_idx = -1
        
        # Skip the very last few lines if they contain our cleanup noise
        # like "capture error 111" or "log flush invalid"
        internal_noise_patterns = [
            "flush invalid",
            "capture error",
            "search r(",
            "r(198);",
            "r(111);"
        ]
        
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i]
            if '{err}' in line:
                # Is this internal noise?
                is_noise = any(p in line.lower() for p in internal_noise_patterns)
                if is_noise and error_start_idx == -1:
                    # If we only have noise at the very end, we should keep looking back
                    continue

                if error_start_idx == -1:
                    error_start_idx = i
                # Walk backwards to find consecutive {err} lines
                j = i
                while j >= 0 and '{err}' in lines[j]:
                    error_lines.insert(0, lines[j])
                    j -= 1
                break
        
        if error_lines:
            # Clean SMCL tags from error message
            clean_lines = []
            for line in error_lines:
                # Remove SMCL tags but keep the text content
                cleaned = re.sub(r'\{[^}]*\}', '', line).strip()
                if cleaned:
                    clean_lines.append(cleaned)
            
            error_msg = " ".join(clean_lines) or f"Stata error r({rc})"
            
            # Context is everything from error start to end
            context_start = max(0, error_start_idx - 5)  # Include 5 lines before error
            context = "\n".join(lines[context_start:])
            
            return error_msg, context
        
        # Fallback: no {err} found, try to extract a meaningful message from text
        # (some Stata errors do not emit {err} tags in SMCL).
        try:
            text_lines = self._smcl_to_text(smcl_content).splitlines()
        except Exception:
            text_lines = []

        def _find_error_line() -> Optional[str]:
            patterns = [
                r"no variables defined",
                r"not found",
                r"variable .* not found",
                r"no observations",
            ]
            for line in reversed(text_lines):
                lowered = line.lower()
                for pat in patterns:
                    if re.search(pat, lowered):
                        return line.strip()
            return None

        extracted = _find_error_line()
        if extracted:
            error_msg = extracted
        else:
            error_msg = f"Stata error r({rc})"

        # Context: last 30 lines of SMCL
        context_start = max(0, len(lines) - 30)
        context = "\n".join(lines[context_start:])

        return error_msg, context

    def _parse_rc_from_smcl(self, smcl_content: str) -> Optional[int]:
        """Parse return code from SMCL content using specific structural patterns."""
        if not smcl_content:
            return None
            
        # Try Rust optimization
        native_res = fast_scan_log(smcl_content, 0)
        if native_res:
            _, _, rc = native_res
            if rc is not None:
                return rc

        # 1. Primary check: SMCL search tag {search r(N), ...}
        # This is the most authoritative interactive indicator
        matches = list(re.finditer(r'\{search r\((\d+)\)', smcl_content))
        if matches:
            try:
                return int(matches[-1].group(1))
            except Exception:
                pass

        # 2. Secondary check: Standalone r(N); pattern
        # This appears at the end of command blocks
        matches = list(re.finditer(r'(?<!\w)r\((\d+)\);?', smcl_content))
        if matches:
            try:
                return int(matches[-1].group(1))
            except Exception:
                pass
                
        return None

    @staticmethod
    def _create_graph_cache_callback(on_graph_cached, notify_log):
        """Create a standardized graph cache callback with proper error handling."""
        async def graph_cache_callback(graph_name: str, success: bool) -> None:
            try:
                if on_graph_cached:
                    await on_graph_cached(graph_name, success)
            except Exception as e:
                logger.error(f"Graph cache callback failed: {e}")
            
            try:
                # Also notify via log channel
                await notify_log(json.dumps({
                    "event": "graph_cached",
                    "graph": graph_name,
                    "success": success
                }))
            except Exception as e:
                logger.error(f"Failed to notify about graph cache: {e}")
        
        return graph_cache_callback

    def _get_cached_graph_path(self, graph_name: str) -> Optional[str]:
        if not hasattr(self, "_cache_lock") or not hasattr(self, "_preemptive_cache"):
            return None
        try:
            with self._cache_lock:
                cache_path = self._preemptive_cache.get(graph_name)
                if not cache_path:
                    return None
                
                # Double-check validity (e.g. signature match for current command)
                if not self._is_cache_valid(graph_name, cache_path):
                    return None
                    
                return cache_path
        except Exception:
            return None

    async def _emit_graph_ready_for_graphs(
        self,
        graph_names: List[str],
        *,
        notify_log: Callable[[str], Awaitable[None]],
        task_id: Optional[str],
        export_format: str,
        graph_ready_initial: Optional[dict[str, str]],
    ) -> int:
        if not graph_names:
            return 0
        # Deduplicate requested names while preserving order
        graph_names = list(dict.fromkeys(graph_names))
        fmt = (export_format or "svg").strip().lower()
        emitted = 0

        # Heuristic: Find active graph to help decide which existing graphs were touched.
        active_graph = None
        try:
            from sfi import Scalar
            active_graph = Scalar.getValue("c(curgraph)")
        except Exception:
            pass
        code = getattr(self, "_current_command_code", "")
        named_graphs = set(self._extract_named_graphs(code))

        for graph_name in graph_names:
            # Try to determine a stable signature before exporting; prefer cached path if present
            cached_path = self._get_cached_graph_path(graph_name) if fmt == "svg" else None
            pre_signature = self._get_graph_signature(graph_name)
            emit_key = f"{graph_name}:{self._command_idx}:{fmt}"
            
            # If we already emitted this EXACT signature in THIS command, skip.
            if self._last_emitted_graph_signatures.get(graph_name) == emit_key:
                continue

            # Emit only when the command matches the graph command or explicitly names it.
            if graph_ready_initial is not None:
                graph_cmd = self._get_graph_command_line(graph_name)
                if not self._command_contains_graph_command(code, graph_cmd or ""):
                    if graph_name not in named_graphs:
                        continue

            try:
                export_path = cached_path
                if not export_path:
                    last_exc = None
                    for attempt in range(6):
                        try:
                            export_path = await anyio.to_thread.run_sync(
                                lambda: self.export_graph(graph_name, format=fmt)
                            )
                            break
                        except Exception as exc:
                            last_exc = exc
                            if attempt < 5:
                                await anyio.sleep(0.05)
                                continue
                            raise last_exc
                if self._last_emitted_graph_signatures.get(graph_name) == emit_key:
                    continue
                payload = {
                    "event": "graph_ready",
                    "task_id": task_id,
                    "graph": {
                        "name": graph_name,
                        "path": export_path,
                        "label": graph_name,
                    },
                }
                await notify_log(json.dumps(payload))
                emitted += 1
                self._last_emitted_graph_signatures[graph_name] = emit_key
                if graph_ready_initial is not None:
                    graph_ready_initial[graph_name] = pre_signature
            except Exception as e:
                logger.warning("graph_ready export failed for %s: %s", graph_name, e)
        return emitted

    @staticmethod
    def _extract_named_graphs(text: str) -> List[str]:
        if not text:
            return []
        matches = _GRAPH_NAME_PATTERN.findall(text)
        if not matches:
            return []
        out = []
        for raw in matches:
            name = raw.strip().strip("\"").strip("'").strip()
            if name:
                out.append(name)
        return out

    async def _maybe_cache_graphs_on_chunk(
        self,
        *,
        graph_cache: Optional[StreamingGraphCache],
        emit_graph_ready: bool,
        notify_log: Callable[[str], Awaitable[None]],
        graph_ready_task_id: Optional[str],
        graph_ready_format: str,
        graph_ready_initial: Optional[dict[str, str]],
        last_check: List[float],
        force: bool = False,
    ) -> int:
        if not graph_cache or not graph_cache.auto_cache:
            return 0
        if self._is_executing and not force:
            # Skip polling if Stata is busy; it will block on _exec_lock anyway.
            # During final check (force=True), we know it's safe because _run_streaming_blocking has finished.
            return 0
        now = time.monotonic()
        if not force and last_check and now - last_check[0] < 0.75:
            return 0
        if last_check:
            last_check[0] = now
        try:
            cached_names = await graph_cache.cache_detected_graphs_with_pystata()
        except Exception as e:
            logger.debug("graph_ready polling failed: %s", e)
            return 0
        if emit_graph_ready and cached_names:
            async with self._ensure_graph_ready_lock():
                return await self._emit_graph_ready_for_graphs(
                    cached_names,
                    notify_log=notify_log,
                    task_id=graph_ready_task_id,
                    export_format=graph_ready_format,
                    graph_ready_initial=graph_ready_initial,
                )
        return 0

    def _ensure_graph_ready_lock(self) -> asyncio.Lock:
        lock = getattr(self, "_graph_ready_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._graph_ready_lock = lock
        return lock

    async def _emit_graph_ready_events(
        self,
        initial_graphs: dict[str, str],
        notify_log: Callable[[str], Awaitable[None]],
        task_id: Optional[str],
        export_format: str,
    ) -> int:
        if initial_graphs is None:
            return 0
        lock = self._ensure_graph_ready_lock()

        fmt = (export_format or "svg").strip().lower()
        emitted = 0

        # Poll briefly for new graphs after command completion; emit once per batch.
        for _ in range(5):
            try:
                current_graphs = list(self.list_graphs(force_refresh=True))
            except Exception as exc:
                logger.debug("graph_ready list_graphs failed: %s", exc)
                current_graphs = []

            if current_graphs:
                async with lock:
                    emitted += await self._emit_graph_ready_for_graphs(
                        current_graphs,
                        notify_log=notify_log,
                        task_id=task_id,
                        export_format=fmt,
                        graph_ready_initial=initial_graphs,
                    )
                break

            await anyio.sleep(0.05)

        return emitted

    def _get_graph_signature(self, graph_name: str) -> str:
        """Return a stable signature for a graph name based on graph metadata."""
        if self._graph_signature_cache_cmd_idx != self._command_idx:
            self._graph_signature_cache = {}
            self._graph_signature_cache_cmd_idx = self._command_idx

        cached = self._graph_signature_cache.get(graph_name)
        if cached:
            return cached

        signature = graph_name

        # Refresh graph metadata if we don't have created timestamps yet.
        try:
            self.list_graphs(force_refresh=True)
        except Exception:
            pass

        try:
            # Use cached graph metadata when available (created timestamp is stable).
            with self._list_graphs_cache_lock:
                cached_graphs = list(self._list_graphs_cache or [])
            for g in cached_graphs:
                if hasattr(g, "name") and g.name == graph_name and getattr(g, "created", None):
                    signature = f"{graph_name}_{g.created}"
                    break
        except Exception:
            pass

        # If still missing, attempt a targeted timestamp lookup via the graph detector.
        if signature == graph_name:
            try:
                detector = getattr(self, "_graph_detector", None)
                if detector is not None:
                    timestamps = detector._get_graph_timestamps([graph_name])
                    ts = timestamps.get(graph_name)
                    if ts:
                        signature = f"{graph_name}_{ts}"
            except Exception:
                pass

        self._graph_signature_cache[graph_name] = signature
        return signature

    @staticmethod
    def _normalize_command_text(text: str) -> str:
        return " ".join((text or "").strip().split()).lower()

    def _command_contains_graph_command(self, code: str, graph_cmd: str) -> bool:
        if not code or not graph_cmd:
            return False
        graph_norm = self._normalize_command_text(graph_cmd)
        if not graph_norm:
            return False
        graph_prefixed = f"graph {graph_norm}" if not graph_norm.startswith("graph ") else graph_norm
        def matches(candidate: str) -> bool:
            cand_norm = self._normalize_command_text(candidate)
            if not cand_norm:
                return False
            return (
                cand_norm == graph_norm
                or graph_norm.startswith(cand_norm)
                or cand_norm.startswith(graph_norm)
                or cand_norm == graph_prefixed
                or graph_prefixed.startswith(cand_norm)
                or cand_norm.startswith(graph_prefixed)
            )

        if "\n" in code:
            for line in code.splitlines():
                if matches(line):
                    return True
            return False
        return matches(code)

    def _get_graph_command_line(self, graph_name: str) -> Optional[str]:
        """Fetch the Stata command line used to create the graph, if available."""
        try:
            from sfi import Macro
        except Exception:
            return None

        resolved = self._resolve_graph_name_for_stata(graph_name)
        hold_name = f"_mcp_gcmd_hold_{uuid.uuid4().hex[:8]}"
        cmd = None
        cur_graph = None

        with self._exec_lock:
            try:
                bundle = (
                    f"capture _return hold {hold_name}\n"
                    f"capture quietly graph describe {resolved}\n"
                    "macro define mcp_gcmd \"`r(command)'\"\n"
                    "macro define mcp_curgraph \"`c(curgraph)'\"\n"
                    f"capture _return restore {hold_name}"
                )
                self.stata.run(bundle, echo=False)
                cmd = Macro.getGlobal("mcp_gcmd")
                cur_graph = Macro.getGlobal("mcp_curgraph")
                self.stata.run("macro drop mcp_gcmd", echo=False)
                self.stata.run("macro drop mcp_curgraph", echo=False)
            except Exception:
                try:
                    self.stata.run(f"capture _return restore {hold_name}", echo=False)
                except Exception:
                    pass
                cmd = None

        if cmd:
            return cmd

        # Fallback: describe current graph without a name and validate against c(curgraph).
        with self._exec_lock:
            try:
                bundle = (
                    f"capture _return hold {hold_name}\n"
                    "capture quietly graph describe\n"
                    "macro define mcp_gcmd \"`r(command)'\"\n"
                    "macro define mcp_curgraph \"`c(curgraph)'\"\n"
                    f"capture _return restore {hold_name}"
                )
                self.stata.run(bundle, echo=False)
                cmd = Macro.getGlobal("mcp_gcmd")
                cur_graph = Macro.getGlobal("mcp_curgraph")
                self.stata.run("macro drop mcp_gcmd", echo=False)
                self.stata.run("macro drop mcp_curgraph", echo=False)
            except Exception:
                try:
                    self.stata.run(f"capture _return restore {hold_name}", echo=False)
                except Exception:
                    pass
                cmd = None

        if cmd and cur_graph:
            if cur_graph == resolved or cur_graph == graph_name:
                return cmd

        return cmd or None

    def _request_break_in(self) -> None:
        """
        Attempt to interrupt a running Stata command when cancellation is requested.

        Uses the Stata sfi.breakIn hook when available; errors are swallowed because
        cancellation should never crash the host process.
        """
        try:
            import sfi  # type: ignore[import-not-found]

            break_fn = getattr(sfi, "breakIn", None) or getattr(sfi, "break_in", None)
            if callable(break_fn):
                try:
                    break_fn()
                    logger.info("Sent breakIn() to Stata for cancellation")
                except Exception as e:  # pragma: no cover - best-effort
                    logger.warning(f"Failed to send breakIn() to Stata: {e}")
            else:  # pragma: no cover - environment without Stata runtime
                logger.debug("sfi.breakIn not available; cannot interrupt Stata")
        except Exception as e:  # pragma: no cover - import failure or other
            logger.debug(f"Unable to import sfi for cancellation: {e}")

    async def _wait_for_stata_stop(self, timeout: float = 2.0) -> bool:
        """
        After requesting a break, poll the Stata interface so it can surface BreakError
        and return control. This is best-effort and time-bounded.
        """
        deadline = time.monotonic() + timeout
        try:
            import sfi  # type: ignore[import-not-found]

            toolkit = getattr(sfi, "SFIToolkit", None)
            poll = getattr(toolkit, "pollnow", None) or getattr(toolkit, "pollstd", None)
            BreakError = getattr(sfi, "BreakError", None)
        except Exception:  # pragma: no cover
            return False

        if not callable(poll):
            return False

        last_exc: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                poll()
            except Exception as e:  # pragma: no cover - depends on Stata runtime
                last_exc = e
                if BreakError is not None and isinstance(e, BreakError):
                    logger.info("Stata BreakError detected; cancellation acknowledged by Stata")
                    return True
                # If Stata already stopped, break on any other exception.
                break
            await anyio.sleep(0.05)

        if last_exc:
            logger.debug(f"Cancellation poll exited with {last_exc}")
        return False

    @contextmanager
    def _temp_cwd(self, cwd: Optional[str]):
        if cwd is None:
            yield
            return
        prev = os.getcwd()
        os.chdir(cwd)
        try:
            yield
        finally:
            os.chdir(prev)

    @contextmanager
    def _safe_redirect_fds(self):
        """Redirects fd 1 (stdout) to fd 2 (stderr) at the OS level."""
        # Save original stdout fd
        try:
            stdout_fd = os.dup(1)
        except Exception:
            # Fallback if we can't dup (e.g. strange environment)
            yield
            return

        try:
            # Redirect OS-level stdout to stderr
            os.dup2(2, 1)
            yield
        finally:
            # Restore stdout
            try:
                os.dup2(stdout_fd, 1)
                os.close(stdout_fd)
            except Exception:
                pass

    def init(self):
        """Initializes usage of pystata using cached discovery results."""
        if self._initialized:
            return

        # Suppress any non-UTF8 banner output from PyStata on stdout, which breaks MCP stdio transport
        from contextlib import redirect_stdout, redirect_stderr

        try:
            import stata_setup
            
            # Get discovered Stata paths (cached from first call)
            discovery_candidates = _get_discovery_candidates()
            if not discovery_candidates:
                raise RuntimeError("No Stata candidates found during discovery")
            
            logger.info("Initializing Stata engine (attempting up to %d candidate binaries)...", len(discovery_candidates))

            # Diagnostic: force faulthandler to output to stderr for C crashes
            import faulthandler
            faulthandler.enable(file=sys.stderr)
            import subprocess

            success = False
            last_error = None
            chosen_exec: Optional[Tuple[str, str]] = None

            for stata_exec_path, edition in discovery_candidates:
                candidates = []
                # Prefer the binary directory first (documented input for stata_setup)
                bin_dir = os.path.dirname(stata_exec_path)
                
                # 2. App Bundle: .../StataMP.app (macOS only)
                curr = bin_dir
                app_bundle = None
                while len(curr) > 1:
                    if curr.endswith(".app"):
                        app_bundle = curr
                        break
                    parent = os.path.dirname(curr)
                    if parent == curr: 
                        break
                    curr = parent

                ordered_candidates = []
                if app_bundle:
                    # On macOS, the parent of the .app is often the correct install path
                    # (e.g., /Applications/StataNow containing StataMP.app)
                    parent_dir = os.path.dirname(app_bundle)
                    if parent_dir and parent_dir != "/":
                        ordered_candidates.append(parent_dir)
                    ordered_candidates.append(app_bundle)
                
                if bin_dir:
                    ordered_candidates.append(bin_dir)
                
                # Deduplicate preserving order
                seen = set()
                candidates = []
                for c in ordered_candidates:
                    if c not in seen:
                        seen.add(c)
                        candidates.append(c)

                for path in candidates:
                    try:
                        # 1. Pre-flight check in a subprocess to capture hard exits/crashes
                        skip_preflight = os.environ.get("MCP_STATA_SKIP_PREFLIGHT") == "1"
                        if not skip_preflight:
                            sys.stderr.write(f"[mcp_stata] DEBUG: Pre-flight check for path '{path}'\n")
                            sys.stderr.flush()
                            
                            preflight_code = f"""
import sys
import stata_setup
from contextlib import redirect_stdout, redirect_stderr
with redirect_stdout(sys.stderr), redirect_stderr(sys.stderr):
    try:
        stata_setup.config({repr(path)}, {repr(edition)})
        from pystata import stata
        # Minimal verification of engine health
        stata.run('display 1', echo=False)
        print('PREFLIGHT_OK')
    except Exception as e:
        print(f'PREFLIGHT_FAIL: {{e}}', file=sys.stderr)
        sys.exit(1)
"""
                            
                            try:
                                # Use shorter timeout for pre-flight if feasible, 
                                # but keep it safe for slow environments. 15s is usually enough for a ping.
                                res = subprocess.run(
                                    [sys.executable, "-c", preflight_code],
                                    capture_output=True, text=True, timeout=20
                                )
                                if res.returncode != 0:
                                    sys.stderr.write(f"[mcp_stata] Pre-flight failed (rc={res.returncode}) for '{path}'\n")
                                    if res.stdout.strip():
                                        sys.stderr.write(f"--- Pre-flight stdout ---\n{res.stdout.strip()}\n")
                                    if res.stderr.strip():
                                        sys.stderr.write(f"--- Pre-flight stderr ---\n{res.stderr.strip()}\n")
                                    sys.stderr.flush()
                                    last_error = f"Pre-flight failed: {res.stdout.strip()} {res.stderr.strip()}"
                                    continue
                                else:
                                    sys.stderr.write(f"[mcp_stata] Pre-flight succeeded for '{path}'. Proceeding to in-process init.\n")
                                    sys.stderr.flush()
                            except Exception as pre_e:
                                sys.stderr.write(f"[mcp_stata] Pre-flight execution error for '{path}': {repr(pre_e)}\n")
                                sys.stderr.flush()
                                last_error = pre_e
                                continue
                        else:
                            sys.stderr.write(f"[mcp_stata] DEBUG: Skipping pre-flight check for path '{path}' (MCP_STATA_SKIP_PREFLIGHT=1)\n")
                            sys.stderr.flush()

                        msg = f"[mcp_stata] DEBUG: In-process stata_setup.config('{path}', '{edition}')\n"
                        sys.stderr.write(msg)
                        sys.stderr.flush()
                        # Redirect both sys.stdout/err AND the raw fds to our stderr pipe.
                        with redirect_stdout(sys.stderr), redirect_stderr(sys.stderr), self._safe_redirect_fds():
                            stata_setup.config(path, edition)
                        
                        sys.stderr.write(f"[mcp_stata] DEBUG: stata_setup.config succeeded for path: {path}\n")
                        sys.stderr.flush()
                        success = True
                        chosen_exec = (stata_exec_path, edition)
                        logger.info("stata_setup.config succeeded with path: %s", path)
                        break
                    except BaseException as e:
                        last_error = e
                        sys.stderr.write(f"[mcp_stata] WARNING: In-process stata_setup.config caught: {repr(e)}\n")
                        sys.stderr.flush()
                        logger.warning("stata_setup.config failed for path '%s': %s", path, e)
                        if isinstance(e, SystemExit):
                            break
                        continue

                if success:
                    # Cache winning candidate for subsequent lookups
                    global _discovery_result
                    if chosen_exec:
                        _discovery_result = chosen_exec
                    break

            if not success:
                error_msg = (
                    f"stata_setup.config failed to initialize Stata. "
                    f"Tried candidates: {discovery_candidates}. "
                    f"Last error: {repr(last_error)}"
                )
                sys.stderr.write(f"[mcp_stata] ERROR: {error_msg}\n")
                sys.stderr.flush()
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            # Cache the binary path for later use (e.g., PNG export on Windows)
            self._stata_exec_path = pathlib.Path(stata_exec_path).absolute()

            try:
                sys.stderr.write("[mcp_stata] DEBUG: Importing pystata and warming up...\n")
                sys.stderr.flush()
                with redirect_stdout(sys.stderr), redirect_stderr(sys.stderr), self._safe_redirect_fds():
                    from pystata import stata  # type: ignore[import-not-found]
                    try:
                        # Disable PyStata streamout to avoid stdout corruption and SystemError
                        from pystata import config as pystata_config  # type: ignore[import-not-found]
                        if hasattr(pystata_config, "set_streamout"):
                            pystata_config.set_streamout("off")
                        elif hasattr(pystata_config, "stconfig"):
                            pystata_config.stconfig["streamout"] = "off"
                    except Exception:
                        pass
                    # Warm up the engine and swallow any late splash screen output
                    stata.run("display 1", echo=False)
                self.stata = stata
                self._initialized = True

                # Initialize persistent session log
                self._persistent_log_path = self._create_smcl_log_path(prefix="mcp_session_")
                self._persistent_log_name = "_mcp_session"
                path_for_stata = self._persistent_log_path.replace("\\", "/")
                # Open the log once for the entire session, ensuring any previous one is closed
                stata.run(f"capture log close {self._persistent_log_name}", echo=False)
                stata.run(f'log using "{path_for_stata}", replace smcl name({self._persistent_log_name})', echo=False)
                
                sys.stderr.write("[mcp_stata] DEBUG: pystata warmed up successfully\n")
                sys.stderr.flush()
            except BaseException as e:
                sys.stderr.write(f"[mcp_stata] ERROR: Failed to load pystata or run initial command: {repr(e)}\n")
                sys.stderr.flush()
                logger.error("Failed to load pystata or run initial command: %s", e)
                raise
            
            # Initialize list_graphs TTL cache
            self._list_graphs_cache = None
            self._list_graphs_cache_time = 0
            self._list_graphs_cache_lock = threading.Lock()

            # Map user-facing graph names (may include spaces/punctuation) to valid
            # internal Stata graph names.
            self._graph_name_aliases: Dict[str, str] = {}
            self._graph_name_reverse: Dict[str, str] = {}
            
            logger.info("StataClient initialized successfully with %s (%s)", stata_exec_path, edition)

        except ImportError as e:
            raise RuntimeError(
                f"Failed to import stata_setup or pystata: {e}. "
                "Ensure they are installed (pip install pystata stata-setup)."
            ) from e

    def _make_valid_stata_name(self, name: str) -> str:
        """Create a valid Stata name (<=32 chars, [A-Za-z_][A-Za-z0-9_]*)."""
        base = re.sub(r"[^A-Za-z0-9_]", "_", name or "")
        if not base:
            base = "Graph"
        if not re.match(r"^[A-Za-z_]", base):
            base = f"G_{base}"
        base = base[:32]

        # Avoid collisions.
        candidate = base
        i = 1
        while candidate in getattr(self, "_graph_name_reverse", {}):
            suffix = f"_{i}"
            candidate = (base[: max(0, 32 - len(suffix))] + suffix)[:32]
            i += 1
        return candidate

    def _resolve_graph_name_for_stata(self, name: str) -> str:
        """Return internal Stata graph name for a user-facing name."""
        if not name:
            return name
        aliases = getattr(self, "_graph_name_aliases", None)
        if aliases and name in aliases:
            return aliases[name]
        return name

    def _maybe_rewrite_graph_name_in_command(self, code: str) -> str:
        """Rewrite name("...") to a valid Stata name and store alias mapping."""
        if not code:
            return code
        if not hasattr(self, "_graph_name_aliases"):
            self._graph_name_aliases = {}
            self._graph_name_reverse = {}

        # Handle common patterns: name("..." ...), name(`"..."' ...), or name(unquoted ...)
        pat = re.compile(r"name\(\s*(?:`\"(?P<cq>[^\"]*)\"'|\"(?P<dq>[^\"]*)\"|(?P<uq>[^,\s\)]+))\s*(?P<rest>[^)]*)\)")

        def repl(m: re.Match) -> str:
            original = m.group("cq") or m.group("dq") or m.group("uq")
            original = (original or "").strip()
            
            # If it's already an alias we recognize, don't rewrite it again
            if original.startswith("mcp_g_") and original in self._graph_name_reverse:
                return m.group(0)

            internal = self._graph_name_aliases.get(original)
            if not internal:
                # Only rewrite if it's NOT a valid Stata name or has special characters
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", original) or len(original) > 32:
                    internal = self._make_valid_stata_name(original)
                    self._graph_name_aliases[original] = internal
                    self._graph_name_reverse[internal] = original
                else:
                    # Valid name, use as is but still record it if we want reverse mapping to be consistent
                    internal = original

            rest = m.group("rest") or ""
            return f"name({internal}{rest})"

        return pat.sub(repl, code)

    def _get_rc_from_scalar(self, Scalar=None) -> int:
        """Safely get return code using sfi.Scalar access to c(rc)."""
        if Scalar is None:
            from sfi import Scalar
        try:
            # c(rc) is the built-in system constant for the last return code.
            # Accessing it via Scalar.getValue is direct and does not reset it.
            rc_val = Scalar.getValue("c(rc)")
            if rc_val is None:
                return 0
            return int(float(rc_val))
        except Exception:
            # Fallback to macro if Scalar fails
            try:
                from sfi import Macro
                self.stata.run("global _mcp_last_rc = _rc", echo=False)
                rc_str = Macro.getGlobal("_mcp_last_rc")
                return int(float(rc_str)) if rc_str else 0
            except Exception:
                return -1

    def _parse_rc_from_text(self, text: str) -> Optional[int]:
        """Parse return code from plain text using structural patterns."""
        if not text:
            return None
            
        # 1. Primary check: 'search r(N)' pattern (SMCL tag potentially stripped)
        matches = list(re.finditer(r'search r\((\d+)\)', text))
        if matches:
            try:
                return int(matches[-1].group(1))
            except Exception:
                pass

        # 2. Secondary check: Standalone r(N); pattern
        # This appears at the end of command blocks
        matches = list(re.finditer(r'(?<!\w)r\((\d+)\);?', text))
        if matches:
            try:
                return int(matches[-1].group(1))
            except Exception:
                pass
                
        return None

    def _parse_line_from_text(self, text: str) -> Optional[int]:
        match = re.search(r"line\s+(\d+)", text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
        return None

    def _read_log_backwards_until_error(self, path: str, max_bytes: int = 5_000_000, start_offset: int = 0) -> str:
        """
        Read log file backwards in chunks, stopping when we find {err} tags, 
        reach the start, or reach the start_offset.

        Args:
            path: Path to the log file
            max_bytes: Maximum total bytes to read (safety limit)
            start_offset: Byte offset to stop searching at (important for persistent logs)

        Returns:
            The relevant portion of the log containing the error and context
        """
        try:
            chunk_size = 50_000
            total_read = 0
            chunks = []

            with open(path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()

                if file_size <= start_offset:
                    return ""

                # Start from the end, but don't go past start_offset
                position = file_size

                while position > start_offset and total_read < max_bytes:
                    read_size = min(chunk_size, position - start_offset, max_bytes - total_read)
                    position -= read_size

                    f.seek(position)
                    chunk = f.read(read_size)
                    chunks.insert(0, chunk)
                    total_read += read_size

                    try:
                        accumulated = b''.join(chunks).decode('utf-8', errors='replace')
                        if '{err}' in accumulated:
                            # Context chunk
                            if position > start_offset and total_read < max_bytes:
                                extra_read = min(chunk_size, position - start_offset, max_bytes - total_read)
                                position -= extra_read
                                f.seek(position)
                                extra_chunk = f.read(extra_read)
                                chunks.insert(0, extra_chunk)
                            return b''.join(chunks).decode('utf-8', errors='replace')
                    except Exception:
                        continue
            
            return b''.join(chunks).decode('utf-8', errors='replace')
        except Exception as e:
            logger.debug(f"Backward log read failed: {e}")
            return ""

    def _read_log_tail_smart(self, path: str, rc: int, trace: bool = False, start_offset: int = 0) -> str:
        """
        Smart log tail reader that adapts based on whether an error occurred.

        - If rc == 0: Read normal tail (20KB without trace, 200KB with trace)
        - If rc != 0: Search backwards dynamically to find the error

        Args:
            path: Path to the log file
            rc: Return code from Stata
            trace: Whether trace mode was enabled
            start_offset: Byte offset to stop searching at

        Returns:
            Relevant log content
        """
        if rc != 0:
            # Error occurred - search backwards for {err} tags
            return self._read_log_backwards_until_error(path, start_offset=start_offset)
        else:
            # Success - just read normal tail
            tail_size = 200_000 if trace else 20_000
            return self._read_log_tail(path, tail_size, start_offset=start_offset)

    def _read_log_tail(self, path: str, max_chars: int, start_offset: int = 0) -> str:
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                end_pos = f.tell()

                if end_pos <= start_offset:
                    return ""
                
                read_size = min(max_chars, end_pos - start_offset)
                f.seek(end_pos - read_size)
                data = f.read(read_size)
            return data.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _build_combined_log(
        self,
        tail: TailBuffer,
        path: str,
        rc: int,
        trace: bool,
        exc: Optional[Exception],
        start_offset: int = 0,
    ) -> str:
        tail_text = tail.get_value()
        log_tail = self._read_log_tail_smart(path, rc, trace, start_offset=start_offset)
        if log_tail and len(log_tail) > len(tail_text):
            tail_text = log_tail
        return (tail_text or "") + (f"\n{exc}" if exc else "")

    def _truncate_command_output(
        self,
        result: CommandResponse,
        max_output_lines: Optional[int],
    ) -> CommandResponse:
        if max_output_lines is None or not result.stdout:
            return result
        lines = result.stdout.splitlines()
        if len(lines) <= max_output_lines:
            return result
        truncated_lines = lines[:max_output_lines]
        truncated_lines.append(
            f"\n... (output truncated: showing {max_output_lines} of {len(lines)} lines)"
        )
        truncated_stdout = "\n".join(truncated_lines)
        if hasattr(result, "model_copy"):
            return result.model_copy(update={"stdout": truncated_stdout})
        return result.copy(update={"stdout": truncated_stdout})

    def _run_plain_capture(self, code: str) -> str:
        """
        Run a Stata command while capturing output using a named SMCL log.
        This is the most reliable way to capture output (like return list)
        without interfering with user logs or being affected by stdout redirection issues.
        """
        if not self._initialized:
            self.init()

        with self._exec_lock:
            hold_name = f"mcp_hold_{uuid.uuid4().hex[:8]}"
            # Hold results BEFORE opening the capture log
            self.stata.run(f"capture _return hold {hold_name}", echo=False)
            
            try:
                with self._smcl_log_capture() as (log_name, smcl_path):
                    # Restore results INSIDE the capture log so return list can see them
                    self.stata.run(f"capture _return restore {hold_name}", echo=False)
                    try:
                        self.stata.run(code, echo=True)
                    except Exception:
                        pass
            except Exception:
                # Cleanup hold if log capture failed to open
                self.stata.run(f"capture _return drop {hold_name}", echo=False)
                content = ""
                smcl_path = None
            else:
                # Read SMCL content and convert to text
                content = self._read_smcl_file(smcl_path)
            # Remove the temp file
            self._safe_unlink(smcl_path)
            
            return self._smcl_to_text(content)

    def _count_do_file_lines(self, path: str) -> int:
        """
        Count the number of executable lines in a .do file for progress inference.

        Blank lines and comment-only lines (starting with * or //) are ignored.
        """
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except Exception:
            return 0

        total = 0
        for line in lines:
            s = line.strip()
            if not s:
                continue
            if s.startswith("*"):
                continue
            if s.startswith("//"):
                continue
            total += 1
        return total

    def _smcl_to_text(self, smcl: str) -> str:
        """Convert simple SMCL markup into plain text for LLM-friendly help."""
        # First, clean internal maintenance
        smcl = self._clean_internal_smcl(smcl)
        
        # Protect escape sequences for curly braces 
        # SMCL uses {c -(} for { and {c )-} for }
        cleaned = smcl.replace("{c -(}", "__L__").replace("{c )-}", "__R__")
        
        # Handle SMCL escape variations that might have been partially processed
        cleaned = cleaned.replace("__G_L__", "__L__").replace("__G_R__", "__R__")
        
        # Keep inline directive content if present (e.g., {bf:word} -> word)
        cleaned = re.sub(r"\{[^}:]+:([^}]*)\}", r"\1", cleaned)

        # Remove remaining SMCL tags like {smcl}, {txt}, {res}, {com}, etc.
        # We use a non-greedy match.
        cleaned = re.sub(r"\{[^}]*\}", "", cleaned)
        
        # Convert placeholders back to literal braces
        cleaned = cleaned.replace("__L__", "{").replace("__R__", "}")
        
        # Normalize whitespace
        cleaned = cleaned.replace("\r", "")
        lines = [line.rstrip() for line in cleaned.splitlines()]
        return "\n".join(lines).strip()

    def _clean_internal_smcl(
        self,
        content: str,
        strip_output: bool = True,
        strip_leading_boilerplate: bool = True,
    ) -> str:
        """
        Conservative cleaning of internal maintenance from SMCL while preserving 
        tags and actual user output.
        """
        if not content:
            return ""

        # Pattern for arbitrary SMCL tags: {txt}, {com}, etc.
        tags = r"(?:\{[^}]+\})*"

        # 1. Strip SMCL log headers and footers (multiple possible due to append/reopen)
        # Headers typically run from {smcl} until the line after "opened on:".
        content = re.sub(
            r"(?:\{smcl\}\s*)?\{txt\}\{sf\}\{ul off\}\{\.-\}.*?opened on:.*?(?:\r?\n){1,2}",
            "",
            content,
            flags=re.DOTALL,
        )
        # Remove orphan header markers that sometimes leak into output
        content = re.sub(r"^\s*\{smcl\}\s*$", "", content, flags=re.MULTILINE)
        content = re.sub(r"^\s*\{txt\}\{sf\}\{ul off\}\s*$", "", content, flags=re.MULTILINE)
        content = re.sub(r"^\s*\{txt\}\{sf\}\{ul off\}\{smcl\}\s*$", "", content, flags=re.MULTILINE)

        # Remove leading boilerplate-only lines (blank or SMCL tag-only)
        if strip_leading_boilerplate:
            lines = content.splitlines()
            lead = 0
            while lead < len(lines):
                line = lines[lead].strip()
                if not line:
                    lead += 1
                    continue
                if re.fullmatch(r"(?:\{[^}]+\})+", line):
                    lead += 1
                    continue
                break
            if lead:
                content = "\n".join(lines[lead:])

        # 2. Strip our injected capture/noisily blocks
        # We match start-of-line followed by optional tags, prompt, optional tags, 
        # then the block markers. Must match the entire line to be safe.
        block_markers = [
            r"capture noisily \{c -\(\}",
            r"capture noisily \{",
            r"noisily \{c -\(\}",
            r"noisily \{",
            r"\{c \)\-\}",
            r"\}"
        ]
        for p in block_markers:
            # Match exactly the marker line (with optional trailing tags/whitespace)
            pattern = r"^" + tags + r"\. " + tags + p + tags + r"\s*(\r?\n|$)"
            content = re.sub(pattern, "", content, flags=re.MULTILINE)

        # 3. Strip internal maintenance commands
        # These can optionally be prefixed with 'capture' and/or 'quietly'
        internal_cmds = [
            r"scalar _mcp_rc\b",
            r"scalar _mcp_.*?\b",
            r"macro drop _mcp_.*?\b",
            r"log flush\b",
            r"log close\b",
            r"capture _return hold\b",
            r"_return hold\b",
            r"preemptive_cache\b"
        ]
        internal_regex = r"^" + tags + r"\. " + tags + r"(?:(?:capture|quietly)\s+)*" + r"(?:" + "|".join(internal_cmds) + r").*?" + tags + r"\s*(\r?\n|$)"
        content = re.sub(internal_regex, "", content, flags=re.MULTILINE)

        # 4. Strip internal file notifications (e.g. from graph exports or internal logs)
        internal_file_patterns = [
            r"mcp_(?:stata|hold|ghold|det|session)_",
            r"preemptive_cache"
        ]
        for p in internal_file_patterns:
            content = re.sub(r"^" + tags + r"\(file " + tags + r".*?" + p + r".*?" + tags + r" (?:saved|not found)(?: as [^)]+)?\).*?(\r?\n|$)", "", content, flags=re.MULTILINE)

        # 5. Strip prompt-only lines that include our injected {txt} tag
        # Preserve native Stata prompts like "{com}." which are part of verbatim output.
        content = re.sub(r"^" + tags + r"\. " + r"(?:\{txt\})+" + tags + r"(\s*\r?\n|$)", "", content, flags=re.MULTILINE)

        # Do not add SMCL tags heuristically; preserve original output.

        # 6. Final cleanup of potential double newlines introduced by stripping
        content = re.sub(r"\n{3,}", "\n\n", content)

        return content.strip() if strip_output else content


    def _extract_error_and_context(self, log_content: str, rc: int) -> Tuple[str, str]:
        """
        Extracts the error message and trace context using {err} SMCL tags.
        """
        if not log_content:
            return f"Stata error r({rc})", ""

        lines = log_content.splitlines()

        # Search backwards for the {err} tag
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i]
            if '{err}' in line:
                # Found the (last) error line. 
                # Walk backwards to find the start of the error block (consecutive {err} lines)
                start_idx = i
                while start_idx > 0 and '{err}' in lines[start_idx-1]:
                    start_idx -= 1
                
                # The full error message is the concatenation of all {err} lines in this block
                error_lines = []
                for j in range(start_idx, i + 1):
                    error_lines.append(lines[j].strip())
                
                clean_msg = " ".join(filter(None, error_lines)) or f"Stata error r({rc})"
                
                # Capture everything from the start of the error block to the end
                context_str = "\n".join(lines[start_idx:])
                return clean_msg, context_str

        # Fallback: grab the last 30 lines
        context_start = max(0, len(lines) - 30)
        context_str = "\n".join(lines[context_start:])

        return f"Stata error r({rc})", context_str

    def _exec_with_capture(self, code: str, echo: bool = True, trace: bool = False, cwd: Optional[str] = None) -> CommandResponse:
        """Executes a command and returns results in a structured envelope."""
        if not self._initialized: self.init()
        self._increment_command_idx()
        self._last_results = None # Invalidate results cache
        
        code = self._maybe_rewrite_graph_name_in_command(code)

        output_buffer, error_buffer = StringIO(), StringIO()
        rc, sys_error = 0, None
        
        with self._exec_lock:
            # Persistent log selection
            use_p = self._persistent_log_path and os.path.exists(self._persistent_log_path) and cwd is None
            smcl_path = self._persistent_log_path if use_p else self._create_smcl_log_path(prefix="mcp_", max_hex=16)
            log_name = None if use_p else self._make_smcl_log_name()
            if use_p:
                # Ensure persistent log is bound to our expected path.
                try:
                    path_for_stata = smcl_path.replace("\\", "/")
                    reopen_bundle = (
                        f"capture quietly log close {self._persistent_log_name}\n"
                        f"capture quietly log using \"{path_for_stata}\", append smcl name({self._persistent_log_name})"
                    )
                    self._run_internal(reopen_bundle, echo=False)
                except Exception:
                    pass
            
            # Flush before seeking to get accurate file size for offset
            if use_p:
                try: 
                    self.stata.run("capture quietly log flush _mcp_session", echo=False)
                except: pass
                
            start_off = os.path.getsize(smcl_path) if use_p else 0
            if not use_p: self._open_smcl_log(smcl_path, log_name)

            rc = 0
            sys_error = None
            try:
                from sfi import Scalar, Macro
                with self._temp_cwd(cwd), self._redirect_io(output_buffer, error_buffer):
                    try:
                        if trace: self.stata.run("set trace on")
                        self._hold_name = f"mcp_hold_{uuid.uuid4().hex[:12]}"

                        # Execute directly to preserve native echo in SMCL logs.
                        # Capture RC immediately via c(rc) before any maintenance commands.
                        self.stata.run(code, echo=echo)
                        rc = self._get_rc_from_scalar(Scalar)

                        # Preserve results for later restoration
                        self.stata.run(f"capture _return hold {self._hold_name}", echo=False)
                        if use_p:
                            flush_bundle = (
                                f"capture quietly log off {self._persistent_log_name}\n"
                                f"capture quietly log on {self._persistent_log_name}"
                            )
                            self.stata.run(flush_bundle, echo=False)
                    except Exception as e:
                        rc = self._parse_rc_from_text(str(e)) or self._get_preserved_rc() or 1
                        raise
                    finally:
                        if trace:
                            try:
                                self.stata.run("set trace off")
                            except Exception:
                                pass
            except Exception as e:
                sys_error = str(e)
            finally:
                if not use_p and log_name: self._close_smcl_log(log_name)
                # Restore results and set final RC state
                if hasattr(self, "_hold_name"):
                    try:
                        cleanup_bundle = f"capture _return restore {self._hold_name}\n"
                        if rc > 0:
                            cleanup_bundle += f"capture error {rc}"
                        self.stata.run(cleanup_bundle, echo=False)
                    except Exception: pass
                    delattr(self, "_hold_name")

        # Output extraction
        smcl_content = self._read_persistent_log_chunk(start_off) if use_p else self._read_smcl_file(smcl_path)
        if use_p and not smcl_content:
            try:
                self.stata.run(f"capture quietly log flush {self._persistent_log_name}", echo=False)
                smcl_content = self._read_persistent_log_chunk(start_off)
            except Exception:
                pass
        if not use_p: self._safe_unlink(smcl_path)
    
        # Use SMCL as authoritative source for stdout (preserve SMCL tags)
        if smcl_content:
            stdout = self._clean_internal_smcl(smcl_content)
        else:
            stdout = output_buffer.getvalue()
            
        stderr = error_buffer.getvalue()

        # If RC looks wrong but SMCL shows no error markers, treat as success.
        if rc != 0 and smcl_content:
            has_err_tag = "{err}" in smcl_content
            rc_match = re.search(r"(?<!\w)r\((\d+)\)", smcl_content)
            if rc_match:
                try:
                    rc = int(rc_match.group(1))
                except Exception:
                    pass
            else:
                text_rc = None
                try:
                    text_rc = self._parse_rc_from_text(self._smcl_to_text(smcl_content))
                except Exception:
                    text_rc = None
                if not has_err_tag and text_rc is None:
                    rc = 0
        elif rc != 0 and not smcl_content and stdout:
            text_rc = self._parse_rc_from_text(stdout + ("\n" + stderr if stderr else ""))
            if text_rc is None:
                rc = 0

        success = rc == 0 and sys_error is None
        error = None
        
        if not success:
            if smcl_content:
                msg, context = self._extract_error_from_smcl(smcl_content, rc)
                if msg == f"Stata error r({rc})":
                    msg2, context2 = self._extract_error_and_context(stdout + stderr, rc)
                    if msg2 != f"Stata error r({rc})":
                        msg, context = msg2, context2
                    elif use_p and self._persistent_log_path:
                        try:
                            with open(self._persistent_log_path, "r", encoding="utf-8", errors="replace") as f:
                                f.seek(start_off)
                                raw_chunk = f.read()
                            msg3, context3 = self._extract_error_from_smcl(raw_chunk, rc)
                            if msg3 != f"Stata error r({rc})":
                                msg, context = msg3, context3
                        except Exception:
                            pass
            else:
                msg, context = self._extract_error_and_context(stdout + stderr, rc)
            snippet = context or stdout or stderr or msg
            error = ErrorEnvelope(message=msg, context=context, rc=rc, command=code, stdout=stdout, stderr=stderr, snippet=snippet)
            # In error case, we often want to isolate the error msg in stderr
            # but keep stdout for context if provided.
            stdout = "" 
        elif echo:
            # SMCL output is already cleaned; no additional filtering needed.
            pass
        # Persistence isolation: Ensure isolated log_path for tests and clarity
        if use_p:
            # Create a temporary chunk file to fulfill the isolated log_path contract
            chunk_file = self._create_smcl_log_path(prefix="mcp_chunk_")
            try:
                with open(chunk_file, "w", encoding="utf-8") as f:
                    f.write(smcl_content)
                smcl_path = chunk_file
            except Exception:
                pass

            # Final safety: If the user explicitly requested CMD2_... and we see CMD1_...
            # then the extraction definitely failed to isolate at the file level.
            # Identify the target UUID in the content
            target_id = None
            if "CMD2_" in code:
                m = re.search(r"CMD2_([a-f0-9-]*)", code)
                if m: target_id = m.group(0)
            elif "CMD1_" in code:
                m = re.search(r"CMD1_([a-f0-9-]*)", code)
                if m: target_id = m.group(0)

            if target_id and target_id in smcl_content:
                idx = smcl_content.find(target_id)
                # Look for the command prompt immediately preceding THIS specific command instance
                com_start = smcl_content.rfind("{com}. ", 0, idx)
                if com_start != -1:
                    # Found it. Now, is there another {com}. between this one and the target?
                    # (In case of error codes or noise). Usually rfind is sufficient.
                    smcl_content = smcl_content[com_start:]
            
            # 2. Aggressive multi-pattern header stripping for any remaining headers
            patterns = [
                r"\{smcl\}(?:\r?\n)?\{txt\}\{sf\}\{ul off\}\{\.-\}(?:\r?\n)?.*?name:\s+\{res\}_mcp_session.*?\{.-\}\r?\n",
                r"\{txt\}\{sf\}\{ul off\}\{\.-\}(?:\r?\n)?.*?name:\s+\{res\}_mcp_session.*?\{.-\}\r?\n",
                r"\(file \{bf\}.*?\{rm\} not found\)\r?\n",
                r"\{p 0 4 2\}\r?\n\(file \{bf\}.*?\{rm\}\r?\nnot found\)\r?\n\{p_end\}\r?\n",
                r"\{smcl\}",
            ]
            for p in patterns:
                smcl_content = re.sub(p, "", smcl_content, flags=re.DOTALL)
                
            # 3. Suppress internal maintenance leaks that sometimes escape quietly/echo=False
            leaks = [
                r"\{com\}\. capture quietly log (?:off|on) _mcp_session\r?\n",
                r"\{com\}\. capture _return hold mcp_hold_[a-f0-9]+\r?\n",
                r"\{com\}\. scalar _mcp_rc = _rc\r?\n",
                r"\{com\}\. \{txt\}\r?\n",
            ]
            for p in leaks:
                smcl_content = re.sub(p, "", smcl_content)

            # Second pass - if we see MANY headers or missed one due to whitespace
            while "_mcp_session" in smcl_content:
                m = re.search(r"(?:\{smcl\}\r?\n?)?\{txt\}\{sf\}\{ul off\}\{\.-\}\r?\n\s+name:\s+\{res\}_mcp_session", smcl_content)
                if not m: break
                header_start = m.start()
                header_end = smcl_content.find("{.-}", m.end())
                if header_end != -1:
                    smcl_content = smcl_content[:header_start] + smcl_content[header_end+4:]
                else:
                    smcl_content = smcl_content[:header_start] + smcl_content[m.end():]

        return CommandResponse(
            command=code, rc=rc, stdout=stdout, stderr=stderr,
            smcl_output=smcl_content, log_path=smcl_path if use_p else None,
            success=success, error=error
        )

    def _exec_no_capture(self, code: str, echo: bool = False, trace: bool = False) -> CommandResponse:
        """Execute Stata code while leaving stdout/stderr alone."""
        if not self._initialized:
            self.init()

        exc: Optional[Exception] = None
        ret_text: Optional[str] = None
        rc = 0
        
        with self._exec_lock:
            try:
                from sfi import Scalar # Import SFI tools
                if trace:
                    self.stata.run("set trace on")
                ret = self.stata.run(code, echo=echo)
                if isinstance(ret, str) and ret:
                    ret_text = ret
                    parsed_rc = self._parse_rc_from_text(ret_text)
                    if parsed_rc is not None:
                        rc = parsed_rc
                
            except Exception as e:
                exc = e
                rc = 1
            finally:
                if trace:
                    try:
                        self.stata.run("set trace off")
                    except Exception as e:
                        logger.warning("Failed to turn off Stata trace mode: %s", e)

        stdout = ""
        stderr = ""
        success = rc == 0 and exc is None
        error = None
        if not success:
            msg = str(exc) if exc else f"Stata error r({rc})"
            error = ErrorEnvelope(
                message=msg,
                rc=rc,
                command=code,
                stdout=ret_text,
            )

        return CommandResponse(
            command=code,
            rc=rc,
            stdout=stdout,
            stderr=None,
            success=success,
            error=error,
        )

    def _get_preserved_rc(self) -> int:
        """Fetch current RC without mutating it."""
        try:
            from sfi import Scalar
            return int(float(Scalar.getValue("c(rc)") or 0))
        except Exception:
            return 0

    def _restore_state(self, hold_name: Optional[str], rc: int) -> None:
        """Restores return results and RC in a single block."""
        code = ""
        if hold_name:
            code += f"capture _return restore {hold_name}\n"
        
        if rc > 0:
            code += f"capture error {rc}\n"
        else:
            code += "capture\n"
            
        try:
            self.stata.run(code, echo=False)
            self._last_results = None
        except Exception:
            pass

    def _exec_no_capture_silent(self, code: str, echo: bool = False, trace: bool = False) -> CommandResponse:
        """Executes code silently, preserving ALL state (RC, r, e, s)."""
        hold_name = f"_mcp_sh_{uuid.uuid4().hex[:8]}"
        preserved_rc = self._get_preserved_rc()
        output_buffer, error_buffer = StringIO(), StringIO()
        rc = 0

        with self._exec_lock, self._redirect_io(output_buffer, error_buffer):
            try:
                # Bundle everything to minimize round-trips and ensure invisibility.
                # Use braces to capture multi-line code correctly.
                inner_code = f"{{\n{code}\n}}" if "\n" in code.strip() else code
                trace_on = "set trace on\n" if trace else ""
                trace_off = "set trace off\n" if trace else ""
                full_cmd = (
                    f"capture _return hold {hold_name}\n"
                    f"{trace_on}"
                    f"capture noisily {inner_code}\n"
                    f"local mcp_rc = _rc\n"
                    f"{trace_off}"
                    f"capture _return restore {hold_name}\n"
                    f"capture error {preserved_rc}"
                )
                self.stata.run(full_cmd, echo=echo)
                from sfi import Macro
                try: rc = int(float(Macro.getLocal("mcp_rc") or 0))
                except: rc = 0
            except Exception as e:
                rc = self._parse_rc_from_text(str(e)) or 1
            
        return CommandResponse(
            command=code, rc=rc,
            stdout=output_buffer.getvalue(),
            stderr=error_buffer.getvalue(),
            success=rc == 0
        )

    def exec_lightweight(self, code: str) -> CommandResponse:
        """
        Executes a command using simple stdout redirection (no SMCL logs).
        Much faster on Windows as it avoids FS operations.
        LIMITED: Does not support error envelopes or complex return code parsing.
        """
        if not self._initialized:
            self.init()

        code = self._maybe_rewrite_graph_name_in_command(code)
        
        output_buffer = StringIO()
        error_buffer = StringIO()
        rc = 0
        exc = None
        
        with self._exec_lock:
             with self._redirect_io(output_buffer, error_buffer):
                try:
                    self.stata.run(code, echo=False)
                except SystemError as e:
                    import traceback
                    traceback.print_exc()
                    exc = e
                    rc = 1
                except Exception as e:
                    exc = e
                    rc = 1
        
        stdout = output_buffer.getvalue()
        stderr = error_buffer.getvalue()
        
        return CommandResponse(
            command=code,
            rc=rc,
            stdout=stdout,
            stderr=stderr if not exc else str(exc),
            success=(rc == 0),
            error=None
        )

    async def run_command_streaming(
    self,
    code: str,
    *,
    notify_log: Callable[[str], Awaitable[None]],
    notify_progress: Optional[Callable[[float, Optional[float], Optional[str]], Awaitable[None]]] = None,
    echo: bool = True,
    trace: bool = False,
    max_output_lines: Optional[int] = None,
    cwd: Optional[str] = None,
    auto_cache_graphs: bool = False,
    on_graph_cached: Optional[Callable[[str, bool], Awaitable[None]]] = None,
    emit_graph_ready: bool = False,
    graph_ready_task_id: Optional[str] = None,
    graph_ready_format: str = "svg",
) -> CommandResponse:
        if not self._initialized:
            self.init()

        code = self._maybe_rewrite_graph_name_in_command(code)
        auto_cache_graphs = auto_cache_graphs or emit_graph_ready
        total_lines = 0  # Commands (not do-files) do not have line-based progress

        if cwd is not None and not os.path.isdir(cwd):
            return CommandResponse(
                command=code,
                rc=601,
                stdout="",
                stderr=None,
                success=False,
                error=ErrorEnvelope(
                    message=f"cwd not found: {cwd}",
                    rc=601,
                    command=code,
                ),
            )

        start_time = time.time()
        exc: Optional[Exception] = None
        smcl_content = ""
        smcl_path = None

        # Setup streaming graph cache if enabled
        graph_cache = self._init_streaming_graph_cache(auto_cache_graphs, on_graph_cached, notify_log)

        _log_file, log_path, tail, tee = self._create_streaming_log(trace=trace)

        # Create SMCL log path for authoritative output capture
        start_offset = 0
        if self._persistent_log_path:
            smcl_path = self._persistent_log_path
            smcl_log_name = self._persistent_log_name
            try:
                start_offset = os.path.getsize(smcl_path)
            except OSError:
                start_offset = 0
        else:
            smcl_path = self._create_smcl_log_path()
            smcl_log_name = self._make_smcl_log_name()

        # Inform the MCP client immediately where to read/tail the output.
        # We provide the cleaned plain-text log_path as the primary 'path' to satisfy 
        # requirements for clean logs without maintenance boilerplate.
        await notify_log(json.dumps({"event": "log_path", "path": log_path, "smcl_path": smcl_path}))

        rc = -1
        path_for_stata = code.replace("\\", "/")
        command = f'{path_for_stata}'

        # Capture initial graph signatures to detect additions/changes
        graph_ready_initial = self._capture_graph_state(graph_cache, emit_graph_ready)
        self._current_command_code = code
        
        # Increment AFTER capture so detected modifications are based on state BEFORE this command
        self._increment_command_idx()

        graph_poll_state = [0.0]
        graph_poll_interval = 0.75

        async def on_chunk_for_graphs(_chunk: str) -> None:
            now = time.monotonic()
            if graph_poll_state and now - graph_poll_state[0] < graph_poll_interval:
                return
            # Background the graph check so we don't block SMCL streaming or task completion
            asyncio.create_task(
                self._maybe_cache_graphs_on_chunk(
                    graph_cache=graph_cache,
                    emit_graph_ready=emit_graph_ready,
                    notify_log=notify_log,
                    graph_ready_task_id=graph_ready_task_id,
                    graph_ready_format=graph_ready_format,
                    graph_ready_initial=graph_ready_initial,
                    last_check=graph_poll_state,
                )
            )

        done = anyio.Event()

        try:
            async with anyio.create_task_group() as tg:
                async def stream_smcl() -> None:
                    try:
                        await self._stream_smcl_log(
                            smcl_path=smcl_path,
                            notify_log=notify_log,
                            done=done,
                            on_chunk=on_chunk_for_graphs if graph_cache else None,
                            start_offset=start_offset,
                            tee=tee,
                        )
                    except Exception as exc:
                        logger.debug("SMCL streaming failed: %s", exc)

                tg.start_soon(stream_smcl)

                if notify_progress is not None:
                    if total_lines > 0:
                        await notify_progress(0, float(total_lines), f"Executing command: 0/{total_lines}")
                    else:
                        await notify_progress(0, None, "Running command")

                try:
                    run_blocking = lambda: self._run_streaming_blocking(
                        command=command,
                        tee=tee,
                        cwd=cwd,
                        trace=trace,
                        echo=echo,
                        smcl_path=smcl_path,
                        smcl_log_name=smcl_log_name,
                        hold_attr="_hold_name_stream",
                        require_smcl_log=True,
                    )
                    try:
                        rc, exc = await anyio.to_thread.run_sync(
                            run_blocking,
                            abandon_on_cancel=True,
                        )
                    except TypeError:
                        rc, exc = await anyio.to_thread.run_sync(run_blocking)
                except Exception as e:
                    exc = e
                    if rc in (-1, 0):
                        rc = 1
                except get_cancelled_exc_class():
                    self._request_break_in()
                    await self._wait_for_stata_stop()
                    raise
                finally:
                    done.set()
        except* Exception as exc_group:
            logger.debug("SMCL streaming task group failed: %s", exc_group)
        finally:
            tee.close()

        # Read SMCL content as the authoritative source
        smcl_content = self._read_smcl_file(smcl_path, start_offset=start_offset)
        # Clean internal maintenance immediately 
        smcl_content = self._clean_internal_smcl(smcl_content, strip_output=False) 


        graph_ready_emitted = 0
        if graph_cache:
            asyncio.create_task(
                self._cache_new_graphs(
                    graph_cache,
                    notify_progress=notify_progress,
                    total_lines=total_lines,
                    completed_label="Command",
                )
            )
            if emit_graph_ready:
                graph_ready_emitted = await self._maybe_cache_graphs_on_chunk(
                    graph_cache=graph_cache,
                    emit_graph_ready=emit_graph_ready,
                    notify_log=notify_log,
                    graph_ready_task_id=graph_ready_task_id,
                    graph_ready_format=graph_ready_format,
                    graph_ready_initial=graph_ready_initial,
                    last_check=graph_poll_state,
                    force=True,
                )
        if emit_graph_ready and not graph_ready_emitted and graph_ready_initial is not None:
            try:
                graph_ready_emitted = await self._emit_graph_ready_events(
                    graph_ready_initial,
                    notify_log,
                    graph_ready_task_id,
                    graph_ready_format,
                )
            except Exception as exc:
                logger.debug("graph_ready fallback emission failed: %s", exc)
        if emit_graph_ready and not graph_ready_emitted:
            try:
                fallback_names = self._extract_named_graphs(code)
                if fallback_names:
                    async with self._ensure_graph_ready_lock():
                        await self._emit_graph_ready_for_graphs(
                            list(dict.fromkeys(fallback_names)),
                            notify_log=notify_log,
                            task_id=graph_ready_task_id,
                            export_format=graph_ready_format,
                            graph_ready_initial=graph_ready_initial,
                        )
            except Exception as exc:
                logger.debug("graph_ready fallback emission failed: %s", exc)

        combined = self._build_combined_log(tail, smcl_path, rc, trace, exc, start_offset=start_offset)
        
        # Use SMCL content as primary source for RC detection only when RC is ambiguous
        if exc is not None or rc in (-1, 1):
            parsed_rc = self._parse_rc_from_smcl(smcl_content)
            if parsed_rc is not None and parsed_rc != 0:
                rc = parsed_rc
            elif rc in (-1, 1):  # Also check text if rc is generic 1 or unset
                parsed_rc_text = self._parse_rc_from_text(combined)
                if parsed_rc_text is not None:
                    rc = parsed_rc_text
                elif rc == -1:
                    rc = 0  # Default to success if no error trace found

        # If RC looks wrong but SMCL shows no error markers, treat as success.
        if rc != 0 and smcl_content:
            has_err_tag = "{err}" in smcl_content
            rc_match = re.search(r"(?<!\w)r\((\d+)\)", smcl_content)
            if rc_match:
                try:
                    rc = int(rc_match.group(1))
                except Exception:
                    pass
            else:
                text_rc = None
                try:
                    text_rc = self._parse_rc_from_text(self._smcl_to_text(smcl_content))
                except Exception:
                    text_rc = None
                if not has_err_tag and text_rc is None:
                    rc = 0

        # If RC looks wrong but SMCL shows no error markers, treat as success.
        if rc != 0 and smcl_content:
            has_err_tag = "{err}" in smcl_content
            rc_match = re.search(r"(?<!\w)r\((\d+)\)", smcl_content)
            if rc_match:
                try:
                    rc = int(rc_match.group(1))
                except Exception:
                    pass
            else:
                text_rc = None
                try:
                    text_rc = self._parse_rc_from_text(self._smcl_to_text(smcl_content))
                except Exception:
                    text_rc = None
                if not has_err_tag and text_rc is None:
                    rc = 0

        success = (rc == 0 and exc is None)
        stderr_final = None
        error = None
        
        # authoritative output (Preserve SMCL tags as requested by user)
        stdout_final = smcl_content if smcl_content else combined
        # Clean the final output of internal maintenance artifacts
        stdout_final = self._clean_internal_smcl(stdout_final)
        
        # NOTE: We keep stdout_final populated even if log_path is set, 
        # so the user gets the exact SMCL result in the tool output.
        # server.py may still clear it for token efficiency.

        if not success:
            # Use SMCL as authoritative source for error extraction
            if smcl_content:
                msg, context = self._extract_error_from_smcl(smcl_content, rc)
            else:
                # Fallback to combined log
                msg, context = self._extract_error_and_context(combined, rc)

            error = ErrorEnvelope(
                message=msg,
                context=context,
                rc=rc,
                command=command,
                log_path=log_path,
                snippet=smcl_content[-800:] if smcl_content else combined[-800:],
                smcl_output=smcl_content,
            )
            # Put summary in stderr
            stderr_final = context
        
        duration = time.time() - start_time
        logger.info(
            "stata.run(stream) rc=%s success=%s trace=%s duration_ms=%.2f code_preview=%s",
            rc,
            success,
            trace,
            duration * 1000,
            code.replace("\n", "\\n")[:120],
        )

        result = CommandResponse(
            command=code,
            rc=rc,
            stdout=stdout_final,
            stderr=stderr_final,
            log_path=log_path,
            success=success,
            error=error,
            smcl_output=smcl_content,
        )

        if notify_progress is not None:
            await notify_progress(1, 1, "Finished")

        return result

    async def run_do_file_streaming(
    self,
    path: str,
    *,
    notify_log: Callable[[str], Awaitable[None]],
    notify_progress: Optional[Callable[[float, Optional[float], Optional[str]], Awaitable[None]]] = None,
    echo: bool = True,
    trace: bool = False,
    max_output_lines: Optional[int] = None,
    cwd: Optional[str] = None,
    auto_cache_graphs: bool = False,
    on_graph_cached: Optional[Callable[[str, bool], Awaitable[None]]] = None,
    emit_graph_ready: bool = False,
    graph_ready_task_id: Optional[str] = None,
    graph_ready_format: str = "svg",
) -> CommandResponse:
        effective_path, command, error_response = self._resolve_do_file_path(path, cwd)
        if error_response is not None:
            return error_response

        total_lines = self._count_do_file_lines(effective_path)
        dofile_text = ""
        try:
            dofile_text = pathlib.Path(effective_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            dofile_text = ""
        executed_lines = 0
        last_progress_time = 0.0
        dot_prompt = re.compile(r"^\.\s+\S")

        async def on_chunk_for_progress(chunk: str) -> None:
            nonlocal executed_lines, last_progress_time
            if total_lines <= 0 or notify_progress is None:
                return
            for line in chunk.splitlines():
                if dot_prompt.match(line):
                    executed_lines += 1
                    if executed_lines > total_lines:
                        executed_lines = total_lines

            now = time.monotonic()
            if executed_lines > 0 and (now - last_progress_time) >= 0.25:
                last_progress_time = now
                await notify_progress(
                    float(executed_lines),
                    float(total_lines),
                    f"Executing do-file: {executed_lines}/{total_lines}",
                )

        if not self._initialized:
            self.init()

        auto_cache_graphs = auto_cache_graphs or emit_graph_ready

        start_time = time.time()
        exc: Optional[Exception] = None
        smcl_content = ""
        smcl_path = None

        graph_cache = self._init_streaming_graph_cache(auto_cache_graphs, on_graph_cached, notify_log)
        _log_file, log_path, tail, tee = self._create_streaming_log(trace=trace)

        smcl_path = self._create_smcl_log_path()
        smcl_log_name = self._make_smcl_log_name()
        start_offset = 0
        if self._persistent_log_path:
            smcl_path = self._persistent_log_path
            smcl_log_name = self._persistent_log_name
            try:
                start_offset = os.path.getsize(smcl_path)
            except OSError:
                start_offset = 0

        # Inform the MCP client immediately where to read/tail the output.
        # We provide the cleaned plain-text log_path as the primary 'path' to satisfy 
        # requirements for clean logs without maintenance boilerplate.
        await notify_log(json.dumps({"event": "log_path", "path": log_path, "smcl_path": smcl_path}))

        rc = -1
        graph_ready_initial = self._capture_graph_state(graph_cache, emit_graph_ready)
        self._current_command_code = dofile_text if dofile_text else command
        
        # Increment AFTER capture
        self._increment_command_idx()
        
        graph_poll_state = [0.0]

        done = anyio.Event()

        try:
            async with anyio.create_task_group() as tg:
                async def on_chunk_for_graphs(_chunk: str) -> None:
                    # Background the graph check so we don't block SMCL streaming or task completion.
                    # Use tg.start_soon instead of asyncio.create_task to ensure all checks 
                    # finish before the command is considered complete.
                    tg.start_soon(
                        functools.partial(
                            self._maybe_cache_graphs_on_chunk,
                            graph_cache=graph_cache,
                            emit_graph_ready=emit_graph_ready,
                            notify_log=notify_log,
                            graph_ready_task_id=graph_ready_task_id,
                            graph_ready_format=graph_ready_format,
                            graph_ready_initial=graph_ready_initial,
                            last_check=graph_poll_state,
                        )
                    )

                async def actual_on_chunk(chunk: str) -> None:
                    # Inform progress tracker
                    await on_chunk_for_progress(chunk)
                    
                    # Background graph detection
                    if graph_cache:
                        await on_chunk_for_graphs(chunk)

                async def stream_smcl() -> None:
                    try:
                        await self._stream_smcl_log(
                            smcl_path=smcl_path,
                            notify_log=notify_log,
                            done=done,
                            on_chunk=actual_on_chunk,
                            start_offset=start_offset,
                            tee=tee,
                        )
                    except Exception as exc:
                        logger.debug("SMCL streaming failed: %s", exc)

                tg.start_soon(stream_smcl)

                if notify_progress is not None:
                    if total_lines > 0:
                        await notify_progress(0, float(total_lines), f"Executing do-file: 0/{total_lines}")
                    else:
                        await notify_progress(0, None, "Running do-file")

                try:
                    run_blocking = lambda: self._run_streaming_blocking(
                        command=command,
                        tee=tee,
                        cwd=cwd,
                        trace=trace,
                        echo=echo,
                        smcl_path=smcl_path,
                        smcl_log_name=smcl_log_name,
                        hold_attr="_hold_name_do",
                        require_smcl_log=True,
                    )
                    try:
                        rc, exc = await anyio.to_thread.run_sync(
                            run_blocking,
                            abandon_on_cancel=True,
                        )
                    except TypeError:
                        rc, exc = await anyio.to_thread.run_sync(run_blocking)
                except Exception as e:
                    exc = e
                    if rc in (-1, 0):
                        rc = 1
                except get_cancelled_exc_class():
                    self._request_break_in()
                    await self._wait_for_stata_stop()
                    raise
                finally:
                    done.set()
        except* Exception as exc_group:
            logger.debug("SMCL streaming task group failed: %s", exc_group)
        finally:
            tee.close()

        # Read SMCL content as the authoritative source
        smcl_content = self._read_smcl_file(smcl_path, start_offset=start_offset)
        # Clean internal maintenance immediately 
        smcl_content = self._clean_internal_smcl(smcl_content, strip_output=False) 


        graph_ready_emitted = 0
        if graph_cache:
            asyncio.create_task(
                self._cache_new_graphs(
                    graph_cache,
                    notify_progress=notify_progress,
                    total_lines=total_lines,
                    completed_label="Do-file",
                )
            )
            if emit_graph_ready:
                graph_ready_emitted = await self._maybe_cache_graphs_on_chunk(
                    graph_cache=graph_cache,
                    emit_graph_ready=emit_graph_ready,
                    notify_log=notify_log,
                    graph_ready_task_id=graph_ready_task_id,
                    graph_ready_format=graph_ready_format,
                    graph_ready_initial=graph_ready_initial,
                    last_check=graph_poll_state,
                    force=True,
                )
        if emit_graph_ready and not graph_ready_emitted and graph_ready_initial is not None:
            try:
                graph_ready_emitted = await self._emit_graph_ready_events(
                    graph_ready_initial,
                    notify_log,
                    graph_ready_task_id,
                    graph_ready_format,
                )
            except Exception as exc:
                logger.debug("graph_ready fallback emission failed: %s", exc)
        if emit_graph_ready and not graph_ready_emitted:
            try:
                fallback_names = self._extract_named_graphs(dofile_text)
                if fallback_names:
                    async with self._ensure_graph_ready_lock():
                        await self._emit_graph_ready_for_graphs(
                            list(dict.fromkeys(fallback_names)),
                            notify_log=notify_log,
                            task_id=graph_ready_task_id,
                            export_format=graph_ready_format,
                            graph_ready_initial=graph_ready_initial,
                        )
            except Exception as exc:
                logger.debug("graph_ready fallback emission failed: %s", exc)

        combined = self._build_combined_log(tail, smcl_path, rc, trace, exc, start_offset=start_offset)
        
        # Use SMCL content as primary source for RC detection only when RC is ambiguous
        if exc is not None or rc in (-1, 1):
            parsed_rc = self._parse_rc_from_smcl(smcl_content)
            if parsed_rc is not None and parsed_rc != 0:
                rc = parsed_rc
            elif rc in (-1, 1):
                parsed_rc_text = self._parse_rc_from_text(combined)
                if parsed_rc_text is not None:
                    rc = parsed_rc_text
                elif rc == -1:
                    rc = 0  # Default to success if no error found

        # If RC looks wrong but SMCL shows no error markers, treat as success.
        if rc != 0 and smcl_content:
            has_err_tag = "{err}" in smcl_content
            rc_match = re.search(r"(?<!\w)r\((\d+)\)", smcl_content)
            if rc_match:
                try:
                    rc = int(rc_match.group(1))
                except Exception:
                    pass
            else:
                text_rc = None
                try:
                    text_rc = self._parse_rc_from_text(self._smcl_to_text(smcl_content))
                except Exception:
                    text_rc = None
                if not has_err_tag and text_rc is None:
                    rc = 0

        success = (rc == 0 and exc is None)
        stderr_final = None
        error = None
        
        # authoritative output (Preserve SMCL tags as requested by user)
        stdout_final = smcl_content if smcl_content else combined
        # Clean the final output of internal maintenance artifacts
        stdout_final = self._clean_internal_smcl(stdout_final)
        
        # NOTE: We keep stdout_final populated even if log_path is set, 
        # so the user gets the exact SMCL result in the tool output.
        # server.py may still clear it for token efficiency.

        if not success:
            # Use SMCL as authoritative source for error extraction
            if smcl_content:
                msg, context = self._extract_error_from_smcl(smcl_content, rc)
            else:
                # Fallback to combined log
                msg, context = self._extract_error_and_context(combined, rc)

            error = ErrorEnvelope(
                message=msg,
                context=context,
                rc=rc,
                command=command,
                log_path=log_path,
                snippet=smcl_content[-800:] if smcl_content else combined[-800:],
                smcl_output=smcl_content,
            )
            # Put summary in stderr
            stderr_final = context
            # Token Efficiency optimization: we keep stdout for local users/tests
            # but if it's very large, we might truncate it later
        
        duration = time.time() - start_time
        logger.info(
            "stata.run(do stream) rc=%s success=%s trace=%s duration_ms=%.2f path=%s",
            rc,
            success,
            trace,
            duration * 1000,
            effective_path,
        )

        result = CommandResponse(
            command=command,
            rc=rc,
            stdout=stdout_final,
            stderr=stderr_final,
            log_path=log_path,
            success=success,
            error=error,
            smcl_output=smcl_content,
        )

        if notify_progress is not None:
            if total_lines > 0:
                await notify_progress(float(total_lines), float(total_lines), f"Executing do-file: {total_lines}/{total_lines}")
            else:
                await notify_progress(1, 1, "Finished")

        return result

    def run_command_structured(self, code: str, echo: bool = True, trace: bool = False, max_output_lines: Optional[int] = None, cwd: Optional[str] = None) -> CommandResponse:
        """Runs a Stata command and returns a structured envelope.

        Args:
            code: The Stata command to execute.
            echo: If True, the command itself is included in the output.
            trace: If True, enables trace mode for debugging.
            max_output_lines: If set, truncates stdout to this many lines (token efficiency).
        """
        result = self._exec_with_capture(code, echo=echo, trace=trace, cwd=cwd)

        return self._truncate_command_output(result, max_output_lines)

    def get_data(self, start: int = 0, count: int = 50) -> List[Dict[str, Any]]:
        """Returns valid JSON-serializable data."""
        if not self._initialized:
            self.init()

        if count > self.MAX_DATA_ROWS:
            count = self.MAX_DATA_ROWS

        with self._exec_lock:
            try:
                # Use pystata integration to retrieve data
                df = self.stata.pdataframe_from_data()

                # Slice
                sliced = df.iloc[start : start + count]

                # Convert to dict
                return sliced.to_dict(orient="records")
            except Exception as e:
                return [{"error": f"Failed to retrieve data: {e}"}]

    def list_variables(self) -> List[Dict[str, str]]:
        """Returns list of variables with labels."""
        if not self._initialized:
            self.init()

        # We can use sfi to be efficient
        from sfi import Data  # type: ignore[import-not-found]
        vars_info = []
        with self._exec_lock:
            for i in range(Data.getVarCount()):
                var_index = i # 0-based
                name = Data.getVarName(var_index)
                label = Data.getVarLabel(var_index)
                type_str = Data.getVarType(var_index) # Returns int

                vars_info.append({
                    "name": name,
                    "label": label,
                    "type": str(type_str),
                })
        return vars_info

    def get_dataset_state(self) -> Dict[str, Any]:
        """Return basic dataset state without mutating the dataset."""
        if not self._initialized:
            self.init()

        from sfi import Data, Macro  # type: ignore[import-not-found]

        with self._exec_lock:
            n = int(Data.getObsTotal())
            k = int(Data.getVarCount())

            frame = "default"
            sortlist = ""
            changed = False
            # Use a combined fetch for dataset state to minimize roundtrips
            try:
                state_bundle = (
                    "macro define mcp_frame \"`c(frame)'\"\n"
                    "macro define mcp_sortlist \"`c(sortlist)'\"\n"
                    "macro define mcp_changed \"`c(changed)'\""
                )
                self.stata.run(state_bundle, echo=False)
                frame = str(Macro.getGlobal("mcp_frame") or "default")
                sortlist = str(Macro.getGlobal("mcp_sortlist") or "")
                changed = bool(int(float(Macro.getGlobal("mcp_changed") or "0")))
                self.stata.run("macro drop mcp_frame mcp_sortlist mcp_changed", echo=False)
            except Exception:
                logger.debug("Failed to get dataset state macros", exc_info=True)

        return {"frame": frame, "n": n, "k": k, "sortlist": sortlist, "changed": changed}

    def _require_data_in_memory(self) -> None:
        state = self.get_dataset_state()
        if int(state.get("k", 0) or 0) == 0 and int(state.get("n", 0) or 0) == 0:
            # Stata empty dataset could still have k>0 n==0; treat that as ok.
            raise RuntimeError("No data in memory")

    def _get_var_index_map(self) -> Dict[str, int]:
        from sfi import Data  # type: ignore[import-not-found]

        out: Dict[str, int] = {}
        with self._exec_lock:
            for i in range(int(Data.getVarCount())):
                try:
                    out[str(Data.getVarName(i))] = i
                except Exception:
                    continue
        return out

    def list_variables_rich(self) -> List[Dict[str, Any]]:
        """Return variable metadata (name/type/label/format/valueLabel) without modifying the dataset."""
        if not self._initialized:
            self.init()

        from sfi import Data  # type: ignore[import-not-found]

        vars_info: List[Dict[str, Any]] = []
        for i in range(int(Data.getVarCount())):
            name = str(Data.getVarName(i))
            label = None
            fmt = None
            vtype = None
            value_label = None
            try:
                label = Data.getVarLabel(i)
            except Exception:
                label = None
            try:
                fmt = Data.getVarFormat(i)
            except Exception:
                fmt = None
            try:
                vtype = Data.getVarType(i)
            except Exception:
                vtype = None

            vars_info.append(
                {
                    "name": name,
                    "type": str(vtype) if vtype is not None else None,
                    "label": label if label else None,
                    "format": fmt if fmt else None,
                    "valueLabel": value_label,
                }
            )
        return vars_info

    @staticmethod
    def _is_stata_missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, float):
            # Stata missing values typically show up as very large floats via sfi.Data.get
            return value > 8.0e307
        return False

    def _normalize_cell(self, value: Any, *, max_chars: int) -> tuple[Any, bool]:
        if self._is_stata_missing(value):
            return ".", False
        if isinstance(value, str):
            if len(value) > max_chars:
                return value[:max_chars], True
            return value, False
        return value, False

    def get_page(
        self,
        *,
        offset: int,
        limit: int,
        vars: List[str],
        include_obs_no: bool,
        max_chars: int,
        obs_indices: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        if not self._initialized:
            self.init()

        from sfi import Data  # type: ignore[import-not-found]

        state = self.get_dataset_state()
        n = int(state.get("n", 0) or 0)
        k = int(state.get("k", 0) or 0)
        if k == 0 and n == 0:
            raise RuntimeError("No data in memory")

        var_map = self._get_var_index_map()
        for v in vars:
            if v not in var_map:
                raise ValueError(f"Invalid variable: {v}")

        if obs_indices is None:
            start = offset
            end = min(offset + limit, n)
            if start >= n:
                rows: list[list[Any]] = []
                returned = 0
                obs_list: list[int] = []
            else:
                obs_list = list(range(start, end))
                raw_rows = Data.get(var=vars, obs=obs_list)
                rows = raw_rows
                returned = len(rows)
        else:
            start = offset
            end = min(offset + limit, len(obs_indices))
            obs_list = obs_indices[start:end]
            raw_rows = Data.get(var=vars, obs=obs_list) if obs_list else []
            rows = raw_rows
            returned = len(rows)

        out_vars = list(vars)
        out_rows: list[list[Any]] = []
        truncated_cells = 0

        if include_obs_no:
            out_vars = ["_n"] + out_vars

        for idx, raw in enumerate(rows):
            norm_row: list[Any] = []
            if include_obs_no:
                norm_row.append(int(obs_list[idx]) + 1)
            for cell in raw:
                norm, truncated = self._normalize_cell(cell, max_chars=max_chars)
                if truncated:
                    truncated_cells += 1
                norm_row.append(norm)
            out_rows.append(norm_row)

        return {
            "vars": out_vars,
            "rows": out_rows,
            "returned": returned,
            "truncated_cells": truncated_cells,
        }

    def get_arrow_stream(
        self,
        *,
        offset: int,
        limit: int,
        vars: List[str],
        include_obs_no: bool,
        obs_indices: Optional[List[int]] = None,
    ) -> bytes:
        """
        Returns an Apache Arrow IPC stream (as bytes) for the requested data page.
        Uses Polars if available (faster), falls back to Pandas.
        """
        if not self._initialized:
            self.init()
        
        import pyarrow as pa
        from sfi import Data  # type: ignore[import-not-found]
        
        use_polars = _get_polars_available()
        if use_polars:
            import polars as pl
        else:
            import pandas as pd
        
        state = self.get_dataset_state()
        n = int(state.get("n", 0) or 0)
        k = int(state.get("k", 0) or 0)
        if k == 0 and n == 0:
            raise RuntimeError("No data in memory")
            
        var_map = self._get_var_index_map()
        for v in vars:
            if v not in var_map:
                raise ValueError(f"Invalid variable: {v}")
        
        # Determine observations to fetch
        if obs_indices is None:
            start = offset
            end = min(offset + limit, n)
            obs_list = list(range(start, end)) if start < n else []
        else:
            start = offset
            end = min(offset + limit, len(obs_indices))
            obs_list = obs_indices[start:end]
        
        try:
            if not obs_list:
                # Empty schema-only table
                if use_polars:
                    schema_cols = {}
                    if include_obs_no:
                        schema_cols["_n"] = pl.Int64
                    for v in vars:
                        schema_cols[v] = pl.Utf8
                    table = pl.DataFrame(schema=schema_cols).to_arrow()
                else:
                    columns = {}
                    if include_obs_no:
                        columns["_n"] = pa.array([], type=pa.int64())
                    for v in vars:
                        columns[v] = pa.array([], type=pa.string())
                    table = pa.table(columns)
            else:
                # Fetch all data in one C-call
                raw_data = Data.get(var=vars, obs=obs_list, valuelabel=False)
                
                if use_polars:
                    df = pl.DataFrame(raw_data, schema=vars, orient="row")
                    if include_obs_no:
                        obs_nums = [i + 1 for i in obs_list]
                        df = df.with_columns(pl.Series("_n", obs_nums, dtype=pl.Int64))
                        df = df.select(["_n"] + vars)
                    table = df.to_arrow()
                else:
                    df = pd.DataFrame(raw_data, columns=vars)
                    if include_obs_no:
                        df.insert(0, "_n", [i + 1 for i in obs_list])
                    table = pa.Table.from_pandas(df, preserve_index=False)
            
            # Serialize to IPC Stream
            sink = pa.BufferOutputStream()
            with pa.RecordBatchStreamWriter(sink, table.schema) as writer:
                writer.write_table(table)
            
            return sink.getvalue().to_pybytes()

        except Exception as e:
            raise RuntimeError(f"Failed to generate Arrow stream: {e}")

    _FILTER_IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

    def _extract_filter_vars(self, filter_expr: str) -> List[str]:
        tokens = set(self._FILTER_IDENT.findall(filter_expr or ""))
        # Exclude python keywords we might inject.
        exclude = {"and", "or", "not", "True", "False", "None"}
        var_map = self._get_var_index_map()
        vars_used = [t for t in tokens if t not in exclude and t in var_map]
        return sorted(vars_used)

    def _compile_filter_expr(self, filter_expr: str) -> Any:
        expr = (filter_expr or "").strip()
        if not expr:
            raise ValueError("Empty filter")

        # Stata boolean operators.
        expr = expr.replace("&", " and ").replace("|", " or ")

        # Replace missing literal '.' (but not numeric decimals like 0.5).
        expr = re.sub(r"(?<![0-9])\.(?![0-9A-Za-z_])", "None", expr)

        try:
            return compile(expr, "<filterExpr>", "eval")
        except Exception as e:
            raise ValueError(f"Invalid filter expression: {e}")

    def validate_filter_expr(self, filter_expr: str) -> None:
        if not self._initialized:
            self.init()
        state = self.get_dataset_state()
        if int(state.get("k", 0) or 0) == 0 and int(state.get("n", 0) or 0) == 0:
            raise RuntimeError("No data in memory")

        vars_used = self._extract_filter_vars(filter_expr)
        if not vars_used:
            # still allow constant expressions like "1" or "True"
            self._compile_filter_expr(filter_expr)
            return
        self._compile_filter_expr(filter_expr)

    def compute_view_indices(self, filter_expr: str, *, chunk_size: int = 5000) -> List[int]:
        if not self._initialized:
            self.init()

        from sfi import Data  # type: ignore[import-not-found]

        state = self.get_dataset_state()
        n = int(state.get("n", 0) or 0)
        k = int(state.get("k", 0) or 0)
        if k == 0 and n == 0:
            raise RuntimeError("No data in memory")

        vars_used = self._extract_filter_vars(filter_expr)
        code = self._compile_filter_expr(filter_expr)
        _ = self._get_var_index_map()

        is_string_vars = []
        if vars_used:
            try:
                from sfi import Variable  # type: ignore
                is_string_vars = [Variable.isString(v) for v in vars_used]
            except (ImportError, AttributeError):
                try:
                    is_string_vars = [Data.isVarTypeStr(v) or Data.isVarTypeStrL(v) for v in vars_used]
                except AttributeError:
                    # Stata 19+ compatibility
                    is_string_vars = [Data.isVarTypeString(v) for v in vars_used]

        indices: List[int] = []
        for start in range(0, n, chunk_size):
            end = min(start + chunk_size, n)
            obs_list = list(range(start, end))
            raw_rows = Data.get(var=vars_used, obs=obs_list) if vars_used else [[None] for _ in obs_list]

            # Try Rust optimization for the chunk
            if vars_used and raw_rows:
                # Transpose rows to columns for Rust
                cols = []
                # Extract columns
                for j in range(len(vars_used)):
                    col_data_list = [row[j] for row in raw_rows]
                    if not is_string_vars[j]:
                        import numpy as np
                        col_data = np.array(col_data_list, dtype=np.float64)
                    else:
                        col_data = col_data_list
                    cols.append(col_data)

                rust_indices = compute_filter_indices(filter_expr, vars_used, cols, is_string_vars)
                if rust_indices is not None:
                    indices.extend([int(obs_list[i]) for i in rust_indices])
                    continue

            for row_i, obs in enumerate(obs_list):
                env: Dict[str, Any] = {}
                if vars_used:
                    for j, v in enumerate(vars_used):
                        val = raw_rows[row_i][j]
                        env[v] = None if self._is_stata_missing(val) else val

                ok = False
                try:
                    ok = bool(eval(code, {"__builtins__": {}}, env))
                except NameError as e:
                    raise ValueError(f"Invalid filter: {e}")
                except Exception as e:
                    raise ValueError(f"Invalid filter: {e}")

                if ok:
                    indices.append(int(obs))

        return indices

    def apply_sort(self, sort_spec: List[str]) -> None:
        """
        Apply sorting to the dataset using gsort.

        Args:
            sort_spec: List of variables to sort by, with optional +/- prefix.
                      e.g., ["-price", "+mpg"] sorts by price descending, then mpg ascending.
                      No prefix is treated as ascending (+).

        Raises:
            ValueError: If sort_spec is invalid or contains invalid variables
            RuntimeError: If no data in memory or sort command fails
        """
        if not self._initialized:
            self.init()

        state = self.get_dataset_state()
        if int(state.get("k", 0) or 0) == 0 and int(state.get("n", 0) or 0) == 0:
            raise RuntimeError("No data in memory")

        if not sort_spec or not isinstance(sort_spec, list):
            raise ValueError("sort_spec must be a non-empty list")

        # Validate all variables exist
        var_map = self._get_var_index_map()
        for spec in sort_spec:
            if not isinstance(spec, str) or not spec:
                raise ValueError(f"Invalid sort specification: {spec!r}")
            # Extract variable name (remove +/- prefix if present)
            varname = spec.lstrip("+-")
            if not varname:
                raise ValueError(f"Invalid sort specification: {spec!r}")

            if varname not in var_map:
                raise ValueError(f"Variable not found: {varname}")

        # Build gsort command
        # gsort uses - for descending, + or nothing for ascending
        gsort_args = []
        for spec in sort_spec:
            if spec.startswith("-") or spec.startswith("+"):
                gsort_args.append(spec)
            else:
                # No prefix means ascending, add + explicitly for clarity
                gsort_args.append(f"+{spec}")

        cmd = f"gsort {' '.join(gsort_args)}"

        try:
            # Sorting is hot-path for UI paging; use lightweight execution.
            result = self.exec_lightweight(cmd)
            if not result.success:
                error_msg = result.stderr or "Sort failed"
                raise RuntimeError(f"Failed to sort dataset: {error_msg}")
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"Failed to sort dataset: {e}")

    def get_variable_details(self, varname: str) -> str:
        """Returns codebook/summary for a specific variable while preserving state."""
        # Use _exec_no_capture_silent to preserve r()/e() results
        resp = self._exec_no_capture_silent(f"codebook {varname}", echo=False)
        if resp.success:
            # _exec_no_capture_silent captures output in resp.error.stdout if it fails,
            # but wait, it doesn't return stdout in CommandResponse for success?
            # Let me check CommandResponse creation in _exec_no_capture_silent.
            pass
        return resp.stdout or ""

    def list_variables_structured(self) -> VariablesResponse:
        vars_info: List[VariableInfo] = []
        for item in self.list_variables():
            vars_info.append(
                VariableInfo(
                    name=item.get("name", ""),
                    label=item.get("label"),
                    type=item.get("type"),
                )
            )
        return VariablesResponse(variables=vars_info)

    def list_graphs(self, *, force_refresh: bool = False) -> List[str]:
        """Returns list of graphs in memory with TTL caching."""
        if not self._initialized:
            self.init()

        import time

        # Prevent recursive Stata calls - if we're already executing, return cached or empty
        if self._is_executing:
            with self._list_graphs_cache_lock:
                if self._list_graphs_cache is not None:
                    logger.debug("Recursive list_graphs call prevented, returning cached value")
                    if self._list_graphs_cache and hasattr(self._list_graphs_cache[0], "name"):
                        return [g.name for g in self._list_graphs_cache]
                    return self._list_graphs_cache
                else:
                    logger.debug("Recursive list_graphs call prevented, returning empty list")
                    return []

        # Check if cache is valid
        current_time = time.time()
        with self._list_graphs_cache_lock:
            if (not force_refresh and self._list_graphs_cache is not None and
                current_time - self._list_graphs_cache_time < self.LIST_GRAPHS_TTL):
                if self._list_graphs_cache and hasattr(self._list_graphs_cache[0], "name"):
                    return [g.name for g in self._list_graphs_cache]
                return self._list_graphs_cache

        # Cache miss or expired, fetch fresh data
        with self._exec_lock:
            try:
                # Preservation of r() results is critical because this can be called
                # automatically after every user command (e.g., during streaming).
                import time
                hold_name = f"_mcp_ghold_{int(time.time() * 1000 % 1000000)}"
                try:
                    self.stata.run(f"capture _return hold {hold_name}", echo=False)
                except SystemError:
                    import traceback
                    sys.stderr.write(traceback.format_exc())
                    sys.stderr.flush()
                    raise
                
                try:
                    # Bundle name listing and metadata retrieval into one Stata call for efficiency
                    bundle = (
                        "macro define mcp_graph_list \"\"\n"
                        "global mcp_graph_details \"\"\n"
                        "quietly graph dir, memory\n"
                        "macro define mcp_graph_list \"`r(list)'\"\n"
                        "if \"`r(list)'\" != \"\" {\n"
                        "  foreach g in `r(list)' {\n"
                        "    quietly graph describe `g'\n"
                        "    global mcp_graph_details \"$mcp_graph_details `g'|`r(command_date)' `r(command_time)';\"\n"
                        "  }\n"
                        "}"
                    )
                    self.stata.run(bundle, echo=False)
                    from sfi import Macro  # type: ignore[import-not-found]
                    graph_list_str = Macro.getGlobal("mcp_graph_list")
                    details_str = Macro.getGlobal("mcp_graph_details")
                    # Cleanup global to keep Stata environment tidy
                    self.stata.run("macro drop mcp_graph_details", echo=False)
                finally:
                    try:
                        self.stata.run(f"capture _return restore {hold_name}", echo=False)
                    except SystemError:
                        import traceback
                        sys.stderr.write(traceback.format_exc())
                        sys.stderr.flush()
                        raise

                import shlex
                raw_list = shlex.split(graph_list_str or "")

                # Parse details: "name1|date time; name2|date time;"
                details_map = {}
                if details_str:
                    for item in details_str.split(';'):
                        item = item.strip()
                        if not item or '|' not in item:
                            continue
                        gname, ts = item.split('|', 1)
                        details_map[gname.strip()] = ts.strip()

                # Map internal Stata names back to user-facing names when we have an alias.
                reverse = getattr(self, "_graph_name_reverse", {})
                
                graph_infos = []
                for n in raw_list:
                    graph_infos.append(GraphInfo(
                        name=reverse.get(n, n),
                        active=False,
                        created=details_map.get(n)
                    ))

                # Update cache
                with self._list_graphs_cache_lock:
                    self._list_graphs_cache = graph_infos
                    self._list_graphs_cache_time = time.time()
                
                return [g.name for g in graph_infos]
                
            except Exception as e:
                # On error, return cached result if available, otherwise empty list
                with self._list_graphs_cache_lock:
                    if self._list_graphs_cache is not None:
                        logger.warning(f"list_graphs failed, returning cached result: {e}")
                        if self._list_graphs_cache and hasattr(self._list_graphs_cache[0], "name"):
                            return [g.name for g in self._list_graphs_cache]
                        return self._list_graphs_cache
                logger.warning(f"list_graphs failed, no cache available: {e}")
                return []

    def list_graphs_structured(self) -> GraphListResponse:
        self.list_graphs()
        
        with self._list_graphs_cache_lock:
            if not self._list_graphs_cache:
                return GraphListResponse(graphs=[])
            
            # The cache now contains GraphInfo objects
            graphs = [g.model_copy() for g in self._list_graphs_cache]
        
        if graphs:
            # Most recently created/displayed graph is active in Stata
            graphs[-1].active = True
            
        return GraphListResponse(graphs=graphs)

    def invalidate_list_graphs_cache(self) -> None:
        """Invalidate the list_graphs cache to force fresh data on next call."""
        with self._list_graphs_cache_lock:
            self._list_graphs_cache = None
            self._list_graphs_cache_time = 0

    def export_graph(self, graph_name: str = None, filename: str = None, format: str = "pdf") -> str:
        """Exports graph to a temp file (pdf or png) and returns the path.

        On Windows, PyStata can crash when exporting PNGs directly. For PNG on
        Windows, we save the graph to .gph and invoke the Stata executable in
        batch mode to export the PNG out-of-process.
        """
        import tempfile

        fmt = (format or "pdf").strip().lower()
        if fmt not in {"pdf", "png", "svg"}:
            raise ValueError(f"Unsupported graph export format: {format}. Allowed: pdf, png, svg.")


        if not filename:
            suffix = f".{fmt}"
            # Use validated temp dir to avoid Windows write permission errors
            with tempfile.NamedTemporaryFile(prefix="mcp_stata_", suffix=suffix, dir=get_writable_temp_dir(), delete=False) as tmp:
                filename = tmp.name
            register_temp_file(filename)
        else:
            # Ensure fresh start
            p_filename = pathlib.Path(filename)
            if p_filename.exists():
                try:
                    p_filename.unlink()
                except Exception:
                    pass

        # Keep the user-facing path as a normal absolute path
        user_filename = pathlib.Path(filename).absolute()

        if fmt == "png" and is_windows():
            # 1) Save graph to a .gph file from the embedded session
            with tempfile.NamedTemporaryFile(prefix="mcp_stata_graph_", suffix=".gph", dir=get_writable_temp_dir(), delete=False) as gph_tmp:
                gph_path = pathlib.Path(gph_tmp.name)
            register_temp_file(gph_path)
            gph_path_for_stata = gph_path.as_posix()
            # Make the target graph current, then save without name() (which isn't accepted there)
            if graph_name:
                self._exec_no_capture_silent(f'quietly graph display {graph_name}', echo=False)
            save_cmd = f'quietly graph save "{gph_path_for_stata}", replace'
            save_resp = self._exec_no_capture_silent(save_cmd, echo=False)
            if not save_resp.success:
                msg = save_resp.error.message if save_resp.error else f"graph save failed (rc={save_resp.rc})"
                raise RuntimeError(msg)

            # 2) Prepare a do-file to export PNG externally
            user_filename_fwd = user_filename.as_posix()
            do_lines = [
                f'quietly graph use "{gph_path_for_stata}"',
                f'quietly graph export "{user_filename_fwd}", replace as(png)',
                "exit",
            ]
            with tempfile.NamedTemporaryFile(prefix="mcp_stata_export_", suffix=".do", dir=get_writable_temp_dir(), delete=False, mode="w", encoding="ascii") as do_tmp:
                do_tmp.write("\n".join(do_lines))
                do_path = pathlib.Path(do_tmp.name)
            register_temp_file(do_path)

            stata_exe = getattr(self, "_stata_exec_path", None)
            if not stata_exe or not pathlib.Path(stata_exe).exists():
                raise RuntimeError("Stata executable path unavailable for PNG export")

            workdir = do_path.parent
            log_path = do_path.with_suffix(".log")
            register_temp_file(log_path)

            cmd = [str(stata_exe), "/e", "do", str(do_path)]
            try:
                completed = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=workdir,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError("External Stata export timed out")
            finally:
                try:
                    do_path.unlink()
                except Exception:
                    # Ignore errors during temporary do-file cleanup (file may not exist or be locked)
                    logger.warning("Failed to remove temporary do-file: %s", do_path, exc_info=True)

                try:
                    gph_path.unlink()
                except Exception:
                    logger.warning("Failed to remove temporary graph file: %s", gph_path, exc_info=True)

                try:
                    if log_path.exists():
                        log_path.unlink()
                except Exception:
                    logger.warning("Failed to remove temporary log file: %s", log_path, exc_info=True)

            if completed.returncode != 0:
                err = completed.stderr.strip() or completed.stdout.strip() or str(completed.returncode)
                raise RuntimeError(f"External Stata export failed: {err}")

        else:
            # Stata prefers forward slashes in its command parser on Windows
            filename_for_stata = user_filename.as_posix()

            if graph_name:
                resolved = self._resolve_graph_name_for_stata(graph_name)
                # Use display + export without name() for maximum compatibility.
                # name(NAME) often fails in PyStata for non-active graphs (r(693)).
                # Graph identifiers must NOT be quoted in 'graph display'.
                disp_resp = self._exec_no_capture_silent(f'quietly graph display {resolved}', echo=False)
                if not disp_resp.success:
                    # graph display failed, likely rc=111 or 693
                    msg = disp_resp.error.message if disp_resp.error else f"Graph display failed (rc={disp_resp.rc})"
                    # Normalize for test expectations
                    if disp_resp.rc == 111:
                        msg = f"graph {resolved} not found r(111);"
                    raise RuntimeError(msg)
            
            cmd = f'quietly graph export "{filename_for_stata}", replace as({fmt})'

            # Avoid stdout/stderr redirection for graph export because PyStata's
            # output thread can crash on Windows when we swap stdio handles.
            resp = self._exec_no_capture_silent(cmd, echo=False)
            if not resp.success:
                # Retry once after a short pause in case Stata had a transient file handle issue
                time.sleep(0.2)
                resp_retry = self._exec_no_capture_silent(cmd, echo=False)
                if not resp_retry.success:
                    msg = resp_retry.error.message if resp_retry.error else f"graph export failed (rc={resp_retry.rc})"
                    raise RuntimeError(msg)
                resp = resp_retry

        if user_filename.exists():
            try:
                size = user_filename.stat().st_size
                if size == 0:
                    raise RuntimeError(f"Graph export failed: produced empty file {user_filename}")
                if size > self.MAX_GRAPH_BYTES:
                    raise RuntimeError(
                        f"Graph export failed: file too large (> {self.MAX_GRAPH_BYTES} bytes): {user_filename}"
                    )
            except Exception as size_err:
                # Clean up oversized or unreadable files
                try:
                    user_filename.unlink()
                except Exception:
                    pass
                raise size_err
            return str(user_filename)

        # If file missing, it failed. Check output for details.
        msg = resp.error.message if resp.error else "graph export failed: file missing"
        raise RuntimeError(msg)

    def get_help(self, topic: str, plain_text: bool = False) -> str:
        """Returns help text as Markdown (default) or plain text."""
        if not self._initialized:
            self.init()

        with self._exec_lock:
            # Try to locate the .sthlp help file
            # We use 'capture' to avoid crashing if not found.
            # Combined into a single bundle to prevent r(fn) from being cleared.
            from sfi import Macro  # type: ignore[import-not-found]
            bundle = (
                f"capture findfile {topic}.sthlp\n"
                "macro define mcp_help_file \"`r(fn)'\""
            )
            self.stata.run(bundle, echo=False)
            fn = Macro.getGlobal("mcp_help_file")

        if fn and os.path.exists(fn):
            try:
                with open(fn, 'r', encoding='utf-8', errors='replace') as f:
                    smcl = f.read()
                if plain_text:
                    return self._smcl_to_text(smcl)
                try:
                    return smcl_to_markdown(smcl, adopath=os.path.dirname(fn), current_file=os.path.splitext(os.path.basename(fn))[0])
                except Exception as parse_err:
                    logger.warning("SMCL to Markdown failed, falling back to plain text: %s", parse_err)
                    return self._smcl_to_text(smcl)
            except Exception as e:
                logger.warning("Help file read failed for %s: %s", topic, e)

        # If no help file found, return a fallback message
        return f"Help file for '{topic}' not found."

    def get_stored_results(self, force_fresh: bool = False) -> Dict[str, Any]:
        """Returns e() and r() results using SFI for maximum reliability."""
        if not force_fresh and self._last_results is not None:
            return self._last_results

        if not self._initialized:
            self.init()

        with self._exec_lock:
            # Capture the current RC first using SFI (non-mutating)
            try:
                from sfi import Scalar, Macro
                preserved_rc = int(float(Scalar.getValue("c(rc)") or 0))
            except Exception:
                preserved_rc = 0

            results = {"r": {}, "e": {}, "s": {}}
            
            try:
                # Fetch lists of names. macro define `: ...' is non-mutating for results.
                fetch_names_block = (
                    "macro define mcp_r_sc \"`: r(scalars)'\"\n"
                    "macro define mcp_r_ma \"`: r(macros)'\"\n"
                    "macro define mcp_e_sc \"`: e(scalars)'\"\n"
                    "macro define mcp_e_ma \"`: e(macros)'\"\n"
                    "macro define mcp_s_sc \"`: s(scalars)'\"\n"
                    "macro define mcp_s_ma \"`: s(macros)'\"\n"
                )
                self.stata.run(fetch_names_block, echo=False)
                
                for rclass in ["r", "e", "s"]:
                    sc_names = (Macro.getGlobal(f"mcp_{rclass}_sc") or "").split()
                    ma_names = (Macro.getGlobal(f"mcp_{rclass}_ma") or "").split()
                    
                    # Fetch Scalars via SFI (fast, non-mutating)
                    for name in sc_names:
                        try:
                            val = Scalar.getValue(f"{rclass}({name})")
                            results[rclass][name] = val
                        except Exception:
                            pass
                    
                    # Fetch Macros via global expansion
                    if ma_names:
                        # Bundle macro copying to minimize roundtrips
                        # We use global macros as a transfer area
                        copy_block = ""
                        for name in ma_names:
                            copy_block += f"macro define mcp_m_{rclass}_{name} \"`{rclass}({name})'\"\n"
                        
                        if copy_block:
                            self.stata.run(copy_block, echo=False)
                            for name in ma_names:
                                results[rclass][name] = Macro.getGlobal(f"mcp_m_{rclass}_{name}")
                
                # Cleanup and Restore state
                self.stata.run("macro drop mcp_*", echo=False)
                
                if preserved_rc > 0:
                    self.stata.run(f"capture error {preserved_rc}", echo=False)
                else:
                    self.stata.run("capture", echo=False)

                self._last_results = results
                return results
            except Exception as e:
                logger.error(f"SFI-based get_stored_results failed: {e}")
                return {"r": {}, "e": {}}

    def invalidate_graph_cache(self, graph_name: str = None) -> None:
        """Invalidate cache for specific graph or all graphs.
        
        Args:
            graph_name: Specific graph name to invalidate. If None, clears all cache.
        """
        self._initialize_cache()
        
        with self._cache_lock:
            if graph_name is None:
                # Clear all cache
                self._preemptive_cache.clear()
            else:
                # Clear specific graph cache
                if graph_name in self._preemptive_cache:
                    del self._preemptive_cache[graph_name]
                # Also clear hash if present
                hash_key = f"{graph_name}_hash"
                if hash_key in self._preemptive_cache:
                    del self._preemptive_cache[hash_key]

    def _initialize_cache(self) -> None:
        """Initialize cache in a thread-safe manner."""
        import tempfile
        import threading
        import os
        import uuid
        
        with StataClient._cache_init_lock:  # Use class-level lock
            if not hasattr(self, '_cache_initialized'):
                    self._preemptive_cache = {}
                    self._cache_access_times = {}  # Track access times for LRU
                    self._cache_sizes = {}  # Track individual cache item sizes
                    self._total_cache_size = 0  # Track total cache size in bytes
                    # Use unique identifier to avoid conflicts
                    unique_id = f"preemptive_cache_{uuid.uuid4().hex[:8]}_{os.getpid()}"
                    self._preemptive_cache_dir = tempfile.mkdtemp(prefix=unique_id, dir=get_writable_temp_dir())
                    register_temp_dir(self._preemptive_cache_dir)
                    self._cache_lock = threading.Lock()
                    self._cache_initialized = True
                    
                    # Register cleanup function
                    import atexit
                    atexit.register(self._cleanup_cache)
            else:
                # Cache already initialized, but directory might have been removed.
                if (not hasattr(self, '_preemptive_cache_dir') or
                    not self._preemptive_cache_dir or
                    not os.path.isdir(self._preemptive_cache_dir)):
                    unique_id = f"preemptive_cache_{uuid.uuid4().hex[:8]}_{os.getpid()}"
                    self._preemptive_cache_dir = tempfile.mkdtemp(prefix=unique_id, dir=get_writable_temp_dir())
                    register_temp_dir(self._preemptive_cache_dir)
    
    def _cleanup_cache(self) -> None:
        """Clean up cache directory and files."""
        import os
        import shutil
        
        if hasattr(self, '_preemptive_cache_dir') and self._preemptive_cache_dir:
            try:
                shutil.rmtree(self._preemptive_cache_dir, ignore_errors=True)
            except Exception:
                pass  # Best effort cleanup
        
        if hasattr(self, '_preemptive_cache'):
            self._preemptive_cache.clear()
    
    def _evict_cache_if_needed(self, new_item_size: int = 0) -> None:
        """
        Evict least recently used cache items if cache size limits are exceeded.

        NOTE: The caller is responsible for holding ``self._cache_lock`` while
        invoking this method, so that eviction and subsequent cache insertion
        (if any) occur within a single critical section.
        """
        import time
        
        # Check if we need to evict based on count or size
        needs_eviction = (
            len(self._preemptive_cache) > StataClient.MAX_CACHE_SIZE or
            self._total_cache_size + new_item_size > StataClient.MAX_CACHE_BYTES
        )
        
        if not needs_eviction:
            return
        
        # Sort by access time (oldest first)
        items_by_access = sorted(
            self._cache_access_times.items(),
            key=lambda x: x[1]
        )
        
        evicted_count = 0
        for graph_name, access_time in items_by_access:
            if (len(self._preemptive_cache) < StataClient.MAX_CACHE_SIZE and 
                self._total_cache_size + new_item_size <= StataClient.MAX_CACHE_BYTES):
                break
            
            # Remove from cache
            if graph_name in self._preemptive_cache:
                cache_path = self._preemptive_cache[graph_name]
                
                # Remove file
                try:
                    if os.path.exists(cache_path):
                        os.remove(cache_path)
                except Exception:
                    pass
                
                # Update tracking
                item_size = self._cache_sizes.get(graph_name, 0)
                del self._preemptive_cache[graph_name]
                del self._cache_access_times[graph_name]
                if graph_name in self._cache_sizes:
                    del self._cache_sizes[graph_name]
                self._total_cache_size -= item_size
                evicted_count += 1
                
                # Remove hash entry if exists
                hash_key = f"{graph_name}_hash"
                if hash_key in self._preemptive_cache:
                    del self._preemptive_cache[hash_key]
        
        if evicted_count > 0:
            logger.debug(f"Evicted {evicted_count} items from graph cache due to size limits")
    
    def _get_content_hash(self, data: bytes) -> str:
        """Generate content hash for cache validation."""
        import hashlib
        return hashlib.md5(data).hexdigest()
    
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize graph name for safe file system usage."""
        import re
        # Remove or replace problematic characters
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', name)
        safe_name = re.sub(r'[^\w\-_.]', '_', safe_name)
        # Limit length
        return safe_name[:100] if len(safe_name) > 100 else safe_name
    
    def _validate_graph_exists(self, graph_name: str) -> bool:
        """Validate that graph still exists in Stata."""
        try:
            # First try to get graph list to verify existence
            graph_list = self.list_graphs(force_refresh=True)
            if graph_name not in graph_list:
                return False
            
            # Additional validation by attempting to display the graph
            resolved = self._resolve_graph_name_for_stata(graph_name)
            cmd = f'quietly graph display {resolved}'
            resp = self._exec_no_capture_silent(cmd, echo=False)
            return resp.success
        except Exception:
            return False
    
    def _is_cache_valid(self, graph_name: str, cache_path: str) -> bool:
        """Check if cached content is still valid using internal signatures."""
        try:
            if not os.path.exists(cache_path) or os.path.getsize(cache_path) == 0:
                return False
                
            current_sig = self._get_graph_signature(graph_name)
            cached_sig = self._preemptive_cache.get(f"{graph_name}_sig")
            
            # If we have a signature match, it's valid for the current command session
            if cached_sig and cached_sig == current_sig:
                return True
                
            # Otherwise it's invalid (needs refresh for new command)
            return False
        except Exception:
            return False

    def export_graphs_all(self) -> GraphExportResponse:
        """Exports all graphs to file paths."""
        exports: List[GraphExport] = []
        graph_names = self.list_graphs(force_refresh=True)
        
        if not graph_names:
            return GraphExportResponse(graphs=exports)
        
        import tempfile
        import os
        import threading
        import uuid
        import time
        import logging
        
        # Initialize cache in thread-safe manner
        self._initialize_cache()

        def _cache_keyed_svg_path(name: str) -> str:
            import hashlib
            safe_name = self._sanitize_filename(name)
            suffix = hashlib.md5((name or "").encode("utf-8")).hexdigest()[:8]
            return os.path.join(self._preemptive_cache_dir, f"{safe_name}_{suffix}.svg")

        def _export_svg_bytes(name: str) -> bytes:
            resolved = self._resolve_graph_name_for_stata(name)

            temp_dir = get_writable_temp_dir()
            safe_temp_name = self._sanitize_filename(name)
            unique_filename = f"{safe_temp_name}_{uuid.uuid4().hex[:8]}_{os.getpid()}_{int(time.time())}.svg"
            svg_path = os.path.join(temp_dir, unique_filename)
            svg_path_for_stata = svg_path.replace("\\", "/")

            try:
                # We use name identifier WITHOUT quotes for Stata 19 compatibility
                # but we use quotes for the file path.
                export_cmd = f'quietly graph export "{svg_path_for_stata}", name({resolved}) replace as(svg)'
                export_resp = self._exec_no_capture_silent(export_cmd, echo=False)

                if not export_resp.success:
                    # Fallback for complex names if the unquoted version failed
                    # but only if it's not a generic r(1)
                    if export_resp.rc != 1:
                        export_cmd_quoted = f'quietly graph export "{svg_path_for_stata}", name("{resolved}") replace as(svg)'
                        export_resp = self._exec_no_capture_silent(export_cmd_quoted, echo=False)
                    
                    if not export_resp.success:
                        # Final resort: display and then export active
                        display_cmd = f'quietly graph display {resolved}'
                        display_resp = self._exec_no_capture_silent(display_cmd, echo=False)
                        if display_resp.success:
                            export_cmd2 = f'quietly graph export "{svg_path_for_stata}", replace as(svg)'
                            export_resp = self._exec_no_capture_silent(export_cmd2, echo=False)
                        else:
                            export_resp = display_resp

                if export_resp.success and os.path.exists(svg_path) and os.path.getsize(svg_path) > 0:
                    with open(svg_path, "rb") as f:
                        return f.read()
                
                # If we reached here, something failed.
                error_info = getattr(export_resp, 'error', None)
                error_msg = error_info.message if error_info else f"Stata error r({export_resp.rc})"
                raise RuntimeError(f"Failed to export graph {name}: {error_msg}")
            finally:
                if os.path.exists(svg_path):
                    try:
                        os.remove(svg_path)
                    except OSError as e:
                        logger.warning(f"Failed to cleanup temp file {svg_path}: {e}")
        
        cached_graphs = {}
        uncached_graphs = []
        cache_errors = []
        
        with self._cache_lock:
            for name in graph_names:
                if name in self._preemptive_cache:
                    cached_path = self._preemptive_cache[name]
                    if os.path.exists(cached_path) and os.path.getsize(cached_path) > 0:
                        # Additional validation: check if graph content has changed
                        if self._is_cache_valid(name, cached_path):
                            cached_graphs[name] = cached_path
                        else:
                            uncached_graphs.append(name)
                            # Remove stale cache entry
                            del self._preemptive_cache[name]
                    else:
                        uncached_graphs.append(name)
                        # Remove invalid cache entry
                        if name in self._preemptive_cache:
                            del self._preemptive_cache[name]
                else:
                    uncached_graphs.append(name)
        
        for name, cached_path in cached_graphs.items():
            try:
                exports.append(GraphExport(name=name, file_path=cached_path))
            except Exception as e:
                cache_errors.append(f"Failed to read cached graph {name}: {e}")
                # Fall back to uncached processing
                uncached_graphs.append(name)
        
        if uncached_graphs:
            successful_graphs = []
            failed_graphs = []
            memory_results = {}
            
            for name in uncached_graphs:
                try:
                    svg_data = _export_svg_bytes(name)
                    memory_results[name] = svg_data
                    successful_graphs.append(name)
                except Exception as e:
                    failed_graphs.append(name)
                    cache_errors.append(f"Failed to cache graph {name}: {e}")
            
            for name in successful_graphs:
                result = memory_results[name]
                
                cache_path = _cache_keyed_svg_path(name)
                
                try:
                    with open(cache_path, 'wb') as f:
                        f.write(result)
                    
                    # Update cache with size tracking and eviction
                    import time
                    item_size = len(result)
                    self._evict_cache_if_needed(item_size)
                    
                    with self._cache_lock:
                        self._preemptive_cache[name] = cache_path
                        # Store content hash for validation
                        self._preemptive_cache[f"{name}_hash"] = self._get_content_hash(result)
                        # Update tracking
                        self._cache_access_times[name] = time.time()
                        self._cache_sizes[name] = item_size
                        self._total_cache_size += item_size
                    
                    exports.append(GraphExport(name=name, file_path=cache_path))
                except Exception as e:
                    cache_errors.append(f"Failed to cache graph {name}: {e}")
                    # Still return the result even if caching fails
                    # Create temp file for immediate use
                    safe_name = self._sanitize_filename(name)
                    temp_path = os.path.join(get_writable_temp_dir(), f"{safe_name}_{uuid.uuid4().hex[:8]}.svg")
                    with open(temp_path, 'wb') as f:
                        f.write(result)
                    register_temp_file(temp_path)
                    exports.append(GraphExport(name=name, file_path=temp_path))
        
        # Log errors if any occurred
        if cache_errors:
            logger = logging.getLogger(__name__)
            for error in cache_errors:
                logger.warning(error)
        
        return GraphExportResponse(graphs=exports)

    def cache_graph_on_creation(self, graph_name: str) -> bool:
        """Revolutionary method to cache a graph immediately after creation.
        
        Call this method right after creating a graph to pre-emptively cache it.
        This eliminates all export wait time for future access.
        
        Args:
            graph_name: Name of the graph to cache
            
        Returns:
            True if caching succeeded, False otherwise
        """
        import os
        import logging
        logger = logging.getLogger("mcp_stata.stata_client")
        
        # Initialize cache in thread-safe manner
        self._initialize_cache()
        
        # Invalidate list_graphs cache since a new graph was created
        self.invalidate_list_graphs_cache()
        
        # Check if already cached and valid
        with self._cache_lock:
            if graph_name in self._preemptive_cache:
                cache_path = self._preemptive_cache[graph_name]
                if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
                    if self._is_cache_valid(graph_name, cache_path):
                        # Update access time for LRU
                        import time
                        self._cache_access_times[graph_name] = time.time()
                        return True
                    else:
                        # Remove stale cache entry
                        del self._preemptive_cache[graph_name]
                        if graph_name in self._cache_access_times:
                            del self._cache_access_times[graph_name]
                        if graph_name in self._cache_sizes:
                            self._total_cache_size -= self._cache_sizes[graph_name]
                            del self._cache_sizes[graph_name]
                        # Remove hash entry if exists
                        hash_key = f"{graph_name}_hash"
                        if hash_key in self._preemptive_cache:
                            del self._preemptive_cache[hash_key]
        
        try:
            # Include signature in filename to force client-side refresh
            import hashlib
            sig = self._get_graph_signature(graph_name)
            safe_name = self._sanitize_filename(sig)
            suffix = hashlib.md5((sig or "").encode("utf-8")).hexdigest()[:8]
            cache_path = os.path.join(self._preemptive_cache_dir, f"{safe_name}_{suffix}.svg")
            cache_path_for_stata = cache_path.replace("\\", "/")

            resolved_graph_name = self._resolve_graph_name_for_stata(graph_name)
            safe_name = resolved_graph_name.strip()
            
            # The most reliable and efficient strategy for capturing distinct graphs in 
            # PyStata background tasks:
            # 1. Ensure the specific graph is active in the Stata engine via 'graph display'.
            # 2. Export with the explicit name() option to ensure isolation.
            # Graph names in Stata should NOT be quoted.
            
            maintenance = [
                f"quietly graph display {safe_name}",
                f"quietly graph export \"{cache_path_for_stata}\", name({safe_name}) replace as(svg)"
            ]
            
            resp = self._exec_no_capture_silent("\n".join(maintenance), echo=False)
            
            if resp.success and os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
                # Read the data to compute hash
                with open(cache_path, 'rb') as f:
                    data = f.read()
                
                # Update cache with size tracking and eviction
                import time
                item_size = len(data)
                self._evict_cache_if_needed(item_size)
                
                with self._cache_lock:
                    # Clear any old versions of this graph from the path cache
                    # (Optional but keeps it clean)
                    old_path = self._preemptive_cache.get(graph_name)
                    if old_path and old_path != cache_path:
                         try:
                             os.remove(old_path)
                         except Exception:
                             pass

                    self._preemptive_cache[graph_name] = cache_path
                    # Store content hash for validation
                    self._preemptive_cache[f"{graph_name}_hash"] = self._get_content_hash(data)
                    # Store signature for fast validation
                    self._preemptive_cache[f"{graph_name}_sig"] = self._get_graph_signature(graph_name)
                    # Update tracking
                    self._cache_access_times[graph_name] = time.time()
                    self._cache_sizes[graph_name] = item_size
                    self._total_cache_size += item_size
                
                return True
            else:
                error_msg = getattr(resp, 'error', 'Unknown error')
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to cache graph {graph_name}: {error_msg}")
                
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Exception caching graph {graph_name}: {e}")
        
        return False

    def run_do_file(self, path: str, echo: bool = True, trace: bool = False, max_output_lines: Optional[int] = None, cwd: Optional[str] = None) -> CommandResponse:
        effective_path, command, error_response = self._resolve_do_file_path(path, cwd)
        if error_response is not None:
            return error_response

        if not self._initialized:
            self.init()

        start_time = time.time()
        exc: Optional[Exception] = None
        smcl_content = ""
        smcl_path = None

        _log_file, log_path, tail, tee = self._create_streaming_log(trace=trace)
        smcl_path = self._create_smcl_log_path()
        smcl_log_name = self._make_smcl_log_name()

        rc = -1
        try:
            rc, exc = self._run_streaming_blocking(
                command=command,
                tee=tee,
                cwd=cwd,
                trace=trace,
                echo=echo,
                smcl_path=smcl_path,
                smcl_log_name=smcl_log_name,
                hold_attr="_hold_name_do_sync",
                require_smcl_log=True,
            )
        except Exception as e:
            exc = e
            rc = 1
        finally:
            tee.close()

        # Read SMCL content as the authoritative source
        smcl_content = self._read_smcl_file(smcl_path)
        smcl_content = self._clean_internal_smcl(smcl_content, strip_output=False)

        combined = self._build_combined_log(tail, log_path, rc, trace, exc)

        # Use SMCL content as primary source for RC detection if not already captured
        if rc == -1 and not exc:
            parsed_rc = self._parse_rc_from_smcl(smcl_content)
            if parsed_rc is not None:
                rc = parsed_rc
            else:
                # Fallback to text parsing
                parsed_rc = self._parse_rc_from_text(combined)
                rc = parsed_rc if parsed_rc is not None else 0
        elif exc and rc == 1:
            # Try to parse more specific RC from exception message
            parsed_rc = self._parse_rc_from_text(str(exc))
            if parsed_rc is not None:
                rc = parsed_rc

        # If RC looks wrong but SMCL shows no error markers, treat as success.
        if rc != 0 and smcl_content:
            has_err_tag = "{err}" in smcl_content
            rc_match = re.search(r"(?<!\w)r\((\d+)\)", smcl_content)
            if rc_match:
                try:
                    rc = int(rc_match.group(1))
                except Exception:
                    pass
            else:
                text_rc = None
                try:
                    text_rc = self._parse_rc_from_text(self._smcl_to_text(smcl_content))
                except Exception:
                    text_rc = None
                if not has_err_tag and text_rc is None:
                    rc = 0

        success = (rc == 0 and exc is None)
        error = None

        if not success:
            # Use SMCL as authoritative source for error extraction
            if smcl_content:
                msg, context = self._extract_error_from_smcl(smcl_content, rc)
            else:
                # Fallback to combined log
                msg, context = self._extract_error_and_context(combined, rc)

            error = ErrorEnvelope(
                message=msg,
                rc=rc,
                snippet=context,
                command=command,
                log_path=log_path,
                smcl_output=smcl_content,
            )

        duration = time.time() - start_time
        logger.info(
            "stata.run(do) rc=%s success=%s trace=%s duration_ms=%.2f path=%s",
            rc,
            success,
            trace,
            duration * 1000,
            effective_path,
        )

        try:
            with open(log_path, "w", encoding="utf-8", errors="replace") as handle:
                handle.write(smcl_content)
        except Exception:
            pass

        return CommandResponse(
            command=command,
            rc=rc,
            stdout="",
            stderr=None,
            log_path=log_path,
            success=success,
            error=error,
            smcl_output=smcl_content,
        )

    def load_data(self, source: str, clear: bool = True, max_output_lines: Optional[int] = None) -> CommandResponse:
        src = source.strip()
        clear_suffix = ", clear" if clear else ""

        if src.startswith("sysuse "):
            cmd = f"{src}{clear_suffix}"
        elif src.startswith("webuse "):
            cmd = f"{src}{clear_suffix}"
        elif src.startswith("use "):
            cmd = f"{src}{clear_suffix}"
        elif "://" in src or src.endswith(".dta") or os.path.sep in src:
            cmd = f'use "{src}"{clear_suffix}'
        else:
            cmd = f"sysuse {src}{clear_suffix}"

        result = self._exec_with_capture(cmd, echo=True, trace=False)
        return self._truncate_command_output(result, max_output_lines)

    def codebook(self, varname: str, trace: bool = False, max_output_lines: Optional[int] = None) -> CommandResponse:
        result = self._exec_with_capture(f"codebook {varname}", trace=trace)
        return self._truncate_command_output(result, max_output_lines)