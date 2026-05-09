from __future__ import annotations
import asyncio
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from mcp_stata.sessions import SessionManager

async def test_multi_sessions():
    manager = SessionManager()
    try:
        print("Starting session manager...")
        await manager.start()
        
        print("Attempting to create session 's2'...")
        s1 = manager.get_session("default")
        s2 = await manager.get_or_create_session("s2")
        
        print(f"Session default PID: {s1.pid}")
        print(f"Session s2 PID: {s2.pid}")
        
        if s1.pid == s2.pid:
            print("FAILURE: Sessions share the same PID!")
            return
        
        print("\nDefining variable 'x = 10' in default session...")
        res_define1 = await s1.call("run_command", {"code": "scalar x = 10", "options": {"echo": True}})
        # print(f"Define 1 output: {res_define1.get('smcl_output')}")
        
        print("Defining variable 'x = 20' in s2 session...")
        res_define2 = await s2.call("run_command", {"code": "scalar x = 20", "options": {"echo": True}})
        # print(f"Define 2 output: {res_define2.get('smcl_output')}")
        
        print("\nChecking value of 'x' in default session...")
        res1 = await s1.call("run_command", {"code": "display x", "options": {"echo": True}})
        out1 = res1.get('smcl_output', '')
        print(f"Default session output contains '10': {'10' in out1}")
        if '10' not in out1:
            print(f"FULL SMCL OUTPUT 1:\n{out1}")
        
        print("Checking value of 'x' in s2 session...")
        res2 = await s2.call("run_command", {"code": "display x", "options": {"echo": True}})
        out2 = res2.get('smcl_output', '')
        print(f"s2 session output contains '20': {'20' in out2}")
        if '20' not in out2:
            print(f"FULL SMCL OUTPUT 2:\n{out2}")
        
        if "10" in out1 and "20" in out2:
            print("\nSUCCESS: Sessions are properly isolated!")
        else:
            print("\nFAILURE: Session data leakage detected or values missing.")
            
        print("\nListing sessions:")
        for s in manager.list_sessions():
            print(f" - {s.id}: {s.status} (PID: {s.pid})")

    finally:
        print("\nStopping all sessions...")
        await manager.stop_all()

if __name__ == "__main__":
    asyncio.run(test_multi_sessions())
