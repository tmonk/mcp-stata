import os
import platform
import glob
import logging
import shutil

from typing import Tuple, Optional, List

logger = logging.getLogger("mcp_stata.discovery")


def _dedupe_preserve(items: List[tuple]) -> List[tuple]:
    seen = set()
    unique = []
    for path, edition in items:
        if path in seen:
            continue
        seen.add(path)
        unique.append((path, edition))
    return unique


def find_stata_path() -> Tuple[str, str]:
    """
    Attempts to automatically locate the Stata installation path.
    Returns (path_to_executable, edition_string).
    """
    system = platform.system()

    # 1. Check Environment Variable
    if os.environ.get("STATA_PATH"):
        path = os.environ["STATA_PATH"]
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
                "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp or /usr/local/stata18/stata-mp)."
            )
        if not os.access(path, os.X_OK):
            raise PermissionError(
                f"STATA_PATH points to '{path}', but it is not executable. "
                "Ensure this is the Stata binary, not the .app directory."
            )
        logger.info("Using STATA_PATH override: %s (%s)", path, edition)
        return path, edition

    # 2. Platform-specific search
    candidates = []  # List of (path, edition)

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
        base_dirs = [
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
        ]

        for base_dir in base_dirs:
            for stata_dir in glob.glob(os.path.join(base_dir, "Stata*")):
                for exe, edition in [
                    ("StataMP-64.exe", "mp"),
                    ("StataMP.exe", "mp"),
                    ("StataSE-64.exe", "se"),
                    ("StataSE.exe", "se"),
                    ("Stata-64.exe", "be"),
                    ("Stata.exe", "be"),
                ]:
                    full_path = os.path.join(stata_dir, exe)
                    if os.path.exists(full_path):
                        candidates.append((full_path, edition))

    elif system == "Linux":
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

        # 2a. Try binaries available on PATH first
        for binary, edition in linux_binaries:
            found = shutil.which(binary)
            if found:
                candidates.append((found, edition))

        # 2b. Search common install prefixes used by Stata's Linux installer
        linux_roots = [
            "/usr/local",
            "/opt",
            os.path.expanduser("~/stata"),
            os.path.expanduser("~/Stata"),
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
        if not os.access(path, os.X_OK):
            logger.warning("Discovered candidate is not executable: %s", path)
            continue
        logger.info("Auto-discovered Stata at %s (%s)", path, edition)
        return path, edition

    raise FileNotFoundError(
        "Could not automatically locate Stata. "
        "Set STATA_PATH to your Stata executable (e.g., "
        "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp, /usr/local/stata18/stata-mp, or C:\\Program Files\\Stata18\\StataMP-64.exe)."
    )
