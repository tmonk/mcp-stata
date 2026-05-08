cd "C:\mcp-stata"

uv tool uninstall mcp-stata  # optional, if you previously installed it
uv pip install -e .

@'
import asyncio
import json
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PREFERRED_TOOL = "get_graph_list"
FALLBACK_TOOL = "list_graphs"  # tool name in tmonk/mcp-stata

def _print_calltool_content(result) -> None:
    # result.content is typically a list of MCP content blocks (often TextContent)
    if not getattr(result, "content", None):
        print("(no content returned)")
        return

    for block in result.content:
        text = getattr(block, "text", None)
        if text is None:
            print(str(block))
            continue

        # Pretty-print JSON if it looks like JSON
        s = text.strip()
        if (s.startswith("{}") and s.endswith("{}")) or (s.startswith("[") and s.endswith("]")):
            try:
                print(json.dumps(json.loads(s), indent=2))
                continue
            except Exception:
                pass
        print(text)

async def main() -> None:
    # This launches the MCP server over stdio.
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "mcp_stata.server"],
        env=None,
    )

    async with AsyncExitStack() as stack:
        stdio, write = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(ClientSession(stdio, write))
        await session.initialize()

        # 1) List tools
        tools_resp = await session.list_tools()
        tools = tools_resp.tools
        print("\n=== Tools exposed by MCP server ===")
        for t in tools:
            desc = (t.description or "").strip()
            print(f"- {t.name}" + (f": {desc}" if desc else ""))

        tool_names = {t.name for t in tools}

        # 2) Call get_graph_list() (or fallback)
        tool_to_call = None
        if PREFERRED_TOOL in tool_names:
            tool_to_call = PREFERRED_TOOL
        elif FALLBACK_TOOL in tool_names:
            tool_to_call = FALLBACK_TOOL

        if tool_to_call is None:
            raise SystemExit(
                f"\nNeither '{PREFERRED_TOOL}' nor '{FALLBACK_TOOL}' was found. "
                f"Available tools: {sorted(tool_names)}"
            )

        print(f"\n=== Calling tool: {tool_to_call} ===")
        result = await session.call_tool(tool_to_call, {{}})
        _print_calltool_content(result)

if __name__ == "__main__":
    asyncio.run(main())
'@ | Set-Content -Encoding UTF8 ./scripts/mcp_list_tools_and_graphs.py

uv run python ./scripts/mcp_list_tools_and_graphs.py
