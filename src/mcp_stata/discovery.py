from __future__ import annotations
"""
Optimized discovery.py with fast auto-discovery and targeted retry logic.
"""

import os
import sys
import platform
import glob
import logging
import shutil
import ntpath
import time
import re
import subprocess
import json
import hashlib
from pathlib import Path
from typing import Tuple, List, Optional, Dict, Any

logger = logging.getLogger("mcp_stata.discovery")

_VERSION_DIGITS_RE = re.compile(r"(\d{1,3})")


def _exists_with_retry(path: str, max_attempts: int = 1, delay: float = 0.01) -> bool:
    """
    Check if file exists with retry logic to handle transient failures.
    This helps with antivirus scans, file locks, and other temporary issues.
    Only use this for validating user-provided paths, not during discovery.
    """
    for attempt in range(max_attempts):
        if os.path.exists(path):
            return True
        if attempt < max_attempts - 1:
            logger.debug(
                f"File existence check attempt {attempt + 1} failed for: {path}"
            )
            time.sleep(delay)
    return False


from .utils import is_windows


def _exists_fast(path: str) -> bool:
    """Fast existence check without retries for auto-discovery."""
    return os.path.exists(path)


def _find_similar_stata_dirs(target_path: str) -> List[str]:
    """
    Find similar Stata directories to help diagnose path typos.
    Useful when user has 'Stata19Now' instead of 'StataNow19'.
    """
    parent = os.path.dirname(target_path)
    
    # If parent doesn't exist, try grandparent (for directory name typos)
    search_dir = parent
    if not os.path.exists(parent):
        search_dir = os.path.dirname(parent)
    
    if not os.path.exists(search_dir):
        return []
    
    try:
        subdirs = [
            d for d in os.listdir(search_dir)
            if os.path.isdir(os.path.join(search_dir, d))
        ]
        # Filter to Stata-related directories (case-insensitive)
        stata_dirs = [
            os.path.join(search_dir, d)
            for d in subdirs
            if 'stata' in d.lower()
        ]
        return stata_dirs
    except (OSError, PermissionError) as e:
        logger.debug(f"Could not list directory {search_dir}: {e}")
        return []


def _validate_path_with_diagnostics(path: str, system: str) -> Tuple[bool, str]:
    """
    Validate path exists and provide detailed diagnostics if not.
    Returns (exists, diagnostic_message)
    Uses retry logic for validation since this is for user-provided paths.
    """
    if _exists_with_retry(path):
        return True, ""
    
    # Build diagnostic message
    diagnostics = []
    diagnostics.append(f"File not found: '{path}'")
    
    parent_dir = os.path.dirname(path)
    filename = os.path.basename(path)
    
    if _exists_with_retry(parent_dir):
        diagnostics.append(f"✓ Parent directory exists: '{parent_dir}'")
        try:
            files_in_parent = os.listdir(parent_dir)
            # Look for similar filenames
            similar_files = [
                f for f in files_in_parent
                if 'stata' in f.lower() and f.lower().endswith('.exe' if system == 'Windows' else '')
            ]
            if similar_files:
                diagnostics.append(f"Found {len(similar_files)} Stata file(s) in parent:")
                for f in similar_files[:5]:  # Show max 5
                    diagnostics.append(f"  - {f}")
            else:
                diagnostics.append(f"No Stata executables found in parent directory")
                diagnostics.append(f"Files present: {', '.join(files_in_parent[:10])}")
        except (OSError, PermissionError) as e:
            diagnostics.append(f"✗ Could not list parent directory: {e}")
    else:
        diagnostics.append(f"✗ Parent directory does not exist: '{parent_dir}'")
        
        # Check for similar directories (typo detection)
        similar_dirs = _find_similar_stata_dirs(path)
        if similar_dirs:
            diagnostics.append("\nDid you mean one of these directories?")
            for dir_path in similar_dirs[:5]:
                diagnostics.append(f"  - {dir_path}")
    
    return False, "\n".join(diagnostics)


def _normalize_env_path(raw: str, system: str) -> str:
    """Strip quotes/whitespace, expand variables, and normalize slashes for STATA_PATH."""
    cleaned = raw.strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (
        cleaned.startswith("'") and cleaned.endswith("'")
    ):
        cleaned = cleaned[1:-1].strip()

    expanded = os.path.expandvars(os.path.expanduser(cleaned))

    # Always normalize path separators for the intended platform. This is especially
    # important when running Windows discovery tests on non-Windows hosts where
    # os.path (PosixPath) would otherwise leave backslashes untouched.
    if system == "Windows":
        return ntpath.normpath(expanded)
    return os.path.normpath(expanded)


def _is_executable(path: str, system: str, use_retry: bool = True) -> bool:
    """
    Check if path is executable.
    use_retry: Use retry logic for user-provided paths, fast check for discovery.
    """
    exists_check = _exists_with_retry if use_retry else _exists_fast
    
    if not exists_check(path):
        return False
    if system == "Windows":
        # On Windows, check if it's a file and has .exe extension
        return os.path.isfile(path) and path.lower().endswith(".exe")
    return os.access(path, os.X_OK)


def _dedupe_preserve(items: List[tuple]) -> List[tuple]:
    seen = set()
    unique = []
    for path, edition in items:
        if path in seen:
            continue
        seen.add(path)
        unique.append((path, edition))
    return unique


def _dedupe_str_preserve(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for s in items:
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _extract_version_number(path: str) -> int:
    """
    Extract the highest Stata version number found in path components that
    mention 'stata'. Returns 0 if no version is found.
    """
    version = 0
    normalized = path.lower().replace("\\", os.sep)
    for part in normalized.split(os.sep):
        if "stata" not in part:
            continue
        for match in _VERSION_DIGITS_RE.findall(part):
            try:
                version = max(version, int(match))
            except ValueError:
                continue
    return version


def _sort_candidates(candidates: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Sort candidates by version desc, edition (mp>se>be), then path for stability."""
    edition_rank = {"mp": 3, "se": 2, "be": 1}

    def sort_key(item: Tuple[str, str]):
        path, edition = item
        version = _extract_version_number(path)
        rank = edition_rank.get((edition or "").lower(), 0)
        return (-version, -rank, path)

    return sorted(candidates, key=sort_key)


def _resolve_windows_host_path(path: str, system: str) -> str:
    """
    On non-Windows hosts running Windows-discovery code, a Windows-style path
    (with backslashes) won't match the real filesystem layout. If the normalized
    path does not exist and we're emulating Windows, try swapping backslashes for
    the host separator so tests can interact with the temp filesystem.
    """
    if system != "Windows":
        return path
    if _exists_fast(path):
        return path
    if os.sep != "\\" and "\\" in path:
        alt_path = path.replace("\\", os.sep)
        if _exists_fast(alt_path):
            return alt_path
    return path


def _detect_system() -> str:
    """
    Prefer Windows detection via is_windows() / sys.platform instead of platform.system()
    because some environments (e.g., Cygwin/MSYS) do not return "Windows".
    """
    if is_windows() or sys.platform.startswith(("cygwin", "msys")):
        return "Windows"
    return platform.system()


def find_stata_candidates() -> List[Tuple[str, str]]:
    """
    Locate all viable Stata installations ordered by preference.

    Returns:
        List of (path_to_executable, edition_string) sorted by:
        - Newest version number found in path (desc)
        - Edition preference: mp > se > be
        - Path name (stable tie-breaker)

    Behavior:
    - If STATA_PATH is set and valid, use it (may yield multiple binaries in dir).
    - If STATA_PATH is set but invalid, provide detailed diagnostics and fall back.
    - If auto-discovery fails, raise an error with helpful suggestions.
    """
    system = _detect_system()
    stata_path_error: Optional[Exception] = None
    stata_path_diagnostics: Optional[str] = None

    windows_binaries = [
        ("StataMP-64.exe", "mp"),
        ("StataMP.exe", "mp"),
        ("StataSE-64.exe", "se"),
        ("StataSE.exe", "se"),
        ("Stata-64.exe", "be"),
        ("Stata.exe", "be"),
    ]
    linux_binaries = [
        ("stata-mp", "mp"),
        ("stata-se", "se"),
        ("stata", "be"),
        ("xstata-mp", "mp"),
        ("xstata-se", "se"),
        ("xstata", "be"),
    ]

    # 1. Check STATA_PATH override with enhanced diagnostics
    raw_stata_path = os.environ.get("STATA_PATH")
    if raw_stata_path:
        try:
            path = _normalize_env_path(raw_stata_path, system)
            path = _resolve_windows_host_path(path, system)

            if os.path.isdir(path):
                candidates_in_dir = []
                if system == "Windows":
                    for exe, edition in windows_binaries:
                        candidate = os.path.join(path, exe)
                        if _is_executable(candidate, system, use_retry=True):
                            candidates_in_dir.append((candidate, edition))
                elif system == "Darwin" or (system != "Windows" and path.endswith(".app")):
                    # macOS app bundle logic
                    sub_path = os.path.join(path, "Contents", "MacOS")
                    if os.path.isdir(sub_path):
                        for binary, edition in [("stata-mp", "mp"), ("stata-se", "se"), ("stata", "be")]:
                            candidate = os.path.join(sub_path, binary)
                            if _is_executable(candidate, system, use_retry=True):
                                candidates_in_dir.append((candidate, edition))
                    
                    # Also try direct if not in a bundle
                    if not candidates_in_dir:
                        for binary, edition in linux_binaries:
                            candidate = os.path.join(path, binary)
                            if _is_executable(candidate, system, use_retry=True):
                                candidates_in_dir.append((candidate, edition))
                else:
                    for binary, edition in linux_binaries:
                        candidate = os.path.join(path, binary)
                        if _is_executable(candidate, system, use_retry=True):
                            candidates_in_dir.append((candidate, edition))

                if candidates_in_dir:
                    resolved = []
                    for candidate, edition in _sort_candidates(candidates_in_dir):
                        if _is_executable(candidate, system, use_retry=True):
                            logger.info(
                                "Found Stata via STATA_PATH directory: %s (%s)",
                                candidate,
                                edition,
                            )
                            resolved.append((candidate, edition))
                    if resolved:
                        return resolved

                # Enhanced error with diagnostics
                exists, diagnostics = _validate_path_with_diagnostics(path, system)
                error_msg = (
                    f"STATA_PATH points to directory '{path}', but no Stata executable was found within.\n"
                    f"{diagnostics}\n\n"
                    "Point STATA_PATH directly to the Stata binary "
                    "(e.g., C:\\Program Files\\StataNow19\\StataMP-64.exe)."
                )
                raise FileNotFoundError(error_msg)

            edition = "be"
            lower_path = path.lower()
            if "mp" in lower_path:
                edition = "mp"
            elif "se" in lower_path:
                edition = "se"
            elif "be" in lower_path:
                edition = "be"

            # Use enhanced validation with diagnostics (with retry for user path)
            exists, diagnostics = _validate_path_with_diagnostics(path, system)
            if not exists:
                error_msg = (
                    f"STATA_PATH points to '{path}', but that file does not exist.\n"
                    f"{diagnostics}\n\n"
                    "Update STATA_PATH to your Stata binary (e.g., "
                    "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp, "
                    "/usr/local/stata19/stata-mp or C:\\Program Files\\StataNow19\\StataMP-64.exe)."
                )
                raise FileNotFoundError(error_msg)
                
            if not _is_executable(path, system, use_retry=True):
                raise PermissionError(
                    f"STATA_PATH points to '{path}', but it is not executable. "
                    "Ensure this is the Stata binary, not the .app directory."
                )

            logger.info("Using STATA_PATH override: %s (%s)", path, edition)
            return [(path, edition)]

        except Exception as exc:
            stata_path_error = exc
            stata_path_diagnostics = str(exc)
            logger.warning(
                "STATA_PATH override failed (%s). Falling back to auto-discovery.",
                exc,
            )

    # 2. Platform-specific search (using fast checks, no retries)
    candidates: List[Tuple[str, str]] = []  # List of (path, edition)

    if system == "Darwin":  # macOS
        # Search targets specific to macOS installation patterns
        patterns = [
            "/Applications/StataNow/StataMP.app",
            "/Applications/StataNow/StataSE.app",
            "/Applications/StataNow/Stata.app",
            "/Applications/Stata/StataMP.app",
            "/Applications/Stata/StataSE.app",
            "/Applications/Stata/Stata.app",
            "/Applications/Stata*/Stata*.app",
            "/Applications/Stata*.app",
        ]

        for pattern in patterns:
            for app_dir in glob.glob(pattern):
                binary_dir = os.path.join(app_dir, "Contents", "MacOS")
                if not _exists_fast(binary_dir):
                    continue
                for binary, edition in [("stata-mp", "mp"), ("stata-se", "se"), ("stata", "be")]:
                    full_path = os.path.join(binary_dir, binary)
                    if _exists_fast(full_path):
                        candidates.append((full_path, edition))
        candidates = _dedupe_preserve(candidates)

    elif system == "Windows":
        # Include ProgramW6432 (real 64-bit Program Files) and hardcode fallbacks.
        base_dirs = _dedupe_str_preserve(
            [
                os.environ.get("ProgramW6432", r"C:\Program Files"),
                os.environ.get("ProgramFiles", r"C:\Program Files"),
                os.environ.get("ProgramFiles(Arm)", r"C:\Program Files (Arm)"),
                os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                r"C:\Program Files",
                r"C:\Program Files (Arm)",
                r"C:\Program Files (x86)",
            ]
        )

        # Resolve for non-Windows hosts running Windows discovery tests.
        base_dirs = [
            _resolve_windows_host_path(ntpath.normpath(bd), system) for bd in base_dirs
        ]
        base_dirs = _dedupe_str_preserve(base_dirs)

        # Look in a few plausible layouts:
        #   base\Stata*\...
        #   base\*\Stata*\...   (e.g., base\StataCorp\Stata19Now)
        #   base\Stata*\*\...   (e.g., base\Stata\Stata19Now)
        dir_globs: List[str] = []
        for base_dir in base_dirs:
            dir_globs.extend(
                [
                    os.path.join(base_dir, "Stata*"),
                    os.path.join(base_dir, "*", "Stata*"),
                    os.path.join(base_dir, "Stata*", "Stata*"),
                ]
            )
        dir_globs = _dedupe_str_preserve(dir_globs)

        stata_dirs: List[str] = []
        for pattern in dir_globs:
            stata_dirs.extend(glob.glob(pattern))
        stata_dirs = _dedupe_str_preserve(stata_dirs)

        for stata_dir in stata_dirs:
            if not os.path.isdir(stata_dir):
                continue
            for exe, edition in windows_binaries:
                full_path = os.path.join(stata_dir, exe)
                if _exists_fast(full_path):
                    candidates.append((full_path, edition))
        candidates = _dedupe_preserve(candidates)

    elif system == "Linux":
        home_base = os.environ.get("HOME") or os.path.expanduser("~")

        # 2a. Try binaries available on PATH first
        for binary, edition in linux_binaries:
            found = shutil.which(binary)
            if found:
                candidates.append((found, edition))

        # 2b. Search common install prefixes used by Stata's Linux installer
        linux_roots = [
            "/usr/local",
            "/opt",
            os.path.join(home_base, "stata"),
            os.path.join(home_base, "Stata"),
        ]

        for root in linux_roots:
            patterns: List[str] = []
            if root.endswith(("stata", "Stata")):
                patterns.append(root)
            else:
                patterns.extend(
                    [
                        os.path.join(root, "stata*"),
                        os.path.join(root, "Stata*"),
                    ]
                )

            for pattern in patterns:
                for base_dir in glob.glob(pattern):
                    if not os.path.isdir(base_dir):
                        continue
                    for binary, edition in linux_binaries:
                        full_path = os.path.join(base_dir, binary)
                        if _exists_fast(full_path):
                            candidates.append((full_path, edition))

        candidates = _dedupe_preserve(candidates)

    # Final validation of candidates (still using fast checks)
    validated: List[Tuple[str, str]] = []
    unique_candidates = _dedupe_preserve(candidates)
    for path, edition in _sort_candidates(unique_candidates):
        if not _exists_fast(path):
            logger.warning("Discovered candidate missing on disk: %s", path)
            continue
        if not _is_executable(path, system, use_retry=False):
            logger.warning("Discovered candidate is not executable: %s", path)
            continue
        logger.info("Auto-discovered Stata at %s (%s)", path, edition)
        validated.append((path, edition))

    if validated:
        return validated

    # Build comprehensive error message
    error_parts = ["Could not automatically locate Stata."]
    
    if stata_path_error is not None:
        error_parts.append(
            f"\nSTATA_PATH was set but failed:\n{stata_path_diagnostics}"
        )
    
    error_parts.append(
        "\nTo fix this issue:\n"
        "1. Set STATA_PATH to point to your Stata executable, for example:\n"
        "   - Windows: C:\\Program Files\\StataNow19\\StataMP-64.exe\n"
        "   - macOS: /Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp\n"
        "   - Linux: /usr/local/stata19/stata-mp\n"
        "\n2. Or install Stata in a standard location where it can be auto-discovered."
    )
    
    if stata_path_error is not None:
        raise FileNotFoundError("\n".join(error_parts)) from stata_path_error
    else:
        raise FileNotFoundError("\n".join(error_parts))


def get_stata_install_root(executable_path: str) -> Optional[str]:
    """
    Find the Stata installation root directory from an executable path.
    Walks up from the binary directory to find the directory containing 'utilities'.
    """
    bin_dir = os.path.dirname(executable_path)
    curr = bin_dir
    while len(curr) > 1:
        # Check if this directory contains the 'utilities' folder (where pystata lives)
        if os.path.isdir(os.path.join(curr, "utilities")):
            return curr
        
        # Also look for .app bundle on macOS
        if curr.endswith(".app"):
            parent = os.path.dirname(curr)
            if parent and parent != "/" and os.path.isdir(os.path.join(parent, "utilities")):
                return parent
            return curr
        
        parent = os.path.dirname(curr)
        if parent == curr: 
            break
        curr = parent
    
    return bin_dir


_DISCOVERY_CACHE_PATH = Path.home() / ".mcp-stata-discovery-cache.json"

def _load_discovery_cache() -> Dict[str, Any]:
    if not _DISCOVERY_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_DISCOVERY_CACHE_PATH.read_text())
    except Exception:
        return {}

def _save_discovery_cache(cache: Dict[str, Any]) -> None:
    try:
        # Keep cache size reasonable
        if len(cache) > 50:
            # Sort by timestamp and keep newest 50
            sorted_items = sorted(cache.items(), key=lambda x: x[1].get('at', 0), reverse=True)
            cache = dict(sorted_items[:50])
        _DISCOVERY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DISCOVERY_CACHE_PATH.write_text(json.dumps(cache))
    except Exception:
        pass

def _get_stata_fingerprint(root_path: str, exe_path: Optional[str] = None) -> str:
    """Generate a fingerprint of the Stata installation to detect changes."""
    # Start with the root and specific components
    paths = [root_path]
    
    # Include immediate children to detect added/removed editions (.app bundles or directories)
    try:
        if os.path.isdir(root_path):
            for item in os.listdir(root_path):
                # We only check immediate children to keep it fast
                paths.append(os.path.join(root_path, item))
    except Exception:
        pass

    if exe_path and os.path.exists(exe_path) and exe_path not in paths:
        paths.append(exe_path)
    
    # Sort paths for consistent fingerprinting
    paths.sort()
    
    parts = []
    for p in paths:
        try:
            # For directories, stat() mtime changes on add/remove of immediate children
            # For files, stat() mtime changes on content update
            stat = os.stat(p)
            parts.append(f"{os.path.basename(p)}:{stat.st_mtime}:{stat.st_size}")
        except Exception:
            pass
    
    fingerprint_raw = "|".join(parts)
    return hashlib.md5(fingerprint_raw.encode("utf-8")).hexdigest()


def verify_stata_install(root_path: str, edition: str, timeout: int = 120, use_cache: bool = True, exe_path: Optional[str] = None) -> bool:
    """
    Perform a pre-flight check in a subprocess to see if this Stata installation works.
    Returns True if the installation is valid and can run a basic command.
    Uses a persistent cache to avoid redundant verification.
    """
    # Check cache first
    cache_key = f"{root_path}:{edition}"
    fingerprint = _get_stata_fingerprint(root_path, exe_path)
    
    if use_cache:
        cache = _load_discovery_cache()
        if cache_key in cache:
            entry = cache[cache_key]
            try:
                # Check if the installation fingerprint has changed
                if entry.get("fingerprint") == fingerprint:
                    # Trust the cached result if it was successful or recently checked
                    is_working = entry.get("working", False)
                    verified_at = entry.get("at", 0)
                    if is_working or (time.time() - verified_at < 86400): # Re-check broken every 24h
                        return is_working
            except Exception:
                pass

    preflight_code = f"""
import sys
import os
import faulthandler

# Enable faulthandler to capture C-level crashes in Stata shared library
faulthandler.enable(file=sys.stderr)

try:
    utils_path = os.path.join({repr(root_path)}, 'utilities')
    if os.path.isdir(utils_path) and utils_path not in sys.path:
        sys.path.insert(0, utils_path)
    
    # Try importing stata_setup (the standard helper)
    try:
        import stata_setup
        sys.stderr.write(f"[preflight] Calling stata_setup.config({repr(root_path)}, {repr(edition)})...\\n")
        sys.stderr.flush()
        stata_setup.config({repr(root_path)}, {repr(edition)})
    except (ImportError, ModuleNotFoundError):
        # Fallback for Stata installations missing stata_setup.py helper (common in some StataNow builds)
        # If we have the 'utilities' folder in sys.path, pystata.config.init() should work.
        try:
            import pystata.config
            sys.stderr.write(f"[preflight] stata_setup not found, trying pystata.config.init({repr(edition)})...\\n")
            sys.stderr.flush()
            pystata.config.init({repr(edition)}, splash=False)
        except (ImportError, ModuleNotFoundError, AttributeError):
             sys.stderr.write('PREFLIGHT_FAIL: Neither stata_setup nor pystata.config found in ' + utils_path + '\\n')
             sys.exit(1)

    sys.stderr.write('[preflight] Importing pystata.stata...\\n')
    sys.stderr.flush()
    from pystata import stata
    sys.stderr.write('[preflight] Running diagnostic command...\\n')
    sys.stderr.flush()
    stata.run('display 1', echo=False)
    sys.stdout.write('PREFLIGHT_OK\\n')
    sys.stdout.flush()
except Exception as e:
    sys.stderr.write(f'PREFLIGHT_FAIL: {{e}}\\n')
    import traceback
    traceback.print_exc()
    sys.stderr.flush()
    sys.exit(1)
except BaseException as e:
    # Capture SystemExit or other non-Exception signals (like hard exits from pystata)
    sys.stderr.write(f'PREFLIGHT_CRASH: {{repr(e)}}\\n')
    sys.stderr.flush()
    sys.exit(1)
"""

    is_working = False
    try:
        py_exe = sys.executable
        if not py_exe or not os.path.exists(py_exe):
            py_exe = os.path.realpath(sys.executable)
            
        env = os.environ.copy()
        # Ensure PYTHONPATH includes the current sys.path to find stata_setup
        extra_paths = [p for p in sys.path if p and os.path.isdir(p)]
        if extra_paths:
            existing = env.get("PYTHONPATH", "")
            merged = os.pathsep.join(extra_paths + ([existing] if existing else []))
            env["PYTHONPATH"] = merged
            
        res = subprocess.run(
            [py_exe, "-c", preflight_code],
            capture_output=True, text=True, timeout=timeout, env=env
        )
        
        if res.returncode == 0 and "PREFLIGHT_OK" in res.stdout:
            is_working = True
        else:
            msg = f"Verification failed for {root_path} (edition {edition}). rc={res.returncode}"
            if res.stdout:
                 msg += f"\nSTDOUT: {res.stdout.strip()}"
            if res.stderr:
                 msg += f"\nSTDERR: {res.stderr.strip()}"
            logger.debug(msg)
            is_working = False
    except subprocess.TimeoutExpired as e:
        msg = f"Pre-flight timed out after {timeout}s for {root_path}"
        if e.output:
            msg += f"\n--- Captured stdout ---\n{e.output}"
        if e.stderr:
            msg += f"\n--- Captured stderr ---\n{e.stderr}"
        logger.warning(msg)
        sys.stderr.write(f"[mcp_stata] {msg}\n")
        sys.stderr.flush()
        is_working = False
    except Exception as e:
        logger.debug(f"Verification error for {root_path}: {e}")
        is_working = False

    # Update cache
    try:
        cache = _load_discovery_cache()
        cache[cache_key] = {
            "working": is_working,
            "fingerprint": fingerprint,
            "at": time.time()
        }
        _save_discovery_cache(cache)
    except Exception:
        pass
        
    return is_working


def find_working_stata_path() -> Tuple[str, str]:
    """
    Find the first Stata candidate that actually works.
    Returns (executable_path, edition).
    Uses parallel verification to speed up discovery when multiple candidates exist.
    Falls back to the first candidate if none can be verified.
    """
    from concurrent.futures import ThreadPoolExecutor
    
    candidates = find_stata_candidates()
    if not candidates:
        raise FileNotFoundError("No Stata candidates found")
        
    # If only one candidate, don't bother with thread pool overhead
    if len(candidates) == 1:
        exe_path, edition = candidates[0]
        root = get_stata_install_root(exe_path)
        if verify_stata_install(root, edition, exe_path=exe_path):
            return exe_path, edition
        return exe_path, edition

    # For multiple candidates, verify in parallel
    results = []
    with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
        # Submit all candidates for verification
        future_to_candidate = {}
        for exe_path, edition in candidates:
            root = get_stata_install_root(exe_path)
            future = executor.submit(verify_stata_install, root, edition, exe_path=exe_path)
            future_to_candidate[future] = (exe_path, edition)
            results.append(future)

        # Wait for results in priority order
        for future in results:
            exe_path, edition = future_to_candidate[future]
            if future.result():
                logger.info(f"Verified working Stata at: {exe_path}")
                return exe_path, edition
            
    logger.warning("No Stata candidates passed verification; falling back to first candidate")
    return candidates[0]


def find_stata_path() -> Tuple[str, str]:
    """
    Backward-compatible wrapper returning the top-ranked candidate.
    Now uses working candidate detection.
    """
    try:
        return find_working_stata_path()
    except Exception:
        candidates = find_stata_candidates()
        if not candidates:
            raise FileNotFoundError("No Stata installations found")
        return candidates[0]


def main() -> int:
    """CLI helper to print discovered Stata binary and edition."""
    try:
        path, edition = find_stata_path()
        # Print so CLI users and tests see the output on stdout.
        print(f"Stata executable: {path}\nEdition: {edition}")
        return 0
    except Exception as exc:  # pragma: no cover - exercised via tests with env
        print(f"Discovery failed: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover - manual utility
    raise SystemExit(main())