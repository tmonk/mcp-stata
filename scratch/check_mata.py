import asyncio
import os
import sys

sys.path.append(os.path.join(os.getcwd(), "src"))

async def main():
    from mcp_stata.server import session_manager
    s = await session_manager.get_or_create_session('test')
    with open('src/mcp_stata/statest/statest.mata') as f:
        code = f.read()
    res = await s.call('run_command_structured', {'code': code})
    print("STDOUT:")
    print(res.get('stdout'))
    print("STDERR:")
    print(res.get('stderr'))
    await session_manager.stop_all()

if __name__ == "__main__":
    asyncio.run(main())
