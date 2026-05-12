# Log Size Mitigation: The Core Constraint for Stata Skills

## Executive Summary

Stata logs are the single biggest token-efficiency threat in any Stata↔agent integration. A routine 5 MB SMCL log from a bootstrap or simulation burns **~920,000 tokens** after cleaning. The error that actually matters is usually **< 100 tokens** and buried at the end. The current MCP server mitigates this with server-side truncation, backward error scanning, and paginated log reading. **Any migration away from MCP must replicate and improve these mitigations.**

---

## 1. Measured Log Sizes

Scripts in this directory (`generate_*.py`, `measure_tokens.py`) produce the following benchmarks on synthetic but realistic SMCL output.

| Scenario | File Size | Raw Tokens | Cleaned Tokens | Error Context | Tail-1K |
|----------|-----------|-----------:|---------------:|--------------:|--------:|
| Small data prep (50 vars) | 3.4 KB | 874 | 630 | 110 | 1,000 |
| Bootstrap (1,000 reps) | 16.0 KB | 4,101 | 1,518 | 170 | 1,000 |
| Simulation (5,000 reps) | 8.4 KB | 2,159 | 1,702 | 102 | 1,000 |
| Mixed workflow (×10) | 155.5 KB | 39,812 | 23,798 | 41 | 1,000 |
| Simulation (×10) | 75.2 KB | 19,260 | 15,427 | 102 | 1,000 |
| **Extreme: 5 MB generated** | **5,120 KB** | **1,310,756** | **923,122** | **64** | **1,000** |

**Key takeaway:** Even a routine long-running job can produce logs that exceed most model context windows. The useful signal (the error, or the final regression table) is a tiny fraction of the total.

---

## 2. What the MCP Server Does Today

### 2.1 Output Truncation

- **`_truncate_text(stdout, limit=5000)`**: hard caps at ~5,000 characters (~1,250 tokens) in the primary tool response.
- **`max_output_lines`**: optionally caps by line count instead of characters.
- **Result**: the agent never sees the full log inline unless it explicitly calls `stata_read_log`.

### 2.2 Error Extraction

When `rc != 0`, the server does **not** return the truncated tail. It returns:

1. **`_extract_error_from_smcl()`** (Python) or **`fast_scan_log()`** (Rust native): scan backwards from the end of the SMCL log for `{err}` tags.
2. **`_read_log_backwards_until_error()`**: chunked backward read (avoids loading a 5 MB file into memory).
3. Result: an `error` envelope with the specific error message + a small context window (default ~15 lines).

**Measured performance of backward scan:**

| Log Size | Naive Scan | Chunked Scan | Context Size |
|----------|-----------:|-------------:|-------------:|
| 2.2 KB | 0.006 ms | 0.006 ms | ~84 tokens |
| 155 KB | 0.178 ms | 0.020 ms | ~84 tokens |
| 5 MB | 6.557 ms | **0.119 ms** | ~126 tokens |

### 2.3 Paginated Log Access

- **`stata_read_log(path, offset, max_bytes=65536)`**: read a 64 KB chunk.
- **`stata_read_log(path, query, ...)`**: search with regex, return match objects + `next_offset` for pagination.
- **Default `max_bytes` for search**: 256 KB; safety cap: 5 MB.

This lets the agent "page through" a giant log without ever loading it whole.

---

## 3. Migration Strategy: CLI-First Log Mitigation

In the skill/CLI architecture, the daemon + CLI must enforce the same constraints. The difference is that instead of MCP envelopes, we emit structured CLI output.

### 3.1 Default CLI Behavior

```bash
$ stata run --echo "bootstrap, reps(5000): reg y x"
```

**Default output (success):**
```
[stata] Command completed successfully (rc=0)
[stata] Output truncated to last 1,000 tokens. Full log: ~/.cache/mcp-stata/logs/session_20260512_143201.smcl

... (last ~1,000 tokens of cleaned output) ...
```

**Default output (failure):**
```
[stata] Command failed (rc=111)
[stata] Error: variable z_nonexistent not found
[stata] Context (last 20 lines):
  . regress y z_nonexistent
  variable z_nonexistent not found
  r(111);
[stata] Full log: ~/.cache/mcp-stata/logs/session_20260512_143201.smcl
```

**Design principle:** *Never* return the full log by default. Always return one of:
1. Truncated tail (success)
2. Extracted error + context (failure)
3. A file path to the full log (both cases)

### 3.2 New CLI Subcommands for Log Management

These replace the MCP `stata_read_log` tool.

```bash
# Tail the log (last N lines or N bytes)
stata log tail [--session NAME] [--lines 50] [--bytes 65536]

# Search the log with regex (paginated)
stata log search <pattern> [--session NAME] [--offset 0] [--max-bytes 262144]

# Extract just the error context (fast backward scan)
stata log errors [--session NAME] [--context-lines 20]

# Get full log path for agent to read directly
stata log path [--session NAME]
```

**Why separate subcommands?**
- Each skill loads only the subcommand it needs.
- The agent composes them naturally: `stata run ...` → (fails) → `stata log errors`.
- Token cost is explicit: `stata log tail --lines 50` = ~50–200 tokens, predictable.

### 3.3 Log File Lifecycle

| Aspect | Rule |
|--------|------|
| **Location** | `~/.cache/mcp-stata/logs/<session_name>_<timestamp>.smcl` |
| **Persistence** | Persistent for the daemon lifetime; optionally archived until `--max-logs` reached. |
| **Rotation** | New log file per `stata run --file` or per N commands; prevents single-file bloat. |
| **Cleanup** | Daemon auto-deletes logs older than `--log-ttl` (default: 24h). |
| **Agent access** | The agent can `read` the log file directly via the `read` tool once it has the path. |

### 3.4 Streaming vs. Batch

For background tasks (`stata run --background`), the daemon streams progress but **does not stream the full log**. Instead it emits:

```json
{"event": "progress", "task_id": "...", "percent": 45}
{"event": "log_path", "task_id": "...", "path": ".../job_001.smcl"}
```

The agent polls `stata task status --task-id ...` and only fetches log chunks on demand.

---

## 4. Skill-Level Instructions

Skills must teach the agent *how* to handle log size, not just *what* commands exist.

### 4.1 `stata-run` Skill (Revised)

```markdown
## Running Stata Code

### Default execution

```bash
stata run --echo "reg price mpg rep78"
```

**If it succeeds:** The output is automatically truncated to the last ~1,000 tokens. 
If you need the full output, read the log file path printed at the bottom.

**If it fails:** The CLI automatically extracts the error and shows only the error 
context (~20 lines). Do NOT ask the user to read the full log unless the error 
context is insufficient.

### When output is huge

If you expect very large output (e.g., `list` on many observations, `tabulate` 
with many levels), the output may be truncated aggressively. Instead of inline 
execution, save to a file inside Stata:

```bash
stata run --echo "reg price mpg; estimates save ./results.ster"
```

Then inspect results with `stata results` or read the file directly.

### Background tasks

```bash
stata run --background --echo --file ./long_job.do
stata task status --task-id <id> --wait --timeout 300
```

After completion, check errors first:

```bash
stata log errors --task-id <id>
```

Only if the error context is unclear, tail the log:

```bash
stata log tail --task-id <id> --lines 100
```
```

### 4.2 `stata-log` Skill (Revised)

```markdown
## Reading Stata Logs

Stata logs can be enormous (100K+ tokens). Never `read` a log file in full. 
Use targeted CLI subcommands.

### Tail the end of a log

```bash
stata log tail --lines 50
```

### Search for a pattern

```bash
stata log search "r(198)"
```

Returns matches with offsets. Continue paging:

```bash
stata log search "r(198)" --offset <next_offset>
```

### Extract errors only

```bash
stata log errors
```

This performs a fast backward scan and returns only the `{err}` context. 
Use this FIRST whenever a command fails.

### Read a specific chunk

```bash
stata log read --offset 1048576 --bytes 65536
```
```

---

## 5. Implementation Checklist

### Daemon (`daemon.py`)

- [ ] Every `run_command` result must include `log_path`.
- [ ] On failure (`rc != 0`), daemon runs backward error scan before returning.
- [ ] Daemon never sends the full log content in the NDJSON response; only tail or error context.
- [ ] Support `max_output_tokens` parameter in run requests (default: 1,000 tokens equivalent).
- [ ] Maintain persistent SMCL log per session with rotation.

### CLI (`cli.py`)

- [ ] `stata run` prints a clear truncation notice: `[truncated: showing last N tokens; full log at <path>]`.
- [ ] `stata run` on failure prints the error context first, then the log path.
- [ ] `stata log tail` supports `--lines` and `--bytes`.
- [ ] `stata log search` supports regex, `--offset`, `--max-bytes`, and returns `next_offset`.
- [ ] `stata log errors` performs backward scan (reuse `fast_scan_log` or Python equivalent).
- [ ] `stata log path` simply prints the current session's log path.

### Skills

- [ ] Every skill that invokes `stata run` must remind the agent: "If this fails, run `stata log errors` first."
- [ ] `stata-log` skill must be discoverable and loaded whenever the agent wants to inspect output.
- [ ] Skills must explicitly warn against reading full log files into context.

### Testing

- [ ] Benchmark: 5 MB log → `stata log errors` must return in < 5 ms and be < 200 tokens.
- [ ] Benchmark: `stata log tail --lines 50` must be < 250 tokens regardless of log size.
- [ ] Test: agent workflow that runs 1,000 regressions, then extracts only the last table and any errors.

---

## 6. Comparison: MCP vs. Skill/CLI Token Cost

| Workflow Step | MCP Tokens | Skill/CLI Tokens | Notes |
|---------------|-----------:|-----------------:|-------|
| Load 20 tool schemas | ~10,000 | **0** | Skills are markdown, not schemas |
| Run command (success) | ~1,250 (truncated) | ~1,000 (truncated) | Comparable |
| Run command (failure) | ~200 (error context) | ~150 (error context) | Comparable |
| Read full log page | ~16,000 (64 KB) | ~16,000 (64 KB) | Identical; agent chooses when |
| Search log | ~4,000 (matches) | ~4,000 (matches) | Identical |
| **Net per session** | **~10,000 overhead** | **~400 (base skill)** | **25× reduction** |

The log-mitigation logic itself is almost identical between MCP and CLI. The win comes from eliminating the perpetual schema tax.
