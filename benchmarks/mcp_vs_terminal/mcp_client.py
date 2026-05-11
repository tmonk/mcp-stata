import asyncio
import os
import sys
from typing import Any, Dict, List, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPStataClient:
    def __init__(self, server_path: str, use_local: bool = False):
        self.server_path = server_path
        self.use_local = use_local
        self.session: Optional[ClientSession] = None
        self._exit_stack = None
        self._client = None

    async def __aenter__(self):
        env = os.environ.copy()
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        env["PYTHONPATH"] = os.path.join(root_dir, "src")
        
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_stata.server"],
            env=env
        )
        
        self._client = stdio_client(server_params)
        read, write = await self._client.__aenter__()
        self.session = ClientSession(read, write)
        await self.session.__aenter__()
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.__aexit__(exc_type, exc_val, exc_tb)
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def get_tools(self) -> List[Dict[str, Any]]:
        if not self.session:
            raise RuntimeError("Session not initialized")
        result = await self.session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        if not self.session:
            raise RuntimeError("Session not initialized")
        result = await self.session.call_tool(name, arguments)
        # Result content is usually a list of TextContent
        return "\n".join([c.text for c in result.content if hasattr(c, "text")])

async def test_mcp():
    async with MCPStataClient(".") as client:
        tools = await client.get_tools()
        print(f"Connected. Found {len(tools)} tools.")
        res = await client.call_tool("stata_run", {"code": "display 2+2"})
        print(f"Result: {res}")

if __name__ == "__main__":
    asyncio.run(test_mcp())
