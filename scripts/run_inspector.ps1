cd "C:\mcp-stata"
uv tool uninstall mcp-stata  # optional, if you previously installed it
uv tool install --editable .
npx @modelcontextprotocol/inspector uvx mcp-stata