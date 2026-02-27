"""Convert a SMCL file into Markdown.

Handles the full structure of Stata .sthlp files including:
- Multiple title sections (## headings)
- Syntax option tables (synopt) → Markdown tables
- Dialog tab subsections (dlgtab/syntab) → ### headings
- Paragraph types (pstd, phang, phang2) → prose paragraphs
- Code examples (phang2 + cmd:.xxx) → ```stata blocks
- Inline markup (bf, it, cmd, opt, etc.)
- Line continuations ({...})
- INCLUDE help expansion
"""

import os
import re


# ---------------------------------------------------------------------------
# Structural/navigation tags stripped from lines (not whole-line skips)
# ---------------------------------------------------------------------------

# Tags that are structural boilerplate - removed from lines before processing.
# This handles the case where {synoptset}{...} continuation merges with a
# meaningful next line like {p2col ...}.
_STRUCTURAL_TAG_RE = re.compile(
    r"\{(?:"
    r"viewerdialog|vieweralsosee|viewerjumpto|findalias"
    r"|p2colset|p2colreset"
    r"|synoptset|synopthdr|synoptline"
    r"|marker"
    r")[^}]*\}"
)


# ---------------------------------------------------------------------------
# Inline SMCL tag → Markdown
# ---------------------------------------------------------------------------

def _inline_to_markdown(text: str) -> str:
    """Convert SMCL inline tags to Markdown equivalents."""

    # Browse links: {browse "URL":TEXT} → [TEXT](URL), {browse "URL"} → URL
    def _browse(m: re.Match) -> str:
        url, label = m.group(1), (m.group(2) or "").strip()
        return f"[{label}]({url})" if label else url

    text = re.sub(r'\{browse\s+"([^"]+)":([^}]*)\}', _browse, text)
    text = re.sub(r'\{browse\s+"([^"]+)"\}', lambda m: m.group(1), text)

    def _tag_colon(m: re.Match) -> str:
        """Handle {tag:content} form."""
        tag = m.group(1).lower()
        content = (m.group(2) or "").strip()
        if tag in ("bf", "strong"):
            return f"**{content}**" if content else ""
        if tag in ("it", "em"):
            return f"*{content}*" if content else ""
        if tag in ("cmd", "code", "inp", "input", "res", "err", "txt"):
            return f"`{content}`" if content else ""
        if tag in ("cmdab", "opt", "opth"):
            # {opt l:evel(#)} → `level(#)` — join abbreviation parts
            if ":" in content:
                pre, post = content.split(":", 1)
                content = pre + post
            return f"`{content}`" if content else ""
        if tag == "help":
            # {help topic:label} → label
            if ":" in content:
                return content.split(":", 1)[1].strip()
            return content
        if tag == "manhelp":
            # {manhelp cmd SECTION:label} → label; {manhelp cmd SECTION} → cmd
            if ":" in content:
                return content.split(":", 1)[1].strip()
            parts = content.split()
            return parts[0] if parts else content
        if tag in ("manlink", "mansection"):
            # {manlink SECTION CMD} → CMD
            parts = content.split()
            return parts[-1] if len(parts) > 1 else content
        # Unknown tagged content: return just the content
        return content

    def _tag_space(m: re.Match) -> str:
        """Handle {tag content} space-separated form."""
        tag = m.group(1).lower()
        content = (m.group(2) or "").strip()
        if tag in ("help",):
            return content
        if tag in ("helpb",):
            return f"`{content}`"
        if tag in ("opt", "opth"):
            # Join abbreviation colon: l:evel(#) → level(#)
            if ":" in content:
                pre, post = content.split(":", 1)
                content = pre + post
            return f"`{content}`"
        if tag in ("bf", "strong"):
            return f"**{content}**"
        if tag in ("it", "em"):
            return f"*{content}*"
        if tag in ("cmd", "cmdab"):
            return f"`{content}`"
        if tag == "manhelp":
            # {manhelp cmd SECTION:label} → label; {manhelp cmd SECTION} → cmd
            if ":" in content:
                return content.split(":", 1)[1].strip()
            parts = content.split()
            return parts[0] if parts else content
        if tag in ("manlink", "mansection"):
            # {manlink SECTION CMD} → CMD
            parts = content.split()
            return parts[-1] if len(parts) > 1 else content
        # Structural space-form tags: discard content
        return ""

    def _apply_once(t: str) -> str:
        t = re.sub(r'\{browse\s+"([^"]+)":([^}]*)\}', _browse, t)
        t = re.sub(r'\{browse\s+"([^"]+)"\}', lambda m: m.group(1), t)
        t = re.sub(r"\{([a-zA-Z0-9_]+):([^}]*)\}", _tag_colon, t)
        t = re.sub(r"\{([a-zA-Z0-9_]+)\s+([^}]+)\}", _tag_space, t)
        t = re.sub(r"\{[^}]*\}", "", t)
        return t

    # Two passes: second pass resolves any residue from nested tags
    text = _apply_once(text)
    if "{" in text:
        text = _apply_once(text)
    # Collapse multiple spaces
    text = re.sub(r"  +", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Pre-processing helpers
# ---------------------------------------------------------------------------

def _join_continuations(lines: list) -> list:
    """Merge lines ending with {..} (SMCL line continuation marker)."""
    result = []
    buf = ""
    for raw in lines:
        stripped = raw.rstrip()
        if stripped.endswith("{...}"):
            buf += stripped[:-5]
        else:
            buf += stripped
            result.append(buf)
            buf = ""
    if buf:
        result.append(buf)
    return result


def expand_includes(lines: list, adopath: str) -> list:
    """Expand INCLUDE help directives using the given ado path."""
    if not adopath or not os.path.exists(adopath):
        return [l for l in lines if not l.strip().startswith("INCLUDE ")]
    includes = [
        (i, line.strip()[13:].strip())
        for i, line in enumerate(lines)
        if line.strip().startswith("INCLUDE help ")
    ]
    for idx, cmd in reversed(includes):
        fn = os.path.join(
            adopath, cmd[0],
            cmd if cmd.endswith(".ihlp") else cmd + ".ihlp",
        )
        try:
            with open(fn, "r", encoding="utf-8") as f:
                content = [l.rstrip() for l in f.readlines()]
        except FileNotFoundError:
            del lines[idx]
            continue
        if content and content[0].startswith("{* *! version"):
            content.pop(0)
        lines[idx : idx + 1] = content
    return lines


# ---------------------------------------------------------------------------
# Synopt / p2col table entry parsing
# ---------------------------------------------------------------------------

def _parse_synopt_entry(stripped: str) -> tuple | None:
    """Parse a {synopt:...} or {p2coldent:...} line.

    Returns (option_markdown, remaining_description_text) or None.
    """
    # {synopt :{opt xxx}}DESC  or  {synopt:{opth vce(...)}}DESC
    # Note: space before colon is valid SMCL: {synopt :content}
    m = re.match(r"\{synopt\s*:((?:\{[^}]*\}|[^}])*)\}(.*)", stripped)
    if m:
        return (_inline_to_markdown(m.group(1)), m.group(2))
    # {p2coldent:+ {opt xxx}}DESC  (StataNow + feature marker)
    # Use nested-brace-aware pattern: (?:\{[^}]*\}|[^}])*
    m = re.match(r"\{p2coldent:\+?\s*((?:\{[^}]*\}|[^}])*)\}(.*)", stripped)
    if m:
        return (_inline_to_markdown(m.group(1).strip()), m.group(2))
    return None


def _collect_paragraph(lines: list, start_idx: int, initial: str) -> tuple:
    """Collect text until {p_end} or a blank line (after content) is found.

    Stops at:
    - An explicit {p_end} tag
    - A blank line after content has been accumulated (implicit paragraph end)

    Returns (full_content_str, next_line_index).
    """
    content = initial
    idx = start_idx
    seen_content = bool(content.strip())
    while True:
        if "{p_end}" in content:
            content = re.sub(r"\{p_end\}.*", "", content)
            break
        if idx >= len(lines):
            break
        next_line = lines[idx].strip()
        if not next_line:  # blank line
            if seen_content:
                break  # end of paragraph — leave idx pointing at blank
            idx += 1  # skip leading blank before content
            continue
        idx += 1
        content = (content + " " + next_line).strip()
        seen_content = True
    return content.strip(), idx


# ---------------------------------------------------------------------------
# Main converter
# ---------------------------------------------------------------------------

def smcl_to_markdown(smcl_text: str, adopath: str = None, current_file: str = "help") -> str:
    """Convert SMCL text to structured Markdown.

    Produces:
    - ## section headings for each {title:...}
    - ### subsection headings for {dlgtab:} / {syntab:}
    - Markdown tables for {synopt:} option entries
    - Prose paragraphs for {pstd}/{phang}/{phang2}
    - ```stata code blocks for inline command examples
    - Bold/italic/code for inline markup
    """
    if not smcl_text:
        return ""

    lines = smcl_text.splitlines()

    # Strip {smcl} header
    if lines and lines[0].strip() == "{smcl}":
        lines = lines[1:]
    # Strip version comment line (e.g. {* *! version 1.0 ...})
    if lines and re.match(r"^\{[*]", lines[0].strip()):
        lines = lines[1:]

    # Merge SMCL continuation lines
    lines = _join_continuations(lines)

    # Expand or remove INCLUDE directives
    if adopath:
        lines = expand_includes(lines, adopath)
    else:
        lines = [l for l in lines if not l.strip().startswith("INCLUDE ")]

    out = [f"# Help for {current_file}\n"]

    # Pending synopt table rows — flushed when a section boundary is hit
    synopt_rows: list = []

    def flush_synopt() -> None:
        if not synopt_rows:
            return
        out.append("")
        out.append("| Option | Description |")
        out.append("|--------|-------------|")
        for opt, desc in synopt_rows:
            out.append(f"| {opt.replace('|', '\\|')} | {desc.replace('|', '\\|')} |")
        out.append("")
        synopt_rows.clear()

    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        i += 1

        if not stripped:
            continue

        # Skip pure SMCL comment lines
        if re.match(r"^\{[*]", stripped):
            continue

        # Remove structural boilerplate tags from the line (handles cases where
        # {synoptset}{...} continuation has merged with a meaningful next line)
        stripped = _STRUCTURAL_TAG_RE.sub("", stripped).strip()
        if not stripped:
            continue

        # ── Section title → ## heading ──────────────────────────────────
        title_m = re.search(r"\{title:(.+?)\}", stripped)
        if title_m:
            flush_synopt()
            out.append(f"\n## {title_m.group(1).strip()}\n")
            continue

        # ── Dialog / syntax tab → ### subsection ────────────────────────
        tab_m = re.search(r"\{(?:dlgtab|syntab):(.+?)\}", stripped)
        if tab_m:
            flush_synopt()
            out.append(f"\n### {tab_m.group(1).strip()}\n")
            continue

        # ── Horizontal rule ──────────────────────────────────────────────
        if re.match(r"\s*\{hline(?:\s+\d+)?\}\s*$", stripped):
            flush_synopt()
            out.append("\n---\n")
            continue

        # ── p2col intro title lines — skip (decorative navigation header) ──
        # {p2col:{bf:...}} or {p2col:}(...) appear only at the top of help
        # files as a manual reference, not as content.
        if re.match(r"\{p2col:\{", stripped) or re.match(r"\{p2col:\}", stripped):
            continue

        # ── p2col section header (e.g. {p2col 5 23 26 2: Scalars}{p_end}) ──
        p2sec_m = re.match(r"\{p2col[^:]*:\s*(.+?)\}\{p_end\}", stripped)
        if p2sec_m:
            flush_synopt()
            out.append(f"\n**{_inline_to_markdown(p2sec_m.group(1))}**\n")
            continue

        # ── Synopt / p2coldent table entry ───────────────────────────────
        synopt_result = _parse_synopt_entry(stripped)
        if synopt_result:
            opt_md, remainder = synopt_result
            desc_content, i = _collect_paragraph(lines, i, remainder)
            desc_md = _inline_to_markdown(desc_content)
            synopt_rows.append((opt_md, desc_md))
            continue

        # ── Paragraph types ──────────────────────────────────────────────
        par_m = re.match(
            r"\{(?:pstd|phang2?|pin\d*|p\d*std|p\b[^}]*)\}(.*)",
            stripped, re.IGNORECASE,
        )
        if par_m:
            flush_synopt()
            content, i = _collect_paragraph(lines, i, par_m.group(1))
            if content:
                # Detect code example line: entire content is {cmd:. xxx}
                code_m = re.match(r"^\{cmd:\.\s*(.*?)\}$", content.strip())
                if code_m:
                    out.append(f"\n```stata\n. {code_m.group(1).strip()}\n```\n")
                else:
                    rendered = _inline_to_markdown(content)
                    if rendered:
                        out.append(f"\n{rendered}\n")
            continue

        # ── Bare code-example line: {cmd:. xxx}{p_end} ──────────────────
        code_bare_m = re.match(r"^\{cmd:\.\s*(.*?)\}(?:\{p_end\})?$", stripped)
        if code_bare_m:
            flush_synopt()
            out.append(f"\n```stata\n. {code_bare_m.group(1).strip()}\n```\n")
            continue

        # ── Plain text (after inline conversion) ─────────────────────────
        flush_synopt()
        rendered = _inline_to_markdown(stripped)
        if rendered:
            out.append(rendered)

    flush_synopt()
    return "\n".join(out).strip() + "\n"
