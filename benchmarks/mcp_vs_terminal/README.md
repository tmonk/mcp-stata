# Benchmark Prompt: mcp-stata vs Terminal Stata-SE

## Objective

Compare two approaches to AI-assisted Stata workflows on two dimensions:

1. **Token efficiency** — total input + output tokens consumed per task
2. **Error detection** — ability to find errors, number of round-trips required, and tokens consumed doing so

---

## Approaches Under Test

Both approaches run locally on the same machine using `gemini-3-flash-preview` via Google Antigravity. The model is held constant — the only variable is how Stata is accessed.


**A: mcp-stata**
`gemini-3-flash-preview` connected via the MCP server, configured in Antigravity's MCP server list (`mcp-stata`). Uses structured tools: `run_command`, `get_stored_results`, `find_in_log`, `describe`, `codebook`, etc. Returns JSON envelopes with `rc`, `stdout`, `stderr`, `line`, `snippet`.

**B: Terminal agent (stata-se)**
`gemini-3-flash-preview` connected to a local bash shell via Antigravity's tool-use interface (single `bash` tool). Interacts with Stata via `stata-se -b do file.do` or `stata-se -e "command"`. Reads output by parsing plain-text `.log` files or stdout. No structured error envelopes.

## Model & Pricing

**Model:** `gemini-3-flash-preview`
**Input token limit:** 1,048,576 | **Output token limit:** 65,536

| Tier | Input (text/image/video) | Output (incl. thinking) | Context caching |
|---|---|---|---|
| Free | Free | Free | Free |
| Paid (Standard) | $0.50 / 1M tokens | $3.00 / 1M tokens | $0.05 / 1M tokens + $1.00 / 1M tokens/hr storage |
| Paid (Batch) | $0.25 / 1M tokens | $1.50 / 1M tokens | — |
| Paid (Priority) | $0.90 / 1M tokens | $5.40 / 1M tokens | $0.09 / 1M tokens + $1.80 / 1M tokens/hr storage |

Use **Standard** tier for benchmark runs. Record estimated cost per task as `input_tokens / 1,000,000 × 0.50 + output_tokens / 1,000,000 × 3.00`.

*Pricing source: https://ai.google.dev/gemini-api/docs/pricing (May 2026)*

---

## Step 0 — Validate Token Counting

Since mcp-stata uses stdio transport and Antigravity does not expose per-turn token counts, token counting is done via a small Python harness that drives both approaches programmatically and reads `usageMetadata` directly from each Gemini API response.

### Harness setup

```python
import google.generativeai as genai
import json, subprocess, threading, os

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel("gemini-3-flash-preview")

def count_tokens_sanity_check():
    response = model.generate_content(
        'Respond with exactly this sentence and nothing else: '
        '"The quick brown fox jumps over the lazy dog."'
    )
    usage = response.usage_metadata
    print(f"Input tokens:  {usage.prompt_token_count}")
    print(f"Output tokens: {usage.candidates_token_count}")
    return usage
```

For **Approach A (mcp-stata)**, the harness connects to the mcp-stata stdio process using the MCP Python SDK (`mcp` package), converts tool results into Gemini function-call format, and passes them back to the model in a multi-turn loop — recording `usage_metadata` after each `generate_content` call.

For **Approach B (terminal)**, the harness exposes a single `bash` function tool, executes shell commands via `subprocess`, and similarly records `usage_metadata` per turn.

Both approaches use the same loop structure so token counts are directly comparable.

### Validation prompt

Send this single-turn prompt with no tools active:

> Respond with exactly the following sentence and nothing else: "The quick brown fox jumps over the lazy dog."

**Checks:**
1. `prompt_token_count` is between 20–30.
2. `candidates_token_count` is between 8–15.
3. Run twice in fresh sessions — counts are identical.

**Record:**

| Field | Value |
|---|---|
| Input tokens (run 1) | |
| Output tokens (run 1) | |
| Input tokens (run 2) | |
| Output tokens (run 2) | |
| Counts match across runs? | yes / no |

If counts differ across runs or are implausible, check that you are not using streaming mode (`stream=True`) — the final `usage_metadata` chunk is sometimes dropped. Use non-streaming for all benchmark runs.

---

## Tasks

Run each task independently under both approaches. Record tokens per turn and total.

### Task Set 1 — Token Efficiency Baseline

These tasks contain no deliberate errors. Measure total tokens to complete.

**T1.1 — Load and summarize**
> Load the built-in `auto` dataset, run `summarize price mpg weight`, and report the mean and standard deviation of each variable.

**T1.2 — Regression and stored results**
> Run `regress price mpg weight foreign`, then retrieve and report the coefficient on `mpg`, its standard error, and the model R-squared.

**T1.3 — Data inspection**
> Load `nlsw88`, describe the dataset structure, and produce a frequency table of `industry`.

**T1.4 — Graph export**
> Load `auto`, produce a scatter plot of `price` vs `mpg` with a fitted line, and export it as a PDF.

---

### Task Set 2 — Error Detection

Each task contains a deliberate error. Measure: (a) whether the error is caught, (b) turns to resolution, (c) total tokens.

**T2.1 — Syntax error**
```stata
sysuse auto
regres price mpg   // typo: "regres" not "regress"
```
> Run this code. Report what went wrong and fix it.

**T2.2 — Variable name error**
```stata
sysuse nlsw88
regress wage educaton experience  // typo: "educaton" not "education"
```
> Run this code. Identify the error and correct it.

**T2.3 — Logic error (wrong return code interpretation)**
```stata
sysuse auto
summarize price
display "Mean price is " r(mean)
display "Observations: " r(N)
// Then immediately after clearing:
clear
display r(mean)   // r() results lost after clear
```
> Run this sequence. Explain what happens at the final `display` and why.

**T2.4 — Do-file error buried in output**

Create a do-file with ~30 lines of valid code, with one error on line 22 (e.g., referencing a variable dropped earlier). Run it and identify the failing line and cause.

**T2.5 — Silent error (wrong result, no rc)**
```stata
sysuse auto
// Intent: regress price on mpg controlling for weight
// Actual: omits weight, results in omitted variable bias
regress price mpg
```
> The code runs without error. Using stored results and the codebook, identify that `weight` is a likely confounder and flag the potential issue.

---

### Task Set 3 — Structural Advantages

These tasks isolate specific capabilities where mcp-stata's architecture should produce the largest measurable gap.

**T3.1 — Large log navigation**

Create a do-file with 200 lines of valid code followed by a syntax error on line 163. Run it. Identify the failing line and error message.

*What to measure*: Terminal agent must read the entire `.log` file (or attempt to). mcp-stata uses `find_in_log` with a bounded context window. Record bytes/tokens of log content ingested by each approach before identifying the error.

**T3.2 — Context window longevity**

Run 20 sequential analysis tasks in a single conversation, each building on the prior state (load data → clean → reshape → merge → regress × 5 → post-estimation × 5 → export results). Do not start a new session between tasks.

*What to measure*: Cumulative input tokens across all 20 turns. Terminal approach accumulates verbose log text in context; mcp-stata returns compact JSON. Record whether either approach begins truncating context or losing state, and at which turn.

*Tasks to use*: T1.1, T1.2, T1.3, then 17 additional steps defined below:
1. `keep if price < 8000`
2. `generate log_price = log(price)`
3. `generate mpg_sq = mpg^2`
4. `label variable log_price "Log of price"`
5. `regress log_price mpg mpg_sq weight`
6. `predict yhat`
7. `predict resid, resid`
8. `summarize resid`
9. `correlate resid weight`
10. `regress log_price mpg weight foreign`
11. `margins foreign`
12. `test mpg = 0`
13. `regress log_price mpg weight rep78`
14. `margins rep78`
15. `tabulate rep78 foreign`
16. `regress log_price mpg if foreign == 0`
17. `regress log_price mpg if foreign == 1`

**T3.3 — Post-estimation chain**

```stata
sysuse nlsw88
regress wage education experience tenure
predict yhat
predict resid, resid
margins, dydx(education)
test education = experience
```

After each command, retrieve and report: the relevant `e()` or `r()` scalars (coefficients, margins, test statistics) without re-running any prior command.

*What to measure*: mcp-stata uses `get_stored_results` after each step. Terminal agent must re-parse the log or re-run commands if results are not in context. Count re-runs (if any) and total tokens.

**T3.4 — Graph iteration**

Load `auto`. Produce a scatter plot of `price` vs `mpg`. Then apply five sequential modifications:
1. Add a linear fit line
2. Change marker colour to navy
3. Add axis titles
4. Add a note citing the data source
5. Change the plot to a binned scatter (use `binscatter` or `twoway scatter` with jitter)

After each step, confirm the graph updated correctly before proceeding.

*What to measure*: Turns and tokens per iteration. Terminal approach requires explicit file export, path management, and re-reading per step. mcp-stata caches graphs automatically. Also record any steps where the terminal approach fails to confirm the update and proceeds incorrectly (correctness failure).

**T3.5 — Parallel sessions**

Run two independent analyses simultaneously within the same conversation:
- Session A: `sysuse auto` → `regress price mpg weight`
- Session B: `sysuse nlsw88` → `regress wage education experience`

Interleave the steps (A step 1, B step 1, A step 2, B step 2). At the end, retrieve `e(r2)` from each session independently.

*What to measure*: mcp-stata uses `session_id` natively. Terminal agent must manage separate do-files, log files, and state manually. Record tokens spent on session bookkeeping (file naming, log routing, state tracking) vs. actual analysis, and whether either session's results were contaminated by the other.

**T3.6 — Help-driven debugging**

```stata
sysuse nlsw88
margins industry, dydx(wage) atmeans
```

This command has incorrect syntax (`dydx` is not a valid option in this position for this use case). The agent must look up `margins` help, identify the correct syntax, and fix the command.

*What to measure*: mcp-stata uses `get_help("margins")` returning structured markdown. Terminal runs `stata-se -e "help margins"` and parses raw help output or falls back to general knowledge. Record tokens consumed by the help lookup and turns to correct fix.

---

## Measurement Protocol

For each task × approach, record:

| Field | Description |
|---|---|
| `approach` | `mcp` or `terminal` |
| `task_id` | e.g. `T1.1`, `T2.3` |
| `input_tokens` | Total tokens in all prompts + tool results sent to the model |
| `output_tokens` | Total tokens in all model responses |
| `turns` | Number of back-and-forth exchanges to complete the task |
| `error_detected` | (T2 only) `true/false` |
| `turns_to_detect` | (T2 only) Turns until error was identified |
| `tokens_to_detect` | (T2 only) Cumulative tokens at point of error identification |
| `resolution_correct` | Final answer/fix is correct: `true/false` |
| `log_bytes_ingested` | (T3.1 only) Bytes of log file read before error identified |
| `context_lost` | (T3.2 only) Turn at which context truncation or state loss occurred, or `none` |
| `reruns` | (T3.3 only) Commands re-executed to recover stored results |
| `correctness_failures` | (T3.4 only) Steps where agent proceeded without confirming graph update |
| `bookkeeping_tokens` | (T3.5 only) Tokens spent on session management vs. analysis (manually annotated) |
| `session_contaminated` | (T3.5 only) Whether one session's state affected the other: `true/false` |

Token counts are read from `response.usage_metadata.prompt_token_count` and `response.usage_metadata.candidates_token_count` after each `generate_content` call in the harness, then summed across all turns per task. Do not use estimates. Use non-streaming mode for all benchmark runs.

---

## Hypotheses to Test

- **H1**: mcp-stata uses fewer tokens per task because structured JSON tool responses are more compact than log file parsing.
- **H2**: mcp-stata detects errors in fewer turns because `rc`, `line`, and `snippet` fields surface the failure immediately, without log scanning.
- **H3**: Terminal approach requires more input tokens on error tasks because the agent must read and search raw `.log` files.
- **H4**: For silent errors (T2.5), neither approach has a structural advantage — both require domain reasoning.
- **H5**: Token cost of log ingestion scales with log file size for the terminal approach but is bounded for mcp-stata (T3.1). The gap should be roughly proportional to log length.
- **H6**: Cumulative input tokens diverge significantly after ~10 turns in T3.2, as verbose log text accumulates in the terminal approach's context.
- **H7**: Terminal approach requires at least one command re-run per post-estimation chain (T3.3) to recover `e()` results not retained in context.
- **H8**: mcp-stata completes each graph iteration in one turn; terminal approach requires at least two (run + read file) per step (T3.4).
- **H9**: Terminal approach spends measurably more tokens on session bookkeeping than analysis in T3.5.
- **H10**: `get_help` (T3.6) returns a more compact and directly navigable response than parsing raw Stata help output, reducing turns to correct fix.

---

## Reporting

Summarise results in a table:

| Task | mcp input tok | mcp output tok | mcp turns | terminal input tok | terminal output tok | terminal turns | notes |
|---|---|---|---|---|---|---|---|
| T1.1 | | | | | | | |
| T1.2 | | | | | | | |
| T1.3 | | | | | | | |
| T1.4 | | | | | | | |
| T2.1 | | | | | | | error detected? |
| T2.2 | | | | | | | error detected? |
| T2.3 | | | | | | | error detected? |
| T2.4 | | | | | | | error detected? |
| T2.5 | | | | | | | error detected? |
| T3.1 | | | | | | | log_bytes_ingested |
| T3.2 | | | | | | | context_lost at turn |
| T3.3 | | | | | | | reruns |
| T3.4 | | | | | | | correctness_failures |
| T3.5 | | | | | | | bookkeeping_tokens, session_contaminated |
| T3.6 | | | | | | | turns to correct fix |

Include notes on any cases where an approach failed to detect an error, produced an incorrect fix, or lost session state.