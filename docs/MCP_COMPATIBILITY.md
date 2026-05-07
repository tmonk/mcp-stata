# MCP Compatibility

The server targets the current FastMCP feature set used by Claude Code, Codex, and Gemini-class MCP clients.

## Supported Surfaces

- Structured tool output via `ToolEnvelope`
- Prompts via `@mcp.prompt`
- Static and templated resources via `@mcp.resource`
- Stdio transport by default

## Client Notes

- Claude/Codex benefit most from the structured tool envelopes and session/project resources.
- Gemini picks up the shared MCP server config plus the repository `AGENTS.md`.
- Legacy direct Python callers can still request JSON-string responses with `as_json=True`.
