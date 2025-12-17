import base64
import logging
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from io import StringIO
from typing import Any, Dict, List, Optional

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

logger = logging.getLogger("mcp_stata")

class StataClient:
    _instance = None
    _initialized = False
    _exec_lock: threading.Lock
    MAX_DATA_ROWS = 500
    MAX_GRAPH_BYTES = 50 * 1024 * 1024  # Allow large graph exports (~50MB)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StataClient, cls).__new__(cls)
            cls._instance._exec_lock = threading.Lock()
        return cls._instance

    @contextmanager
    def _redirect_io(self):
        """Safely redirect stdout/stderr for the duration of a Stata call."""
        out_buf, err_buf = StringIO(), StringIO()
        backup_stdout, backup_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out_buf, err_buf
        try:
            yield out_buf, err_buf
        finally:
            sys.stdout, sys.stderr = backup_stdout, backup_stderr

    def init(self):
        """Initializes usage of pystata."""
        if self._initialized:
            return

        try:
            import stata_setup

            try:
                stata_exec_path, edition = find_stata_path()
            except FileNotFoundError as e:
                raise RuntimeError(f"Stata binary not found: {e}") from e
            except PermissionError as e:
                raise RuntimeError(
                    f"Stata binary is not executable: {e}. "
                    "Point STATA_PATH directly to the Stata binary (e.g., .../Contents/MacOS/stata-mp)."
                ) from e
            
            logger.info(f"Discovery found Stata at: {stata_exec_path} ({edition})")

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
                    stata_setup.config(path, edition)
                    success = True
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

            from pystata import stata  # type: ignore[import-not-found]
            self.stata = stata
            self._initialized = True

        except ImportError:
            # Fallback for when stata_setup isn't in PYTHONPATH yet?
            # Usually users must have it installed. We rely on discovery logic.
            raise RuntimeError("Could not import `stata_setup`. Ensure pystata is installed.")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Stata: {e}")

    def _read_return_code(self) -> int:
        """Read the last Stata return code without mutating rc."""
        try:
            from sfi import Macro  # type: ignore[import-not-found]
            rc_val = Macro.getCValue("rc")  # type: ignore[attr-defined]
            return int(float(rc_val))
        except Exception:
            try:
                self.stata.run("global MCP_RC = c(rc)")
                from sfi import Macro as Macro2  # type: ignore[import-not-found]
                rc_val = Macro2.getGlobal("MCP_RC")
                return int(float(rc_val))
            except Exception:
                return -1

    def _parse_rc_from_text(self, text: str) -> Optional[int]:
        match = re.search(r"r\((\d+)\)", text)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
        return None

    def _parse_line_from_text(self, text: str) -> Optional[int]:
        match = re.search(r"line\s+(\d+)", text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
        return None

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

    def _build_error_envelope(
        self,
        command: str,
        rc: int,
        stdout: str,
        stderr: str,
        exc: Optional[Exception],
        trace: bool,
    ) -> ErrorEnvelope:
        combined = "\n".join(filter(None, [stdout, stderr, str(exc) if exc else ""])).strip()
        rc_hint = self._parse_rc_from_text(combined) if combined else None
        rc_final = rc if rc not in (-1, None) else rc_hint
        line_no = self._parse_line_from_text(combined) if combined else None
        snippet = combined[-800:] if combined else None
        message = (stderr or (str(exc) if exc else "") or stdout or "Stata error").strip()
        return ErrorEnvelope(
            message=message,
            rc=rc_final,
            line=line_no,
            command=command,
            stdout=stdout or None,
            stderr=stderr or None,
            snippet=snippet,
            trace=trace or None,
        )

    def _exec_with_capture(self, code: str, echo: bool = True, trace: bool = False) -> CommandResponse:
        """Execute Stata code with stdout/stderr capture and rc detection."""
        if not self._initialized:
            self.init()

        start_time = time.time()
        exc: Optional[Exception] = None
        with self._exec_lock:
            with self._redirect_io() as (out_buf, err_buf):
                try:
                    if trace:
                        self.stata.run("set trace on")
                    self.stata.run(code, echo=echo)
                except Exception as e:
                    exc = e
                finally:
                    rc = self._read_return_code()
                    if trace:
                        try:
                            self.stata.run("set trace off")
                        except Exception:
                            pass

        stdout = out_buf.getvalue()
        stderr = err_buf.getvalue()
        # If no exception and stderr is empty, treat rc anomalies as success (e.g., spurious rc reads)
        if exc is None and (not stderr or not stderr.strip()):
            rc = 0 if rc is None or rc != 0 else rc
        success = rc == 0 and exc is None
        error = None
        if not success:
            error = self._build_error_envelope(code, rc, stdout, stderr, exc, trace)
        duration = time.time() - start_time
        code_preview = code.replace("\n", "\\n")
        logger.info(
            "stata.run rc=%s success=%s trace=%s duration_ms=%.2f code_preview=%s",
            rc,
            success,
            trace,
            duration * 1000,
            code_preview[:120],
        )
        # Mutually exclusive - when error, output is in ErrorEnvelope only
        return CommandResponse(
            command=code,
            rc=rc,
            stdout="" if not success else stdout,
            stderr=None,
            success=success,
            error=error,
        )

    def _exec_no_capture(self, code: str, echo: bool = False, trace: bool = False) -> CommandResponse:
        """Execute Stata code while leaving stdout/stderr alone.

        PyStata's output bridge uses its own thread and can misbehave on Windows
        when we redirect stdio (e.g., graph export). This path keeps the normal
        handlers and just reads rc afterward.
        """
        if not self._initialized:
            self.init()

        exc: Optional[Exception] = None
        with self._exec_lock:
            try:
                if trace:
                    self.stata.run("set trace on")
                self.stata.run(code, echo=echo)
            except Exception as e:
                exc = e
            finally:
                rc = self._read_return_code()
                if exc is None and (rc is None or rc == -1):
                    # Normalize spurious rc reads only when missing/invalid
                    rc = 0
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
            error = self._build_error_envelope(code, rc, stdout, stderr, exc, trace)

        return CommandResponse(
            command=code,
            rc=rc,
            stdout=stdout,
            stderr=None,
            success=success,
            error=error,
        )

    def run_command(self, code: str, echo: bool = True) -> str:
        """Runs a Stata command and returns raw output (legacy)."""
        result = self._exec_with_capture(code, echo=echo)
        if result.success:
            return result.stdout
        if result.error:
            return f"Error executing Stata code (r({result.error.rc})):\n{result.error.message}"
        return "Unknown Stata error"

    def run_command_structured(self, code: str, echo: bool = True, trace: bool = False, max_output_lines: Optional[int] = None) -> CommandResponse:
        """Runs a Stata command and returns a structured envelope.

        Args:
            code: The Stata command to execute.
            echo: If True, the command itself is included in the output.
            trace: If True, enables trace mode for debugging.
            max_output_lines: If set, truncates stdout to this many lines (token efficiency).
        """
        result = self._exec_with_capture(code, echo=echo, trace=trace)

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

    def get_variable_details(self, varname: str) -> str:
        """Returns codebook/summary for a specific variable."""
        return self.run_command(f"codebook {varname}")

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

    def list_graphs(self) -> List[str]:
        """Returns list of graphs in memory."""
        if not self._initialized:
            self.init()

        # 'graph dir' returns list in r(list)
        # We need to ensure we run it quietly so we don't spam.
        self.stata.run("quietly graph dir, memory")

        # Accessing r-class results in Python can be tricky via pystata's run command.
        # We stash the result in a global macro that python sfi can easily read.
        from sfi import Macro  # type: ignore[import-not-found]
        self.stata.run("global mcp_graph_list `r(list)'")
        graph_list_str = Macro.getGlobal("mcp_graph_list")
        if not graph_list_str:
            return []

        return graph_list_str.split()

    def list_graphs_structured(self) -> GraphListResponse:
        names = self.list_graphs()
        active_name = names[-1] if names else None
        graphs = [GraphInfo(name=n, active=(n == active_name)) for n in names]
        return GraphListResponse(graphs=graphs)

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
                cmd += f' "{filename_for_stata}", name("{graph_name}") replace as({fmt})'
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
                return f"Error reading help file at {fn}: {e}"

        # Fallback to URL if file not found
        return f"Help file for '{topic}' not found. Please consult: https://www.stata.com/help.cgi?{topic}"

    def get_stored_results(self) -> Dict[str, Any]:
        """Returns e() and r() results."""
        if not self._initialized:
            self.init()

        results = {"r": {}, "e": {}}

        # We parse 'return list' output as there is no direct bulk export of stored results
        raw_r = self.run_command("return list")
        raw_e = self.run_command("ereturn list")

        # Simple parser
        def parse_list(text):
            data = {}
            # We don't strictly need to track sections if we check patterns
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue

                # scalars: r(name) = value
                if "=" in line and ("r(" in line or "e(" in line):
                    try:
                        name_part, val_part = line.split("=", 1)
                        name_part = name_part.strip()  # "r(mean)"
                        val_part = val_part.strip()    # "6165.2..."

                        # Extract just the name inside r(...) if desired,
                        # or keep full key "r(mean)".
                        # User likely wants "mean" inside "r" dict.

                        if "(" in name_part and name_part.endswith(")"):
                            # r(mean) -> mean
                            start = name_part.find("(") + 1
                            end = name_part.find(")")
                            key = name_part[start:end]
                            data[key] = val_part
                    except Exception:
                        pass

                # macros: r(name) : "value"
                elif ":" in line and ("r(" in line or "e(" in line):
                    try:
                        name_part, val_part = line.split(":", 1)
                        name_part = name_part.strip()
                        val_part = val_part.strip().strip('"')

                        if "(" in name_part and name_part.endswith(")"):
                            start = name_part.find("(") + 1
                            end = name_part.find(")")
                            key = name_part[start:end]
                            data[key] = val_part
                    except Exception:
                        pass
            return data

        results["r"] = parse_list(raw_r)
        results["e"] = parse_list(raw_e)

        return results

    def export_graphs_all(self, use_base64: bool = False) -> GraphExportResponse:
        """Exports all graphs to file paths (default) or base64-encoded strings.

        Args:
            use_base64: If True, returns base64-encoded images. If False (default),
                       returns file paths to exported PNG files.
        """
        exports: List[GraphExport] = []
        for name in self.list_graphs():
            try:
                path = self.export_graph(name, format="png")
                if use_base64:
                    with open(path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("ascii")
                    exports.append(GraphExport(name=name, image_base64=b64))
                else:
                    exports.append(GraphExport(name=name, file_path=path))
            except Exception as e:
                logger.warning("Failed to export graph '%s': %s", name, e)
                continue
        return GraphExportResponse(graphs=exports)

    def run_do_file(self, path: str, echo: bool = True, trace: bool = False, max_output_lines: Optional[int] = None) -> CommandResponse:
        if not os.path.exists(path):
            return CommandResponse(
                command=f'do "{path}"',
                rc=601,
                stdout="",
                stderr=None,
                success=False,
                error=ErrorEnvelope(
                    message=f"Do-file not found: {path}",
                    rc=601,
                    command=path,
                ),
            )
        result = self._exec_with_capture(f'do "{path}"', echo=echo, trace=trace)

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

