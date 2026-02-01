import asyncio
import os
import sys
import time
from pathlib import Path

# Add src to sys.path
sys.path.append(os.path.join(os.getcwd(), "src"))

from mcp_stata.sessions import SessionManager

async def test_cancellation():
    manager = SessionManager()
    try:
        print("Starting session manager...")
        await manager.start()
        session = manager.get_session("default")
        print(f"Session started, PID: {session.pid}")

        # Set a scalar to verify data preservation
        print("Setting scalar x = 42...")
        await session.call("run_command", {"code": "scalar x = 42", "options": {"echo": False}})

        # Start a long-running CPU-bound command (loop)
        print("Starting long-running command (large loop)...")
        # Use run_command to run a loop that will produce lots of output and take time
        code = "forvalues i = 1/1000000 { \n display `i' \n }"
        
        async def log_receiver(text):
            # print(f"LOG: {text.strip()}") # Uncomment for debugging
            pass

        task = asyncio.create_task(session.call("run_command", {"code": code, "options": {"echo": True}}, notify_log=log_receiver))
        
        # Wait a bit for it to start
        print("Waiting 2 seconds before cancelling...")
        await asyncio.sleep(2)
        
        print("Cancelling task now...")
        start_cancel = time.time()
        task.cancel()
        
        interrupted_result = None
        try:
            interrupted_result = await task
            print("Task finished normally (should not happen)")
        except asyncio.CancelledError:
            duration = time.time() - start_cancel
            print(f"Task successfully cancelled in {duration:.2f}s")
            # The result is actually not returned by 'await task' when it raises CancelledError
            # but StataSession.call waited for it.
        
        # We can't easily get the interrupted_result here because of how asyncio.Task works,
        # but we can check if the session is alive.
        
        # Verify session is still alive and data is preserved
        print("Verifying session health and data preservation...")
        res = await session.call("run_command", {"code": "display x", "options": {"echo": False}})
        output = res.get("stdout", "") or res.get("smcl_output", "")
        # CommandResponse may return stdout or smcl_output depending on how it was built
        print(f"Output of 'display x': '{output.strip()}'")
        
        if "42" in output:
            print("SUCCESS: Data preserved and session responsive.")
        else:
            print(f"FAILURE: Data lost or session unresponsive. Output was: {output}")

    finally:
        print("Stopping all sessions...")
        await manager.stop_all()

if __name__ == "__main__":
    asyncio.run(test_cancellation())
