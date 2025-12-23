import stata_setup
stata_setup.config("/Applications/StataNow/", "mp")
from pystata import stata
import tempfile
import os

print("=== Testing multiple concurrent logs ===\n")

# Create temp files for logs
log1_path = tempfile.mktemp(suffix='.smcl')
log2_path = tempfile.mktemp(suffix='.smcl')

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