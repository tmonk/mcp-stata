import os
import sys
import platform
import glob

from typing import Tuple, Optional

def find_stata_path() -> Tuple[str, str]:
    """
    Attempts to automatically locate the Stata installation path.
    Returns (path_to_executable, edition_string).
    """
    system = platform.system()
    
    # 1. Check Environment Variable
    if os.environ.get("STATA_PATH"):
        path = os.environ["STATA_PATH"]
        # Guess edition from path
        edition = "be" # default fallback
        lower_path = path.lower()
        if "mp" in lower_path: edition = "mp"
        elif "se" in lower_path: edition = "se"
        elif "be" in lower_path: edition = "be"
        return path, edition

    # 2. Platform-specific search
    candidates = [] # List of (path, edition)
    
    if system == "Darwin":  # macOS
        # Search patterns: /Applications/Stata*/*.app
        # We explicitly list StataNow and Stata
        app_globs = [
            "/Applications/StataNow/StataMP.app",
            "/Applications/StataNow/StataSE.app",
            "/Applications/StataNow/Stata.app",
            "/Applications/Stata/StataMP.app",
            "/Applications/Stata/StataSE.app",
            "/Applications/Stata/Stata.app",
            "/Applications/Stata*/Stata*.app"
        ]
        
        for pattern in app_globs:
            for app_dir in glob.glob(pattern):
                binary_dir = os.path.join(app_dir, "Contents", "MacOS")
                if not os.path.exists(binary_dir): continue
                
                # Check for specific binaries (prioritize MP)
                # 'stata-mp' is the binary name usually
                for binary, edition in [("stata-mp", "mp"), ("stata-se", "se"), ("stata", "be")]:
                    full_path = os.path.join(binary_dir, binary)
                    if os.path.exists(full_path):
                        candidates.append((full_path, edition))

    elif system == "Windows":
        # Check Program Files
        base_dirs = [
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        ]
        
        for base_dir in base_dirs:
            # Look for Stata* folders (including StataNow)
            for stata_dir in glob.glob(os.path.join(base_dir, "Stata*")):
                # Look for executables
                for exe, edition in [
                    ("StataMP-64.exe", "mp"), ("StataMP.exe", "mp"),
                    ("StataSE-64.exe", "se"), ("StataSE.exe", "se"),
                    ("Stata-64.exe", "be"),   ("Stata.exe", "be")
                ]:
                    full_path = os.path.join(stata_dir, exe)
                    if os.path.exists(full_path):
                        candidates.append((full_path, edition))

    elif system == "Linux":
        # Check standard locations
        for binary, edition in [
            ("/usr/local/stata/stata-mp", "mp"),
            ("/usr/local/stata/stata-se", "se"),
            ("/usr/local/stata/stata", "be"),
            ("/usr/bin/stata", "be") # Assume BE if generic
        ]:
            if os.path.exists(binary):
                candidates.append((binary, edition))
    else:
        candidates = []

    # Prioritize MP > SE > BE
    # candidates list is populated in discovery order, but we can sort?
    # Our explicit lists prioritized MP already.
    # Just return first valid one.
    
    if candidates:
        return candidates[0]


    # Check candidates
    for path in candidates:
        if os.path.exists(path):
            return path
            
    # Raise error if not found to simplify downstream logic
    raise FileNotFoundError(
        "Could not automatically locate Stata. "
        "Please set the 'STATA_PATH' environment variable to your Stata executable."
    )
