import os
import sys
import platform
import glob
import logging
import shutil
import ntpath

from typing import Tuple, List, Optional

logger = logging.getLogger("mcp_stata.discovery")


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


def _is_executable(path: str, system: str) -> bool:
    if not os.path.exists(path):
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


def _resolve_windows_host_path(path: str, system: str) -> str:
    """
    On non-Windows hosts running Windows-discovery code, a Windows-style path
    (with backslashes) won't match the real filesystem layout. If the normalized
    path does not exist and we're emulating Windows, try swapping backslashes for
    the host separator so tests can interact with the temp filesystem.
    """
    if system != "Windows":
        return path
    if os.path.exists(path):
        return path
    if os.sep != "\\" and "\\" in path:
        alt_path = path.replace("\\", os.sep)
        if os.path.exists(alt_path):
            return alt_path
    return path


def _detect_system() -> str:
    """
    Prefer Windows detection via os.name / sys.platform instead of platform.system()
    because some environments (e.g., Cygwin/MSYS) do not return "Windows".
    """
    if os.name == "nt" or sys.platform.startswith(("cygwin", "msys")):
        return "Windows"
    return platform.system()


def find_stata_path() -> Tuple[str, str]:
    """
    Attempts to automatically locate the Stata installation path.
    Returns (path_to_executable, edition_string).

    Behavior:
    - If STATA_PATH is set and valid, use it.
    - If STATA_PATH is set but invalid, fall back to auto-discovery.
    - If auto-discovery fails, raise an error (including STATA_PATH failure context, if any).
    """
    system = _detect_system()
    stata_path_error: Optional[Exception] = None

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
        ("stata-ic", "be"),
        ("stata", "be"),
        ("xstata-mp", "mp"),
        ("xstata-se", "se"),
        ("xstata-ic", "be"),
        ("xstata", "be"),
    ]

    # 1. Check Environment Variable (supports quoted values and directory targets)
    raw_env_path = os.environ.get("STATA_PATH")
    if raw_env_path:
        try:
            path = _normalize_env_path(raw_env_path, system)
            path = _resolve_windows_host_path(path, system)
            logger.info("Trying STATA_PATH override (normalized): %s", path)

            # If a directory is provided, try standard binaries for the platform
            if os.path.isdir(path):
                search_set = []
                if system == "Windows":
                    search_set = windows_binaries
                elif system == "Linux":
                    search_set = linux_binaries
                elif system == "Darwin":
                    search_set = [
                        ("Contents/MacOS/stata-mp", "mp"),
                        ("Contents/MacOS/stata-se", "se"),
                        ("Contents/MacOS/stata", "be"),
                        ("stata-mp", "mp"),
                        ("stata-se", "se"),
                        ("stata", "be"),
                    ]

                for binary, edition in search_set:
                    candidate = os.path.join(path, binary)
                    if _is_executable(candidate, system):
                        logger.info(
                            "Found Stata via STATA_PATH directory: %s (%s)",
                            candidate,
                            edition,
                        )
                        return candidate, edition

                raise FileNotFoundError(
                    f"STATA_PATH points to directory '{path}', but no Stata executable was found within. "
                    "Point STATA_PATH directly to the Stata binary "
                    "(e.g., C:\\Program Files\\Stata19\\StataMP-64.exe)."
                )

            edition = "be"
            lower_path = path.lower()
            if "mp" in lower_path:
                edition = "mp"
            elif "se" in lower_path:
                edition = "se"
            elif "be" in lower_path:
                edition = "be"

            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"STATA_PATH points to '{path}', but that file does not exist. "
                    "Update STATA_PATH to your Stata binary (e.g., "
                    "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp, "
                    "/usr/local/stata19/stata-mp or C:\\Program Files\\Stata19Now\\StataSE-64.exe)."
                )
            if not _is_executable(path, system):
                raise PermissionError(
                    f"STATA_PATH points to '{path}', but it is not executable. "
                    "Ensure this is the Stata binary, not the .app directory."
                )

            logger.info("Using STATA_PATH override: %s (%s)", path, edition)
            return path, edition

        except Exception as exc:
            stata_path_error = exc
            logger.warning(
                "STATA_PATH override failed (%s). Falling back to auto-discovery.",
                exc,
            )

    # 2. Platform-specific search
    candidates: List[Tuple[str, str]] = []  # List of (path, edition)

    if system == "Darwin":  # macOS
        app_globs = [
            "/Applications/StataNow/StataMP.app",
            "/Applications/StataNow/StataSE.app",
            "/Applications/StataNow/Stata.app",
            "/Applications/Stata/StataMP.app",
            "/Applications/Stata/StataSE.app",
            "/Applications/Stata/Stata.app",
            "/Applications/Stata*/Stata*.app",
        ]

        for pattern in app_globs:
            for app_dir in glob.glob(pattern):
                binary_dir = os.path.join(app_dir, "Contents", "MacOS")
                if not os.path.exists(binary_dir):
                    continue
                for binary, edition in [("stata-mp", "mp"), ("stata-se", "se"), ("stata", "be")]:
                    full_path = os.path.join(binary_dir, binary)
                    if os.path.exists(full_path):
                        candidates.append((full_path, edition))

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
                if os.path.exists(full_path):
                    candidates.append((full_path, edition))

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
                        if os.path.exists(full_path):
                            candidates.append((full_path, edition))

    candidates = _dedupe_preserve(candidates)

    for path, edition in candidates:
        if not os.path.exists(path):
            logger.warning("Discovered candidate missing on disk: %s", path)
            continue
        if not _is_executable(path, system):
            logger.warning("Discovered candidate is not executable: %s", path)
            continue
        logger.info("Auto-discovered Stata at %s (%s)", path, edition)
        return path, edition

    if stata_path_error is not None:
        raise FileNotFoundError(
            "Could not automatically locate Stata after STATA_PATH failed. "
            f"STATA_PATH error was: {stata_path_error}. "
            "Fix STATA_PATH to point to the Stata executable, or install Stata in a standard location "
            "(e.g., /Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp, /usr/local/stata18/stata-mp, "
            "or C:\\Program Files\\Stata18\\StataMP-64.exe)."
        ) from stata_path_error

    raise FileNotFoundError(
        "Could not automatically locate Stata. "
        "Set STATA_PATH to your Stata executable (e.g., "
        "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp, /usr/local/stata18/stata-mp, "
        "or C:\\Program Files\\Stata18\\StataMP-64.exe)."
    )


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