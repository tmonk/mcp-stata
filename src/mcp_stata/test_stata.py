import stata_setup
stata_setup.config("/Applications/StataNow/", "mp")
from pystata import stata
import os
import uuid
from .utils import get_writable_temp_dir

print("=== Testing multiple concurrent logs ===\n")

# Create temp files for logs in a writable directory
temp_dir = get_writable_temp_dir()
log1_path = os.path.join(temp_dir, f"test_log1_{uuid.uuid4().hex[:8]}.smcl")
log2_path = os.path.join(temp_dir, f"test_log2_{uuid.uuid4().hex[:8]}.smcl")

stata.run("sysuse auto, clear")

try:
    # Start first (unnamed) log - simulating user's log
    print("1. Starting unnamed user log...")
    stata.run(f'log using "{log1_path}", replace smcl')
    
    # Start second (named) log - our capture log
    print("2. Starting named capture log...")
    stata.run(f'log using "{log2_path}", replace smcl name(_capture)')
    
    # Run a command - should go to both logs
    print("3. Running command...")
    stata.run("summarize price mpg")
    
    # Close named log first
    print("4. Closing named log...")
    stata.run("log close _capture")
    
    # Close unnamed log
    print("5. Closing unnamed log...")
    stata.run("log close")
    
    print("\n=== SUCCESS: Multiple concurrent logs work! ===\n")
    
    # Show contents
    print("--- User log contents (first 500 chars) ---")
    with open(log1_path, 'r') as f:
        print(f.read()[:500])
    
    print("\n--- Capture log contents (first 500 chars) ---")
    with open(log2_path, 'r') as f:
        print(f.read()[:500])

except Exception as e:
    print(f"\n=== FAILED: {e} ===\n")

finally:
    # Cleanup
    for p in [log1_path, log2_path]:
        if os.path.exists(p):
            os.unlink(p)