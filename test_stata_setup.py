
import stata_setup
import os

stata_exec_path = "C:\Program Files\StataNow19\StataSE-64.exe"
edition = "se"

try:
    print(f"Attempting to run stata_setup.config with path: {os.path.dirname(stata_exec_path)} and edition: {edition}")
    stata_setup.config(os.path.dirname(stata_exec_path), edition)
    print("stata_setup.config succeeded")
except Exception as e:
    print(f"stata_setup.config failed: {e}")
