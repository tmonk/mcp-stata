# MCP compatibility notes

## Structured tools (`structured_output=True`)

mcp-stata tools return Pydantic models such as `ToolEnvelope`. On the MCP wire, that yields:

- **`structuredContent`**: JSON object validated against the tool `outputSchema`.
- **`content`**: a list of content blocks. FastMCP historically also placed a **duplicate** JSON serialization of the same payload in a `text` block (often pretty-printed).

Duplicate text wastes tokens and vertical space when the host renders both channels.

### Server-side behavior (mcp-stata patch)

After `FastMCP(...)` startup, mcp-stata patches FastMCP so structured tools default to:

- **`structuredContent` unchanged**
- **`content`**: empty (`[]`) — no duplicate JSON string

Override with environment variable:

| `MCP_STATA_STRUCTURED_COMPANION_TEXT` | Behavior |
| ------------------------------------- | -------- |
| unset or `omit` (default)             | Empty `content`; use `structuredContent` for data |
| `compact`                             | Retain duplicate JSON text alongside `structuredContent`, serialized as **compact** JSON (single line) |

Hosts vary: some UIs emphasize `content[].text`, others surface `structuredContent`. If a client misbehaves with empty `content`, set `MCP_STATA_STRUCTURED_COMPANION_TEXT=compact` and retry.

### Not the same as `as_json=True`

Tool parameters such as `as_json=True` (where applicable) change **server-side tool arguments / alternate response shaping** for specific tools. That is unrelated to the MCP-level duplication between `structuredContent` and unstructured `content` text blocks.

## References

- GitHub [#53](https://github.com/tmonk/mcp-stata/issues/53): compact companion JSON (pretty-print → compact).
- GitHub [#55](https://github.com/tmonk/mcp-stata/issues/55): omit duplicate companion JSON by default.
