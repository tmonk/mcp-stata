
import os
import sys

import pytest
import stata_setup

# Skip entirely on non-Windows platforms since Stata COM setup is Windows-only.
pytestmark = [
    pytest.mark.skipif(sys.platform != "win32", reason="Stata setup test runs only on Windows"),
    pytest.mark.requires_stata
]

stata_exec_path = r"C:\Program Files\StataNow19\StataSE-64.exe"
edition = "se"

try:
    print(f"Attempting to run stata_setup.config with path: {os.path.dirname(stata_exec_path)} and edition: {edition}")
    stata_setup.config(os.path.dirname(stata_exec_path), edition)
    print("stata_setup.config succeeded")
except Exception as e:
    print(f"stata_setup.config failed: {e}")
