import json
import logging
import os
import re
import subprocess
import sys
import threading
import uuid
from importlib.metadata import PackageNotFoundError, version
import tempfile
import time
from contextlib import contextmanager
from io import StringIO, BytesIO
from typing import Any, Awaitable, Callable, Dict, Generator, List, Optional, Tuple, BinaryIO
import platform
import sys
from typing import Optional

import anyio
from anyio import get_cancelled_exc_class

from .discovery import find_stata_path
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

logger = logging.getLogger("mcp_stata")

_POLARS_AVAILABLE: Optional[bool] = None

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
_discovery_attempted = False
_discovery_error: Optional[Exception] = None


def _get_discovered_stata() -> Tuple[str, str]:
    """
    Get the discovered Stata path and edition, running discovery only once.
    
    Returns:
        Tuple of (stata_executable_path, edition)
    
    Raises:
        RuntimeError: If Stata discovery fails
    """
    global _discovery_result, _discovery_attempted, _discovery_error
    
    with _discovery_lock:
        # If we've already successfully discovered Stata, return cached result
        if _discovery_result is not None:
            return _discovery_result
        
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
            
            try:
                pkg_version = version("mcp-stata")
            except PackageNotFoundError:
                pkg_version = "unknown"
            logger.info("mcp-stata version: %s", pkg_version)
            
            # Run discovery
            stata_exec_path, edition = find_stata_path()
            
            # Cache the successful result
            _discovery_result = (stata_exec_path, edition)
            logger.info("Discovery found Stata at: %s (%s)", stata_exec_path, edition)
            
            return _discovery_result
            
        except FileNotFoundError as e:
            _discovery_error = e
            raise RuntimeError(f"Stata binary not found: {e}") from e
        except PermissionError as e:
            _discovery_error = e
            raise RuntimeError(
                f"Stata binary is not executable: {e}. "
                "Point STATA_PATH directly to the Stata binary (e.g., .../Contents/MacOS/stata-mp)."
            ) from e


class StataClient:
    _initialized = False
    _exec_lock: threading.Lock
    _cache_init_lock = threading.Lock()  # Class-level lock for cache initialization
    _is_executing = False  # Flag to prevent recursive Stata calls
    MAX_DATA_ROWS = 500
    MAX_GRAPH_BYTES = 50 * 1024 * 1024  # Maximum graph exports (~50MB)
    MAX_CACHE_SIZE = 100  # Maximum number of graphs to cache
    MAX_CACHE_BYTES = 500 * 1024 * 1024  # Maximum cache size in bytes (~500MB)
    LIST_GRAPHS_TTL = 0.075  # TTL for list_graphs cache (75ms)

    def __new__(cls):
        inst = super(StataClient, cls).__new__(cls)
        inst._exec_lock = threading.RLock()
        inst._is_executing = False
        return inst

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
        # Create temp file path for SMCL output
        # Create temp file path for SMCL output
        # Use a unique name but DO NOT join start with mkstemp to avoid existing file locks.
        # Stata will create the file.
        smcl_path = os.path.join(tempfile.gettempdir(), f"mcp_smcl_{uuid.uuid4().hex}.smcl")
        
        # Ensure cleanup in case of pre-existing file (unlikely with UUID)
        try:
             if os.path.exists(smcl_path):
                os.unlink(smcl_path)
        except Exception:
             pass
        
        # Unique log name to avoid collisions with user logs
        log_name = f"_mcp_smcl_{uuid.uuid4().hex[:8]}"
        
        try:
            # Open named SMCL log (quietly to avoid polluting output)
            # Add retry logic for Windows file locking flakiness
            log_opened = False
            for attempt in range(4):
                try:
                    self.stata.run(f'quietly log using "{smcl_path}", replace smcl name({log_name})', echo=False)
                    log_opened = True
                    break
                except Exception:
                    if attempt < 3:
                        time.sleep(0.1)
            
            if not log_opened:
                # Still yield, consumer might see empty file or handle error, 
                # but we can't do much if Stata refuses to log.
                pass
                
            yield log_name, smcl_path
        finally:
            # Always close our named log
            try:
                self.stata.run(f'capture log close {log_name}', echo=False)
            except Exception:
                # Fallback: try capture in case log wasn't opened
                try:
                    self.stata.run(f'capture log close {log_name}', echo=False)
                except Exception:
                    pass

    def _read_smcl_file(self, path: str) -> str:
        """Read SMCL file contents, handling encoding issues and Windows file locks."""
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except PermissionError:
            if os.name == "nt":
                # Windows Fallback: Try to use 'type' command to bypass exclusive lock
                try:
                    res = subprocess.run(f'type "{path}"', shell=True, capture_output=True)
                    if res.returncode == 0:
                        return res.stdout.decode('utf-8', errors='replace')
                except Exception as e:
                    logger.debug(f"Combined fallback read failed: {e}")
            logger.warning(f"Failed to read SMCL file {path} due to lock")
            return ""
        except Exception as e:
            logger.warning(f"Failed to read SMCL file {path}: {e}")
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
        
        lines = smcl_content.splitlines()
        
        # Search backwards for {err} tags - they indicate error lines
        error_lines = []
        error_start_idx = -1
        
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i]
            if '{err}' in line:
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
        
        # Fallback: no {err} found, return last 30 lines as context
        context_start = max(0, len(lines) - 30)
        context = "\n".join(lines[context_start:])
        
        return f"Stata error r({rc})", context

    def _parse_rc_from_smcl(self, smcl_content: str) -> Optional[int]:
        """Parse return code from SMCL content using specific structural patterns."""
        if not smcl_content:
            return None
            
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

    def init(self):
        """Initializes usage of pystata using cached discovery results."""
        if self._initialized:
            return

        # Suppress any non-UTF8 banner output from PyStata on stdout, which breaks MCP stdio transport
        from contextlib import redirect_stdout, redirect_stderr
        devnull = open(os.devnull, "w", encoding="utf-8", errors="ignore")

        try:
            import stata_setup
            
            # Get discovered Stata path (cached from first call)
            stata_exec_path, edition = _get_discovered_stata()

            candidates = []

            # Prefer the binary directory first (documented input for stata_setup)
            bin_dir = os.path.dirname(stata_exec_path)
            if bin_dir:
                candidates.append(bin_dir)

            # 2. App Bundle: .../StataMP.app (macOS only)
            curr = bin_dir
            app_bundle = None
            while len(curr) > 1:
                if curr.endswith(".app"):
                    app_bundle = curr
                    break
                parent = os.path.dirname(curr)
                if parent == curr:  # Reached root directory, prevent infinite loop on Windows
                    break
                curr = parent

            if app_bundle:
                candidates.insert(0, os.path.dirname(app_bundle))
                candidates.insert(1, app_bundle)

            # Deduplicate preserving order
            seen = set()
            deduped = []
            for c in candidates:
                if c in seen:
                    continue
                seen.add(c)
                deduped.append(c)
            candidates = deduped

            success = False
            for path in candidates:
                try:
                    with redirect_stdout(devnull), redirect_stderr(devnull):
                        stata_setup.config(path, edition)
                    success = True
                    logger.debug("stata_setup.config succeeded with path: %s", path)
                    break
                except Exception:
                    continue

            if not success:
                raise RuntimeError(
                    f"stata_setup.config failed. Tried: {candidates}. "
                    f"Derived from binary: {stata_exec_path}"
                )

            # Cache the binary path for later use (e.g., PNG export on Windows)
            self._stata_exec_path = os.path.abspath(stata_exec_path)

            with redirect_stdout(devnull), redirect_stderr(devnull):
                from pystata import stata  # type: ignore[import-not-found]
                # Warm up the engine and swallow any late splash screen output
                stata.run("display 1", echo=False)
            self.stata = stata
            self._initialized = True
            
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
        finally:
            try:
                devnull.close()
            except Exception:
                pass

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

        # Handle common patterns: name("..." ...) or name(`"..."' ...)
        pat = re.compile(r"name\(\s*(?:`\"(?P<cq>[^\"]*)\"'|\"(?P<dq>[^\"]*)\")\s*(?P<rest>[^)]*)\)")

        def repl(m: re.Match) -> str:
            original = m.group("cq") if m.group("cq") is not None else m.group("dq")
            original = original or ""
            internal = self._graph_name_aliases.get(original)
            if not internal:
                internal = self._make_valid_stata_name(original)
                self._graph_name_aliases[original] = internal
                self._graph_name_reverse[internal] = original
            rest = m.group("rest") or ""
            return f"name({internal}{rest})"

        return pat.sub(repl, code)

    def _get_rc_from_scalar(self, Scalar) -> int:
        """Safely get return code, handling None values."""
        try:
            from sfi import Macro
            rc_val = Macro.getGlobal("_rc")
            if rc_val is None:
                return -1
            return int(float(rc_val))
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

    def _read_log_backwards_until_error(self, path: str, max_bytes: int = 5_000_000) -> str:
        """
        Read log file backwards in chunks, stopping when we find {err} tags or reach the start.

        This is more efficient and robust than reading huge fixed tails, as we only read
        what we need to find the error.

        Args:
            path: Path to the log file
            max_bytes: Maximum total bytes to read (safety limit, default 5MB)

        Returns:
            The relevant portion of the log containing the error and context
        """
        try:
            chunk_size = 50_000  # Read 50KB chunks at a time
            total_read = 0
            chunks = []

            with open(path, 'rb') as f:
                # Get file size
                f.seek(0, os.SEEK_END)
                file_size = f.tell()

                if file_size == 0:
                    return ""

                # Start from the end
                position = file_size

                while position > 0 and total_read < max_bytes:
                    # Calculate how much to read in this chunk
                    read_size = min(chunk_size, position, max_bytes - total_read)
                    position -= read_size

                    # Seek and read
                    f.seek(position)
                    chunk = f.read(read_size)
                    chunks.insert(0, chunk)
                    total_read += read_size

                    # Decode and check for error tags
                    try:
                        accumulated = b''.join(chunks).decode('utf-8', errors='replace')

                        # Check if we've found an error tag
                        if '{err}' in accumulated:
                            # Found it! Read one more chunk for context before the error
                            if position > 0 and total_read < max_bytes:
                                extra_read = min(chunk_size, position, max_bytes - total_read)
                                position -= extra_read
                                f.seek(position)
                                extra_chunk = f.read(extra_read)
                                chunks.insert(0, extra_chunk)

                            return b''.join(chunks).decode('utf-8', errors='replace')

                    except UnicodeDecodeError:
                        # Continue reading if we hit a decode error (might be mid-character)
                        continue

                # Read everything we've accumulated
                return b''.join(chunks).decode('utf-8', errors='replace')

        except Exception as e:
            logger.warning(f"Error reading log backwards: {e}")
            # Fallback to regular tail read
            return self._read_log_tail(path, 200_000)

    def _read_log_tail_smart(self, path: str, rc: int, trace: bool = False) -> str:
        """
        Smart log tail reader that adapts based on whether an error occurred.

        - If rc == 0: Read normal tail (20KB without trace, 200KB with trace)
        - If rc != 0: Search backwards dynamically to find the error

        Args:
            path: Path to the log file
            rc: Return code from Stata
            trace: Whether trace mode was enabled

        Returns:
            Relevant log content
        """
        if rc != 0:
            # Error occurred - search backwards for {err} tags
            return self._read_log_backwards_until_error(path)
        else:
            # Success - just read normal tail
            tail_size = 200_000 if trace else 20_000
            return self._read_log_tail(path, tail_size)

    def _read_log_tail(self, path: str, max_chars: int) -> str:
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()

                if size <= 0:
                    return ""
                read_size = min(size, max_chars)
                f.seek(-read_size, os.SEEK_END)
                data = f.read(read_size)
            return data.decode("utf-8", errors="replace")
        except Exception:
            return ""

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
            try:
                os.unlink(smcl_path)
            except Exception:
                pass
            
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
        # First, keep inline directive content if present (e.g., {bf:word} -> word)
        cleaned = re.sub(r"\{[^}:]+:([^}]*)\}", r"\1", smcl)
        # Remove remaining SMCL brace commands like {smcl}, {vieweralsosee ...}, {txt}, {p}
        cleaned = re.sub(r"\{[^}]*\}", "", cleaned)
        # Normalize whitespace
        cleaned = cleaned.replace("\r", "")
        lines = [line.rstrip() for line in cleaned.splitlines()]
        return "\n".join(lines).strip()

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
        if not self._initialized:
            self.init()

        # Rewrite graph names with special characters to internal aliases
        code = self._maybe_rewrite_graph_name_in_command(code)

        output_buffer = StringIO()
        error_buffer = StringIO()
        rc = 0
        sys_error = None
        error_envelope = None
        smcl_content = ""
        smcl_path = None

        with self._exec_lock:
            try:
                from sfi import Scalar, SFIToolkit
                with self._temp_cwd(cwd):
                    # Create SMCL log for authoritative output capture
                    # Use shorter unique path to avoid Windows path issues
                    smcl_path = os.path.join(tempfile.gettempdir(), f"mcp_{uuid.uuid4().hex[:16]}.smcl")
                    
                    # Ensure cleanup in case of pre-existing file
                    try:
                        if os.path.exists(smcl_path):
                            os.unlink(smcl_path)
                    except Exception:
                        pass
                    
                    log_name = f"_mcp_smcl_{uuid.uuid4().hex[:8]}"
                    
                    # Open SMCL log BEFORE output redirection
                    # Add retry logic for Windows file locking flakiness
                    log_opened = False
                    for attempt in range(4):
                        try:
                            self.stata.run(f'log using "{smcl_path}", replace smcl name({log_name})', echo=False)
                            log_opened = True
                            break
                        except Exception:
                            if attempt < 3:
                                time.sleep(0.1)
                    
                    if not log_opened:
                        # Fallback: try one more time without replace if it was strangely missing, 
                        # or just proceed (logging will fail but execution might work)
                        pass
                    
                    try:
                        with self._redirect_io(output_buffer, error_buffer):
                            try:
                                if trace:
                                    self.stata.run("set trace on")

                                # Run the user code
                                self.stata.run(code, echo=echo)
                                
                                # Hold results IMMEDIATELY to prevent clobbering by cleanup
                                self._hold_name = f"mcp_hold_{uuid.uuid4().hex[:8]}"
                                self.stata.run(f"capture _return hold {self._hold_name}", echo=False)
                                
                            finally:
                                if trace:
                                    try:
                                        self.stata.run("set trace off")
                                    except Exception:
                                        pass
                    finally:
                        # Close SMCL log AFTER output redirection
                        try:
                            self.stata.run(f'capture log close {log_name}', echo=False)
                        except Exception:
                            pass

                        # Restore and capture results while still inside the lock
                        if hasattr(self, '_hold_name'):
                            try:
                                self.stata.run(f"capture _return restore {self._hold_name}", echo=False)
                                self._last_results = self.get_stored_results(force_fresh=True)
                                delattr(self, '_hold_name')
                            except Exception:
                                pass

            except Exception as e:
                sys_error = str(e)
                # Try to parse RC from exception message
                parsed_rc = self._parse_rc_from_text(sys_error)
                rc = parsed_rc if parsed_rc is not None else 1

        # Read SMCL content as the authoritative source
        if smcl_path:
            smcl_content = self._read_smcl_file(smcl_path)
            # Clean up SMCL file
            try:
                os.unlink(smcl_path)
            except Exception:
                pass

        stdout_content = output_buffer.getvalue()
        stderr_content = error_buffer.getvalue()

        # If RC wasn't captured or is generic, try to parse from SMCL
        if rc in (0, 1, -1) and smcl_content:
            parsed_rc = self._parse_rc_from_smcl(smcl_content)
            if parsed_rc is not None and parsed_rc != 0:
                rc = parsed_rc
            elif rc == -1:
                rc = 0

        # If stdout is empty but SMCL has content AND command succeeded, use SMCL as stdout
        # This handles cases where Stata writes to log but not to redirected stdout
        # For errors, we keep stdout empty and error info goes to ErrorEnvelope
        if rc == 0 and not stdout_content and smcl_content:
            # Convert SMCL to plain text for stdout
            stdout_content = self._smcl_to_text(smcl_content)

        if rc != 0:
            if sys_error:
                msg = sys_error
                context = sys_error
            else:
                # Extract error from SMCL (authoritative source)
                msg, context = self._extract_error_from_smcl(smcl_content, rc)

            error_envelope = ErrorEnvelope(
                message=msg, 
                rc=rc, 
                context=context, 
                snippet=smcl_content[-800:] if smcl_content else (stdout_content + stderr_content)[-800:],
                smcl_output=smcl_content  # Include raw SMCL for debugging
            )
            stderr_content = context

        resp = CommandResponse(
            command=code,
            rc=rc,
            stdout=stdout_content,
            stderr=stderr_content,
            success=(rc == 0),
            error=error_envelope,
            log_path=smcl_path if smcl_path else None
        )

        # Capture results immediately after execution, INSIDE the lock
        try:
            self._last_results = self.get_stored_results(force_fresh=True)
        except Exception:
            self._last_results = None

        return resp
        
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
) -> CommandResponse:
        if not self._initialized:
            self.init()

        code = self._maybe_rewrite_graph_name_in_command(code)
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
        graph_cache = None
        if auto_cache_graphs:
            graph_cache = StreamingGraphCache(self, auto_cache=True)
            
            graph_cache_callback = self._create_graph_cache_callback(on_graph_cached, notify_log)
            
            graph_cache.add_cache_callback(graph_cache_callback)

        log_file = tempfile.NamedTemporaryFile(
            prefix="mcp_stata_",
            suffix=".log",
            delete=False,
            mode="w",
            encoding="utf-8",
            errors="replace",
            buffering=1,
        )
        log_path = log_file.name
        tail = TailBuffer(max_chars=200000 if trace else 20000)
        tee = FileTeeIO(log_file, tail)

        # Create SMCL log path for authoritative output capture
        # Create SMCL log path for authoritative output capture
        # Use generated path to avoid locks
        smcl_path = os.path.join(tempfile.gettempdir(), f"mcp_smcl_{uuid.uuid4().hex}.smcl")
        
        # Ensure cleanup in case of pre-existing file
        try:
             if os.path.exists(smcl_path):
                os.unlink(smcl_path)
        except Exception:
             pass
        smcl_log_name = f"_mcp_smcl_{uuid.uuid4().hex[:8]}"

        # Inform the MCP client immediately where to read/tail the output.
        await notify_log(json.dumps({"event": "log_path", "path": smcl_path}))

        rc = -1
        path_for_stata = code.replace("\\", "/")
        command = f'{path_for_stata}'

        # Capture initial graph state BEFORE execution starts
        if graph_cache:
            try:
                graph_cache._initial_graphs = set(self.list_graphs())
                logger.debug(f"Initial graph state captured: {graph_cache._initial_graphs}")
            except Exception as e:
                logger.debug(f"Failed to capture initial graph state: {e}")
                graph_cache._initial_graphs = set()

        def _run_blocking() -> None:
            nonlocal rc, exc
            with self._exec_lock:
                # Set execution flag to prevent recursive Stata calls
                self._is_executing = True
                try:
                    from sfi import Scalar, SFIToolkit # Import SFI tools
                    with self._temp_cwd(cwd):
                        # Open SMCL log BEFORE output redirection
                        # Add retry logic for Windows file locking flakiness
                        log_opened = False
                        for attempt in range(4):
                            try:
                                self.stata.run(f'log using "{smcl_path}", replace smcl name({smcl_log_name})', echo=False)
                                log_opened = True
                                break
                            except Exception:
                                if attempt < 3:
                                    time.sleep(0.1)
                        
                        if not log_opened:
                            # Fallback but allow execution to attempt to proceed
                            pass
                        
                        try:
                            with self._redirect_io_streaming(tee, tee):
                                try:
                                    if trace:
                                        self.stata.run("set trace on")
                                    ret = self.stata.run(command, echo=echo)
                                    
                                    # Hold results IMMEDIATELY to prevent clobbering by cleanup
                                    self._hold_name_stream = f"mcp_hold_{uuid.uuid4().hex[:8]}"
                                    self.stata.run(f"capture _return hold {self._hold_name_stream}", echo=False)
                                    # Some PyStata builds return output as a string rather than printing.
                                    if isinstance(ret, str) and ret:
                                        try:
                                            tee.write(ret)
                                        except Exception:
                                            pass
                                    try:
                                        rc = self._get_rc_from_scalar(Scalar)
                                    except Exception:
                                        pass

                                except Exception as e:
                                    exc = e
                                    if rc in (-1, 0):
                                        rc = 1
                                finally:
                                    if trace:
                                        try:
                                            self.stata.run("set trace off")
                                        except Exception:
                                            pass
                        finally:
                            # Close SMCL log AFTER output redirection
                            try:
                                self.stata.run(f'capture log close {smcl_log_name}', echo=False)
                            except Exception:
                                pass

                            # Restore and capture results while still inside the lock
                            if hasattr(self, '_hold_name_stream'):
                                try:
                                    self.stata.run(f"capture _return restore {self._hold_name_stream}", echo=False)
                                    self._last_results = self.get_stored_results(force_fresh=True)
                                    delattr(self, '_hold_name_stream')
                                except Exception:
                                    pass
                finally:
                    # Clear execution flag
                    self._is_executing = False

        done = anyio.Event()

        async def _monitor_and_stream_log() -> None:
            """Monitor log file and stream chunks for both display and progress tracking."""
            last_pos = 0
            # Wait for Stata to create the SMCL file (we removed the placeholder to avoid locks)
            while not done.is_set() and not os.path.exists(smcl_path):
                await anyio.sleep(0.05)
            
            try:
                # Helper to read file content robustly (handling Windows shared read locks)
                def _read_content():
                    try:
                        with open(smcl_path, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(last_pos)
                            return f.read()
                    except PermissionError:
                        if os.name == "nt":
                            # Windows Fallback: Use 'type' command to read locked file
                            try:
                                # Start a shell process to 'type' the file. This bypasses locking sometimes.
                                # Note: Reading full file and seeking in-memory is inefficient for massive logs 
                                # but acceptable for Stata logs to unblock Windows streaming.
                                res = subprocess.run(f'type "{smcl_path}"', shell=True, capture_output=True)
                                full_content = res.stdout.decode("utf-8", errors="replace")
                                if len(full_content) > last_pos:
                                    return full_content[last_pos:]
                                return ""
                            except Exception:
                                return ""
                        raise
                    except FileNotFoundError:
                        return ""

                while not done.is_set():
                    chunk = await anyio.to_thread.run_sync(_read_content)
                    if chunk:
                        last_pos += len(chunk)
                        # Stream the actual log content for display
                        await notify_log(chunk)
                        # Also track progress if needed
                        if total_lines > 0 and notify_progress:
                             await on_chunk_for_progress(chunk)
                    await anyio.sleep(0.05)

                # Final read
                chunk = await anyio.to_thread.run_sync(_read_content)
                if chunk:
                    last_pos += len(chunk)
                    await notify_log(chunk)
                    if total_lines > 0 and notify_progress:
                        await on_chunk_for_progress(chunk)

            except Exception as e:
                logger.warning(f"Log streaming failed: {e}")
                return

        async with anyio.create_task_group() as tg:
            tg.start_soon(_monitor_and_stream_log)

            if notify_progress is not None:
                if total_lines > 0:
                    await notify_progress(0, float(total_lines), f"Executing command: 0/{total_lines}")
                else:
                    await notify_progress(0, None, "Running command")

            try:
                await anyio.to_thread.run_sync(_run_blocking, abandon_on_cancel=True)
            except get_cancelled_exc_class():
                self._request_break_in()
                await self._wait_for_stata_stop()
                raise
            finally:
                done.set()
                tee.close()

        # Read SMCL content as the authoritative source
        smcl_content = self._read_smcl_file(smcl_path)

        # Robust post-execution graph detection and caching
        if graph_cache and graph_cache.auto_cache:
            try:
                cached_graphs = []
                initial_graphs = getattr(graph_cache, '_initial_graphs', set())
                current_graphs = set(self.list_graphs())
                new_graphs = current_graphs - initial_graphs - graph_cache._cached_graphs

                if new_graphs:
                    logger.info(f"Detected {len(new_graphs)} new graph(s): {sorted(new_graphs)}")

                for graph_name in new_graphs:
                    try:
                        cache_result = await anyio.to_thread.run_sync(
                            self.cache_graph_on_creation,
                            graph_name
                        )
                        if cache_result:
                            cached_graphs.append(graph_name)
                            graph_cache._cached_graphs.add(graph_name)
                        
                        for callback in graph_cache._cache_callbacks:
                            try:
                                await anyio.to_thread.run_sync(callback, graph_name, cache_result)
                            except Exception: pass
                    except Exception as e:
                        logger.error(f"Error caching graph {graph_name}: {e}")

                # Notify progress if graphs were cached
                if cached_graphs and notify_progress:
                    await notify_progress(
                        float(total_lines) if total_lines > 0 else 1,
                        float(total_lines) if total_lines > 0 else 1,
                        f"Command completed. Cached {len(cached_graphs)} graph(s): {', '.join(cached_graphs)}"
                    )
            except Exception as e:
                logger.error(f"Post-execution graph detection failed: {e}")

        tail_text = tail.get_value()
        # Use smart log tail to find error if it's far up
        log_tail = self._read_log_tail_smart(smcl_path, rc, trace)
        if log_tail and len(log_tail) > len(tail_text):
            tail_text = log_tail
        combined = (tail_text or "") + (f"\n{exc}" if exc else "")
        
        # Use SMCL content as primary source for RC detection
        if not exc or rc in (1, -1):
            parsed_rc = self._parse_rc_from_smcl(smcl_content)
            if parsed_rc is not None and parsed_rc != 0:
                rc = parsed_rc
            elif rc in (-1, 0, 1): # Also check text if rc is generic 1 or unset
                parsed_rc_text = self._parse_rc_from_text(combined)
                if parsed_rc_text is not None:
                    rc = parsed_rc_text
                elif rc == -1:
                    rc = 0 # Default to success if no error trace found

        success = (rc == 0 and exc is None)
        stderr_final = None
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
                context=context,
                rc=rc,
                command=command,
                log_path=log_path,
                snippet=smcl_content[-800:] if smcl_content else combined[-800:],
                smcl_output=smcl_content,
            )
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
            stdout="",
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
) -> CommandResponse:
        if cwd is not None and not os.path.isdir(cwd):
            return CommandResponse(
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
        if cwd is not None and not os.path.isabs(path):
            effective_path = os.path.abspath(os.path.join(cwd, path))

        if not os.path.exists(effective_path):
            return CommandResponse(
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

        total_lines = self._count_do_file_lines(effective_path)
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

        start_time = time.time()
        exc: Optional[Exception] = None
        smcl_content = ""
        smcl_path = None

        # Setup streaming graph cache if enabled
        graph_cache = None
        if auto_cache_graphs:
            graph_cache = StreamingGraphCache(self, auto_cache=True)
            
            graph_cache_callback = self._create_graph_cache_callback(on_graph_cached, notify_log)
            
            graph_cache.add_cache_callback(graph_cache_callback)

        log_file = tempfile.NamedTemporaryFile(
            prefix="mcp_stata_",
            suffix=".log",
            delete=False,
            mode="w",
            encoding="utf-8",
            errors="replace",
            buffering=1,
        )
        log_path = log_file.name
        tail = TailBuffer(max_chars=200000 if trace else 20000)
        tee = FileTeeIO(log_file, tail)

        # Create SMCL log path for authoritative output capture (placeholder removed to avoid locks)
        # Create SMCL log path for authoritative output capture (placeholder removed to avoid locks)
        # Use generated path to avoid locks
        smcl_path = os.path.join(tempfile.gettempdir(), f"mcp_smcl_{uuid.uuid4().hex}.smcl")
        
        # Ensure cleanup in case of pre-existing file
        try:
             if os.path.exists(smcl_path):
                os.unlink(smcl_path)
        except Exception:
             pass
        smcl_log_name = f"_mcp_smcl_{uuid.uuid4().hex[:8]}"

        # Inform the MCP client immediately where to read/tail the output.
        await notify_log(json.dumps({"event": "log_path", "path": smcl_path}))

        rc = -1
        path_for_stata = effective_path.replace("\\", "/")
        command = f'do "{path_for_stata}"'

        # Capture initial graph state BEFORE execution starts
        if graph_cache:
            try:
                graph_cache._initial_graphs = set(self.list_graphs())
                logger.debug(f"Initial graph state captured: {graph_cache._initial_graphs}")
            except Exception as e:
                logger.debug(f"Failed to capture initial graph state: {e}")
                graph_cache._initial_graphs = set()

        def _run_blocking() -> None:
            nonlocal rc, exc
            with self._exec_lock:
                # Set execution flag to prevent recursive Stata calls
                self._is_executing = True
                try:
                    from sfi import Scalar, SFIToolkit # Import SFI tools
                    with self._temp_cwd(cwd):
                        # Open SMCL log BEFORE output redirection
                        # Add retry logic for Windows file locking flakiness
                        log_opened = False
                        for attempt in range(4):
                            try:
                                self.stata.run(f'log using "{smcl_path}", replace smcl name({smcl_log_name})', echo=False)
                                log_opened = True
                                break
                            except Exception:
                                if attempt < 3:
                                    time.sleep(0.1)
                        
                        if not log_opened:
                            # Fallback but allow execution to attempt to proceed
                            pass
                        
                        try:
                            with self._redirect_io_streaming(tee, tee):
                                print("DEBUG: Python print inside redirect checks capture")
                                try:
                                    if trace:
                                        self.stata.run("set trace on")
                                    ret = self.stata.run(command, echo=echo)
                                    
                                    # Hold results IMMEDIATELY to prevent clobbering by cleanup
                                    self._hold_name_do = f"mcp_hold_{uuid.uuid4().hex[:8]}"
                                    self.stata.run(f"capture _return hold {self._hold_name_do}", echo=False)
                                    # Some PyStata builds return output as a string rather than printing.
                                    if isinstance(ret, str) and ret:
                                        try:
                                            tee.write(ret)
                                        except Exception:
                                            pass
                                    try:
                                        rc = self._get_rc_from_scalar(Scalar)
                                    except Exception:
                                        pass

                                except Exception as e:
                                    exc = e
                                    if rc in (-1, 0):
                                        rc = 1
                                finally:
                                    if trace:
                                        try:
                                            self.stata.run("set trace off")
                                        except Exception:
                                            pass
                        finally:
                            # Close SMCL log AFTER output redirection
                            try:
                                self.stata.run(f'capture log close {smcl_log_name}', echo=False)
                            except Exception:
                                pass

                            # Restore and capture results while still inside the lock
                            if hasattr(self, '_hold_name_do'):
                                try:
                                    self.stata.run(f"capture _return restore {self._hold_name_do}", echo=False)
                                    self._last_results = self.get_stored_results(force_fresh=True)
                                    delattr(self, '_hold_name_do')
                                except Exception:
                                    pass
                finally:
                    # Clear execution flag
                    self._is_executing = False

        done = anyio.Event()

        async def _monitor_and_stream_log() -> None:
            """Monitor log file and stream chunks for both display and progress tracking."""
            last_pos = 0
            # Wait for Stata to create the SMCL file (placeholder removed to avoid locks)
            while not done.is_set() and not os.path.exists(smcl_path):
                await anyio.sleep(0.05)
            
            try:
                # Helper to read file content robustly (handling Windows shared read locks)
                def _read_content():
                    try:
                        with open(smcl_path, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(last_pos)
                            return f.read()
                    except PermissionError:
                        if os.name == "nt":
                            # Windows Fallback: Use 'type' command to read locked file
                            try:
                                # Start a shell process to 'type' the file. This bypasses locking sometimes.
                                # Note: Reading full file and seeking in-memory is inefficient for massive logs 
                                # but acceptable for Stata logs to unblock Windows streaming.
                                import subprocess
                                res = subprocess.run(f'type "{smcl_path}"', shell=True, capture_output=True)
                                full_content = res.stdout.decode("utf-8", errors="replace")
                                if len(full_content) > last_pos:
                                    return full_content[last_pos:]
                                return ""
                            except Exception:
                                return ""
                        raise
                    except FileNotFoundError:
                        return ""

                while not done.is_set():
                    chunk = await anyio.to_thread.run_sync(_read_content)
                    if chunk:
                        last_pos += len(chunk)
                        # Stream the actual log content for display
                        await notify_log(chunk)
                        # Also track progress if needed
                        if total_lines > 0 and notify_progress:
                                await on_chunk_for_progress(chunk)
                    await anyio.sleep(0.05)

                # Final read
                chunk = await anyio.to_thread.run_sync(_read_content)
                if chunk:
                    last_pos += len(chunk)
                    await notify_log(chunk)
                    if total_lines > 0 and notify_progress:
                        await on_chunk_for_progress(chunk)

            except Exception as e:
                logger.warning(f"Log streaming failed: {e}")
                return

        async with anyio.create_task_group() as tg:
            tg.start_soon(_monitor_and_stream_log)

            if notify_progress is not None:
                if total_lines > 0:
                    await notify_progress(0, float(total_lines), f"Executing do-file: 0/{total_lines}")
                else:
                    await notify_progress(0, None, "Running do-file")

            try:
                await anyio.to_thread.run_sync(_run_blocking, abandon_on_cancel=True)
            except get_cancelled_exc_class():
                self._request_break_in()
                await self._wait_for_stata_stop()
                raise
            finally:
                done.set()
                tee.close()

        # Read SMCL content as the authoritative source
        smcl_content = self._read_smcl_file(smcl_path)

        # Robust post-execution graph detection and caching
        if graph_cache and graph_cache.auto_cache:
            try:
                cached_graphs = []
                initial_graphs = getattr(graph_cache, '_initial_graphs', set())
                current_graphs = set(self.list_graphs())
                new_graphs = current_graphs - initial_graphs - graph_cache._cached_graphs

                if new_graphs:
                    logger.info(f"Detected {len(new_graphs)} new graph(s): {sorted(new_graphs)}")

                for graph_name in new_graphs:
                    try:
                        cache_result = await anyio.to_thread.run_sync(
                            self.cache_graph_on_creation,
                            graph_name
                        )
                        if cache_result:
                            cached_graphs.append(graph_name)
                            graph_cache._cached_graphs.add(graph_name)
                        
                        for callback in graph_cache._cache_callbacks:
                            try:
                                await anyio.to_thread.run_sync(callback, graph_name, cache_result)
                            except Exception: pass
                    except Exception as e:
                        logger.error(f"Error caching graph {graph_name}: {e}")

                # Notify progress if graphs were cached
                if cached_graphs and notify_progress:
                    await notify_progress(
                        float(total_lines) if total_lines > 0 else 1,
                        float(total_lines) if total_lines > 0 else 1,
                        f"Do-file completed. Cached {len(cached_graphs)} graph(s): {', '.join(cached_graphs)}"
                    )
            except Exception as e:
                logger.error(f"Post-execution graph detection failed: {e}")

        tail_text = tail.get_value()
        log_tail = self._read_log_tail_smart(log_path, rc, trace)
        if log_tail and len(log_tail) > len(tail_text):
            tail_text = log_tail
        combined = (tail_text or "") + (f"\n{exc}" if exc else "")
        
        # Use SMCL content as primary source for RC detection
        if not exc or rc in (1, -1):
            parsed_rc = self._parse_rc_from_smcl(smcl_content)
            if parsed_rc is not None and parsed_rc != 0:
                rc = parsed_rc
            elif rc in (-1, 0, 1):
                parsed_rc_text = self._parse_rc_from_text(combined)
                if parsed_rc_text is not None:
                    rc = parsed_rc_text
                elif rc == -1:
                    rc = 0  # Default to success if no error found

        success = (rc == 0 and exc is None)
        stderr_final = None
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
                context=context,
                rc=rc,
                command=command,
                log_path=log_path,
                snippet=smcl_content[-800:] if smcl_content else combined[-800:],
                smcl_output=smcl_content,
            )
            stderr_final = context

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
            stdout="",
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

        # Truncate stdout if requested
        if max_output_lines is not None and result.stdout:
            lines = result.stdout.splitlines()
            if len(lines) > max_output_lines:
                truncated_lines = lines[:max_output_lines]
                truncated_lines.append(f"\n... (output truncated: showing {max_output_lines} of {len(lines)} lines)")
                result = CommandResponse(
                    command=result.command,
                    rc=result.rc,
                    stdout="\n".join(truncated_lines),
                    stderr=result.stderr,
                    success=result.success,
                    error=result.error,
                )

        return result

    def get_data(self, start: int = 0, count: int = 50) -> List[Dict[str, Any]]:
        """Returns valid JSON-serializable data."""
        if not self._initialized:
            self.init()

        if count > self.MAX_DATA_ROWS:
            count = self.MAX_DATA_ROWS

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

        n = int(Data.getObsTotal())
        k = int(Data.getVarCount())

        frame = "default"
        sortlist = ""
        changed = False
        try:
            frame = str(Macro.getGlobal("frame") or "default")
        except Exception:
            logger.debug("Failed to get 'frame' macro", exc_info=True)
            frame = "default"
        try:
            sortlist = str(Macro.getGlobal("sortlist") or "")
        except Exception:
            logger.debug("Failed to get 'sortlist' macro", exc_info=True)
            sortlist = ""
        try:
            changed = bool(int(float(Macro.getGlobal("changed") or "0")))
        except Exception:
            logger.debug("Failed to get 'changed' macro", exc_info=True)
            changed = False

        return {"frame": frame, "n": n, "k": k, "sortlist": sortlist, "changed": changed}

    def _require_data_in_memory(self) -> None:
        state = self.get_dataset_state()
        if int(state.get("k", 0) or 0) == 0 and int(state.get("n", 0) or 0) == 0:
            # Stata empty dataset could still have k>0 n==0; treat that as ok.
            raise RuntimeError("No data in memory")

    def _get_var_index_map(self) -> Dict[str, int]:
        from sfi import Data  # type: ignore[import-not-found]

        out: Dict[str, int] = {}
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

        indices: List[int] = []
        for start in range(0, n, chunk_size):
            end = min(start + chunk_size, n)
            obs_list = list(range(start, end))
            raw_rows = Data.get(var=vars_used, obs=obs_list) if vars_used else [[None] for _ in obs_list]

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
            result = self.run_command_structured(cmd, echo=False)
            if not result.success:
                error_msg = result.error.message if result.error else "Sort failed"
                raise RuntimeError(f"Failed to sort dataset: {error_msg}")
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"Failed to sort dataset: {e}")

    def get_variable_details(self, varname: str) -> str:
        """Returns codebook/summary for a specific variable."""
        resp = self.run_command_structured(f"codebook {varname}", echo=True)
        if resp.success:
            return resp.stdout
        if resp.error:
            return resp.error.message
        return ""

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
                    return self._list_graphs_cache
                else:
                    logger.debug("Recursive list_graphs call prevented, returning empty list")
                    return []

        # Check if cache is valid
        current_time = time.time()
        with self._list_graphs_cache_lock:
            if (not force_refresh and self._list_graphs_cache is not None and
                current_time - self._list_graphs_cache_time < self.LIST_GRAPHS_TTL):
                return self._list_graphs_cache

        # Cache miss or expired, fetch fresh data
        try:
            # Preservation of r() results is critical because this can be called
            # automatically after every user command (e.g., during streaming).
            import time
            hold_name = f"_mcp_ghold_{int(time.time() * 1000 % 1000000)}"
            self.stata.run(f"capture _return hold {hold_name}", echo=False)
            
            try:
                self.stata.run("macro define mcp_graph_list \"\"", echo=False)
                self.stata.run("quietly graph dir, memory", echo=False)
                from sfi import Macro  # type: ignore[import-not-found]
                self.stata.run("macro define mcp_graph_list `r(list)'", echo=False)
                graph_list_str = Macro.getGlobal("mcp_graph_list")
            finally:
                self.stata.run(f"capture _return restore {hold_name}", echo=False)

            raw_list = graph_list_str.split() if graph_list_str else []

            # Map internal Stata names back to user-facing names when we have an alias.
            reverse = getattr(self, "_graph_name_reverse", {})
            graph_list = [reverse.get(n, n) for n in raw_list]

            result = graph_list

            # Update cache
            with self._list_graphs_cache_lock:
                self._list_graphs_cache = result
                self._list_graphs_cache_time = time.time()
            
            return result
            
        except Exception as e:
            # On error, return cached result if available, otherwise empty list
            with self._list_graphs_cache_lock:
                if self._list_graphs_cache is not None:
                    logger.warning(f"list_graphs failed, returning cached result: {e}")
                    return self._list_graphs_cache
            logger.warning(f"list_graphs failed, no cache available: {e}")
            return []

    def list_graphs_structured(self) -> GraphListResponse:
        names = self.list_graphs()
        active_name = names[-1] if names else None
        graphs = [GraphInfo(name=n, active=(n == active_name)) for n in names]
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
        if fmt not in {"pdf", "png"}:
            raise ValueError(f"Unsupported graph export format: {format}. Allowed: pdf, png.")

        if not filename:
            suffix = f".{fmt}"
            with tempfile.NamedTemporaryFile(prefix="mcp_stata_", suffix=suffix, delete=False) as tmp:
                filename = tmp.name
        else:
            # Ensure fresh start
            if os.path.exists(filename):
                try:
                    os.remove(filename)
                except Exception:
                    pass

        # Keep the user-facing path as a normal absolute Windows path
        user_filename = os.path.abspath(filename)

        if fmt == "png" and os.name == "nt":
            # 1) Save graph to a .gph file from the embedded session
            with tempfile.NamedTemporaryFile(prefix="mcp_stata_graph_", suffix=".gph", delete=False) as gph_tmp:
                gph_path = gph_tmp.name
            gph_path_for_stata = gph_path.replace("\\", "/")
            # Make the target graph current, then save without name() (which isn't accepted there)
            if graph_name:
                self._exec_no_capture(f'graph display "{graph_name}"', echo=False)
            save_cmd = f'graph save "{gph_path_for_stata}", replace'
            save_resp = self._exec_no_capture(save_cmd, echo=False)
            if not save_resp.success:
                msg = save_resp.error.message if save_resp.error else f"graph save failed (rc={save_resp.rc})"
                raise RuntimeError(msg)

            # 2) Prepare a do-file to export PNG externally
            user_filename_fwd = user_filename.replace("\\", "/")
            do_lines = [
                f'graph use "{gph_path_for_stata}"',
                f'graph export "{user_filename_fwd}", replace as(png)',
                "exit",
            ]
            with tempfile.NamedTemporaryFile(prefix="mcp_stata_export_", suffix=".do", delete=False, mode="w", encoding="ascii") as do_tmp:
                do_tmp.write("\n".join(do_lines))
                do_path = do_tmp.name

            stata_exe = getattr(self, "_stata_exec_path", None)
            if not stata_exe or not os.path.exists(stata_exe):
                raise RuntimeError("Stata executable path unavailable for PNG export")

            workdir = os.path.dirname(do_path) or None
            log_path = os.path.splitext(do_path)[0] + ".log"

            cmd = [stata_exe, "/e", "do", do_path]
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
                    os.remove(do_path)
                except Exception:
                    # Ignore errors during temporary do-file cleanup (file may not exist or be locked)
                    logger.warning("Failed to remove temporary do-file: %s", do_path, exc_info=True)

                try:
                    os.remove(gph_path)
                except Exception:
                    logger.warning("Failed to remove temporary graph file: %s", gph_path, exc_info=True)

                try:
                    if os.path.exists(log_path):
                        os.remove(log_path)
                except Exception:
                    logger.warning("Failed to remove temporary log file: %s", log_path, exc_info=True)

            if completed.returncode != 0:
                err = completed.stderr.strip() or completed.stdout.strip() or str(completed.returncode)
                raise RuntimeError(f"External Stata export failed: {err}")

        else:
            # Stata prefers forward slashes in its command parser on Windows
            filename_for_stata = user_filename.replace("\\", "/")

            cmd = "graph export"
            if graph_name:
                resolved = self._resolve_graph_name_for_stata(graph_name)
                cmd += f' "{filename_for_stata}", name("{resolved}") replace as({fmt})'
            else:
                cmd += f' "{filename_for_stata}", replace as({fmt})'

            # Avoid stdout/stderr redirection for graph export because PyStata's
            # output thread can crash on Windows when we swap stdio handles.
            resp = self._exec_no_capture(cmd, echo=False)
            if not resp.success:
                # Retry once after a short pause in case Stata had a transient file handle issue
                time.sleep(0.2)
                resp_retry = self._exec_no_capture(cmd, echo=False)
                if not resp_retry.success:
                    msg = resp_retry.error.message if resp_retry.error else f"graph export failed (rc={resp_retry.rc})"
                    raise RuntimeError(msg)
                resp = resp_retry

        if os.path.exists(user_filename):
            try:
                size = os.path.getsize(user_filename)
                if size == 0:
                    raise RuntimeError(f"Graph export failed: produced empty file {user_filename}")
                if size > self.MAX_GRAPH_BYTES:
                    raise RuntimeError(
                        f"Graph export failed: file too large (> {self.MAX_GRAPH_BYTES} bytes): {user_filename}"
                    )
            except Exception as size_err:
                # Clean up oversized or unreadable files
                try:
                    os.remove(user_filename)
                except Exception:
                    pass
                raise size_err
            return user_filename

        # If file missing, it failed. Check output for details.
        msg = resp.error.message if resp.error else "graph export failed: file missing"
        raise RuntimeError(msg)

    def get_help(self, topic: str, plain_text: bool = False) -> str:
        """Returns help text as Markdown (default) or plain text."""
        if not self._initialized:
            self.init()

        # Try to locate the .sthlp help file
        # We use 'capture' to avoid crashing if not found
        self.stata.run(f"capture findfile {topic}.sthlp")

        # Retrieve the found path from r(fn)
        from sfi import Macro  # type: ignore[import-not-found]
        self.stata.run("global mcp_help_file `r(fn)'")
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
            # We must be extremely careful not to clobber r()/e() while fetching their names.
            # We use a hold to peek at the results.
            hold_name = f"mcp_peek_{uuid.uuid4().hex[:8]}"
            self.stata.run(f"capture _return hold {hold_name}", echo=False)
            
            try:
                from sfi import Scalar, Macro
                results = {"r": {}, "e": {}}
                
                for rclass in ["r", "e"]:
                    # Restore with 'hold' to peek at results without losing them from the hold
                    # Note: Stata 18+ supports 'restore ..., hold' which is ideal.
                    self.stata.run(f"capture _return restore {hold_name}, hold", echo=False)
                    
                    # Fetch names using backtick expansion (which we verified works better than colon)
                    # and avoid leading underscores which were causing syntax errors with 'global'
                    self.stata.run(f"macro define mcp_scnames `: {rclass}(scalars)'", echo=False)
                    self.stata.run(f"macro define mcp_macnames `: {rclass}(macros)'", echo=False)
                    
                    # 1. Capture Scalars
                    names_str = Macro.getGlobal("mcp_scnames")
                    if names_str:
                        for name in names_str.split():
                            try:
                                val = Scalar.getValue(f"{rclass}({name})")
                                results[rclass][name] = val
                            except Exception:
                                pass
                                
                    # 2. Capture Macros (strings)
                    macros_str = Macro.getGlobal("mcp_macnames")
                    if macros_str:
                        for name in macros_str.split():
                            try:
                                # Restore/Hold again to be safe before fetching each macro
                                self.stata.run(f"capture _return restore {hold_name}, hold", echo=False)
                                # Capture the string value into a macro
                                self.stata.run(f"macro define mcp_mval `{rclass}({name})'", echo=False)
                                val = Macro.getGlobal("mcp_mval")
                                results[rclass][name] = val
                            except Exception:
                                pass
                
                # Cleanup
                self.stata.run("macro drop mcp_scnames mcp_macnames mcp_mval", echo=False)
                self.stata.run(f"capture _return restore {hold_name}", echo=False) # Restore one last time to leave Stata in correct state
                
                self._last_results = results
                return results
            except Exception as e:
                logger.error(f"SFI-based get_stored_results failed: {e}")
                # Try to clean up hold if we failed
                try:
                    self.stata.run(f"capture _return drop {hold_name}", echo=False)
                except Exception:
                    pass
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
                    self._preemptive_cache_dir = tempfile.mkdtemp(prefix=unique_id)
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
                    self._preemptive_cache_dir = tempfile.mkdtemp(prefix=unique_id)
    
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
            cmd = f'graph display {resolved}'
            resp = self._exec_no_capture(cmd, echo=False)
            return resp.success
        except Exception:
            return False
    
    def _is_cache_valid(self, graph_name: str, cache_path: str) -> bool:
        """Check if cached content is still valid."""
        try:
            # Get current graph content hash
            import tempfile
            import os
            
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, f"temp_{graph_name}_{os.getpid()}.svg")

            resolved = self._resolve_graph_name_for_stata(graph_name)
            export_cmd = f'graph export "{temp_file.replace("\\\\", "/")}", name({resolved}) replace as(svg)'
            resp = self._exec_no_capture(export_cmd, echo=False)
            
            if resp.success and os.path.exists(temp_file):
                with open(temp_file, 'rb') as f:
                    current_data = f.read()
                os.remove(temp_file)
                
                current_hash = self._get_content_hash(current_data)
                cached_hash = self._preemptive_cache.get(f"{graph_name}_hash")
                
                return cached_hash == current_hash
        except Exception:
            pass
        
        return False  # Assume invalid if we can't verify

    def export_graphs_all(self, use_base64: bool = False) -> GraphExportResponse:
        """Exports all graphs to file paths (default) or base64-encoded strings.

        Args:
            use_base64: If True, returns base64-encoded images. If False (default),
                       returns file paths to exported SVG files.
        """
        exports: List[GraphExport] = []
        graph_names = self.list_graphs(force_refresh=True)
        
        if not graph_names:
            return GraphExportResponse(graphs=exports)
        
        import tempfile
        import os
        import threading
        import base64
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

            temp_dir = tempfile.gettempdir()
            safe_temp_name = self._sanitize_filename(name)
            unique_filename = f"{safe_temp_name}_{uuid.uuid4().hex[:8]}_{os.getpid()}_{int(time.time())}.svg"
            svg_path = os.path.join(temp_dir, unique_filename)
            svg_path_for_stata = svg_path.replace("\\", "/")

            try:
                export_cmd = f'graph export "{svg_path_for_stata}", name({resolved}) replace as(svg)'
                export_resp = self._exec_no_capture(export_cmd, echo=False)

                if not export_resp.success:
                    display_cmd = f'graph display {resolved}'
                    display_resp = self._exec_no_capture(display_cmd, echo=False)
                    if display_resp.success:
                        export_cmd2 = f'graph export "{svg_path_for_stata}", replace as(svg)'
                        export_resp = self._exec_no_capture(export_cmd2, echo=False)
                    else:
                        export_resp = display_resp

                if export_resp.success and os.path.exists(svg_path) and os.path.getsize(svg_path) > 0:
                    with open(svg_path, "rb") as f:
                        return f.read()
                error_msg = getattr(export_resp, 'error', 'Unknown error')
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
                if use_base64:
                    with open(cached_path, "rb") as f:
                        svg_b64 = base64.b64encode(f.read()).decode("ascii")
                    exports.append(GraphExport(name=name, image_base64=svg_b64))
                else:
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
                    
                    if use_base64:
                        svg_b64 = base64.b64encode(result).decode("ascii")
                        exports.append(GraphExport(name=name, image_base64=svg_b64))
                    else:
                        exports.append(GraphExport(name=name, file_path=cache_path))
                except Exception as e:
                    cache_errors.append(f"Failed to cache graph {name}: {e}")
                    # Still return the result even if caching fails
                    if use_base64:
                        svg_b64 = base64.b64encode(result).decode("ascii")
                        exports.append(GraphExport(name=name, image_base64=svg_b64))
                    else:
                        # Create temp file for immediate use
                        safe_name = self._sanitize_filename(name)
                        temp_path = os.path.join(tempfile.gettempdir(), f"{safe_name}_{uuid.uuid4().hex[:8]}.svg")
                        with open(temp_path, 'wb') as f:
                            f.write(result)
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
            # Sanitize graph name for file system
            safe_name = self._sanitize_filename(graph_name)
            cache_path = os.path.join(self._preemptive_cache_dir, f"{safe_name}.svg")
            cache_path_for_stata = cache_path.replace("\\", "/")

            resolved_graph_name = self._resolve_graph_name_for_stata(graph_name)
            graph_name_q = self._stata_quote(resolved_graph_name)
            
            export_cmd = f'graph export "{cache_path_for_stata}", name({graph_name_q}) replace as(svg)'
            resp = self._exec_no_capture(export_cmd, echo=False)

            # Fallback: some graph names (spaces, slashes, backslashes) can confuse
            # Stata's parser in name() even when the graph exists. In that case,
            # make the graph current, then export without name().
            if not resp.success:
                try:
                    display_cmd = f'graph display {graph_name_q}'
                    display_resp = self._exec_no_capture(display_cmd, echo=False)
                    if display_resp.success:
                        export_cmd2 = f'graph export "{cache_path_for_stata}", replace as(svg)'
                        resp = self._exec_no_capture(export_cmd2, echo=False)
                except Exception:
                    pass
            
            if resp.success and os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
                # Read the data to compute hash
                with open(cache_path, 'rb') as f:
                    data = f.read()
                
                # Update cache with size tracking and eviction
                import time
                item_size = len(data)
                self._evict_cache_if_needed(item_size)
                
                with self._cache_lock:
                    self._preemptive_cache[graph_name] = cache_path
                    # Store content hash for validation
                    self._preemptive_cache[f"{graph_name}_hash"] = self._get_content_hash(data)
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
        if cwd is not None and not os.path.isdir(cwd):
            return CommandResponse(
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
        if cwd is not None and not os.path.isabs(path):
            effective_path = os.path.abspath(os.path.join(cwd, path))

        if not os.path.exists(effective_path):
            return CommandResponse(
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

        if not self._initialized:
            self.init()

        start_time = time.time()
        exc: Optional[Exception] = None
        smcl_content = ""
        smcl_path = None
        path_for_stata = effective_path.replace("\\", "/")
        command = f'do "{path_for_stata}"'

        log_file = tempfile.NamedTemporaryFile(
            prefix="mcp_stata_",
            suffix=".log",
            delete=False,
            mode="w",
            encoding="utf-8",
            errors="replace",
            buffering=1,
        )
        log_path = log_file.name
        tail = TailBuffer(max_chars=200000 if trace else 20000)
        tee = FileTeeIO(log_file, tail)

        # Create SMCL log for authoritative output capture
        smcl_fd, smcl_path = tempfile.mkstemp(prefix="mcp_smcl_", suffix=".smcl")
        os.close(smcl_fd)
        # Remove the placeholder file so Stata can create it without replace/lock issues on Windows
        try:
            os.unlink(smcl_path)
        except Exception:
            pass
        smcl_log_name = f"_mcp_smcl_{uuid.uuid4().hex[:8]}"

        rc = -1

        with self._exec_lock:
            try:
                from sfi import Scalar, SFIToolkit # Import SFI tools
                with self._temp_cwd(cwd):
                    # Open SMCL log BEFORE output redirection
                    self.stata.run(f'log using "{smcl_path}", replace smcl name({smcl_log_name})', echo=False)
                    
                    try:
                        with self._redirect_io_streaming(tee, tee):
                            try:
                                if trace:
                                    self.stata.run("set trace on")
                                ret = self.stata.run(command, echo=echo)
                                # Some PyStata builds return output as a string rather than printing.
                                if isinstance(ret, str) and ret:
                                    try:
                                        tee.write(ret)
                                    except Exception:
                                        pass
                                
                            except Exception as e:
                                exc = e
                                rc = 1
                            finally:
                                if trace:
                                    try:
                                        self.stata.run("set trace off")
                                    except Exception:
                                        pass
                    finally:
                        # Close SMCL log AFTER output redirection
                        try:
                            self.stata.run(f'capture log close {smcl_log_name}', echo=False)
                        except Exception:
                            try:
                                self.stata.run(f'capture log close {smcl_log_name}', echo=False)
                            except Exception:
                                pass

                        # Capture results immediately after execution, INSIDE the lock
                        try:
                            self._last_results = self.get_stored_results(force_fresh=True)
                        except Exception:
                            self._last_results = None
            except Exception as e:
                # Outer catch in case imports or locks fail
                exc = e
                rc = 1

        tee.close()

        # Read SMCL content as the authoritative source
        smcl_content = self._read_smcl_file(smcl_path)

        tail_text = tail.get_value()
        log_tail = self._read_log_tail_smart(log_path, rc, trace)
        if log_tail and len(log_tail) > len(tail_text):
            tail_text = log_tail
        combined = (tail_text or "") + (f"\n{exc}" if exc else "")

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

        # Truncate stdout if requested
        if max_output_lines is not None and result.stdout:
            lines = result.stdout.splitlines()
            if len(lines) > max_output_lines:
                truncated_lines = lines[:max_output_lines]
                truncated_lines.append(f"\n... (output truncated: showing {max_output_lines} of {len(lines)} lines)")
                result = CommandResponse(
                    command=result.command,
                    rc=result.rc,
                    stdout="\n".join(truncated_lines),
                    stderr=result.stderr,
                    success=result.success,
                    error=result.error,
                )

        return result

    def codebook(self, varname: str, trace: bool = False, max_output_lines: Optional[int] = None) -> CommandResponse:
        result = self._exec_with_capture(f"codebook {varname}", trace=trace)

        # Truncate stdout if requested
        if max_output_lines is not None and result.stdout:
            lines = result.stdout.splitlines()
            if len(lines) > max_output_lines:
                truncated_lines = lines[:max_output_lines]
                truncated_lines.append(f"\n... (output truncated: showing {max_output_lines} of {len(lines)} lines)")
                result = CommandResponse(
                    command=result.command,
                    rc=result.rc,
                    stdout="\n".join(truncated_lines),
                    stderr=result.stderr,
                    success=result.success,
                    error=result.error,
                )

        return result