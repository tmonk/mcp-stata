import sys
import stata_setup
stata_setup.config("/Applications/StataNow", "mp")
from pystata import stata
from sfi import Scalar, Macro

def get_rc():
    rc_c = None
    try:
        rc_c = Scalar.getValue("c(rc)")
    except Exception as e:
        rc_c = f"Error: {e}"
        
    rc_v = None
    try:
        stata.run("global _mcp_last_rc = _rc", echo=False)
        rc_v = Macro.getGlobal("_mcp_last_rc")
    except Exception as e:
        rc_v = f"Error: {e}"
        
    return rc_c, rc_v

print("--- Initial state ---")
print(f"RC (c, v): {get_rc()}")

print("\n--- Testing error 198 ---")
try:
    stata.run("error 198", echo=False)
except Exception:
    pass

print(f"RC (c, v) after error 198: {get_rc()}")

print("\n--- Testing capture error 111 ---")
stata.run("capture error 111", echo=False)
print(f"RC (c, v) after capture error 111: {get_rc()}")

print("\n--- Testing restore logic ---")
stata.run("capture error 198", echo=False)
prev_rc = get_rc()[0]
stata.run("display 1", echo=False)
print(f"RC before restore: {get_rc()}")
stata.run(f"capture error {int(float(prev_rc))}", echo=False)
print(f"RC after restore: {get_rc()}")
