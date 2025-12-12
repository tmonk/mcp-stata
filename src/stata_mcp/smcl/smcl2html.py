"""Convert a SMCL file into Markdown.

Adapted from https://github.com/sergiocorreia/parse-smcl (MIT). Simplified into
a single module geared toward MCP, emitting Markdown by default.
"""

import os
import re


def expand_includes(lines, adopath):
    """Expand INCLUDE directives if ado path is available."""
    if not adopath:
        return lines
    includes = [(i, line[13:].strip()) for (i, line) in enumerate(lines) if line.startswith("INCLUDE help ")]
    if os.path.exists(adopath):
        for i, cmd in reversed(includes):
            fn = os.path.join(adopath, cmd[0], cmd if cmd.endswith(".ihlp") else cmd + ".ihlp")
            try:
                with open(fn, "r", encoding="utf-8") as f:
                    content = f.readlines()
            except FileNotFoundError:
                continue
            if content and content[0].startswith("{* *! version"):
                content.pop(0)
            lines[i:i+1] = content
    return lines


def _inline_to_markdown(text: str) -> str:
    """Convert common inline SMCL directives to Markdown."""

    def repl(match: re.Match) -> str:
        tag = match.group(1).lower()
        content = match.group(2) or ""
        if tag in ("bf", "strong"):
            return f"**{content}**"
        if tag in ("it", "em"):
            return f"*{content}*"
        if tag in ("cmd", "cmdab", "code", "inp", "input", "res", "err", "txt"):
            return f"`{content}`"
        return content

    text = re.sub(r"\{([a-zA-Z0-9_]+):([^}]*)\}", repl, text)
    text = re.sub(r"\{[^}]*\}", "", text)
    return text


def smcl_to_markdown(smcl_text: str, adopath: str = None, current_file: str = "help") -> str:
    """Convert SMCL text to lightweight Markdown suitable for LLM consumption."""
    if not smcl_text:
        return ""

    lines = smcl_text.splitlines()
    if lines and lines[0].strip() == "{smcl}":
        lines = lines[1:]

    lines = expand_includes(lines, adopath)

    title = None
    body_parts = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("{title:"):
            title = line[len("{title:") :].rstrip("}")
            continue
        # Paragraph markers
        line = line.replace("{p_end}", "")
        line = re.sub(r"\{p[^}]*\}", "", line)
        body_parts.append(_inline_to_markdown(line))

    md_parts = [f"# Help for {current_file}"]
    if title:
        md_parts.append(f"\n## {title}\n")
    md_parts.append("\n".join(part for part in body_parts if part).strip())

    return "\n\n".join(part for part in md_parts if part).strip() + "\n"
