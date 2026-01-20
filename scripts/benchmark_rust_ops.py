import time
import re
import os
import numpy as np
from mcp_stata._native_ops import smcl_to_markdown as rust_smcl_to_markdown
from mcp_stata._native_ops import fast_scan_log as rust_fast_scan_log
from mcp_stata._native_ops import compute_filter_indices as rust_compute_filter_indices

# --- Task 1: SMCL to Markdown ---
def python_smcl_to_markdown(smcl_text: str) -> str:
    def _inline_to_markdown(text: str) -> str:
        def repl(match: re.Match) -> str:
            tag = match.group(1).lower()
            content = match.group(2) or ""
            if tag in ("bf", "strong"): return f"**{content}**"
            if tag in ("it", "em"): return f"*{content}*"
            if tag in ("cmd", "cmdab", "code", "inp", "input", "res", "err", "txt"): return f"`{content}`"
            return content
        text = re.sub(r"\{([a-zA-Z0-9_]+):([^}]*)\}", repl, text)
        text = re.sub(r"\{[^}]*\}", "", text)
        return text

    if not smcl_text: return ""
    lines = smcl_text.splitlines()
    body_parts = []
    title = None
    for raw in lines:
        line = raw.strip()
        if not line or line == "{smcl}": continue
        if line.startswith("{title:"):
            title = line[len("{title:") :].rstrip("}")
            continue
        line = line.replace("{p_end}", "")
        line = re.sub(r"\{p[^}]*\}", "", line)
        body_parts.append(_inline_to_markdown(line))
    
    res = ""
    if title: res += f"## {title}\n\n"
    res += "\n".join(part for part in body_parts if part)
    return res

# --- Task 2: Log Scanning ---
def python_fast_scan_log(smcl_content: str, rc_default: int):
    rc = None
    matches = list(re.finditer(r'\{search r\((\d+)\)', smcl_content))
    if matches:
        rc = int(matches[-1].group(1))
    if rc is None:
        matches = list(re.finditer(r'(?<!\w)r\((\d+)\);?', smcl_content))
        if matches:
            rc = int(matches[-1].group(1))
    
    lines = smcl_content.splitlines()
    error_msg = f"Stata error r({rc or rc_default})"
    error_start_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if '{err}' in lines[i]:
            error_start_idx = i
            j = i
            err_lines = []
            while j >= 0 and '{err}' in lines[j]:
                cleaned = re.sub(r'\{[^}]*\}', '', lines[j]).strip()
                if cleaned: err_lines.insert(0, cleaned)
                j -= 1
            if err_lines: error_msg = " ".join(err_lines)
            break
    
    context_start = max(0, error_start_idx - 5) if error_start_idx >= 0 else max(0, len(lines) - 30)
    context = "\n".join(lines[context_start:])
    return error_msg, context, rc

# --- Task 3: Filtering ---
def python_compute_filter(expr: str, names: list, columns: list):
    # Simplified simulation of the eval loop
    indices = []
    row_count = len(columns[0])
    # Pre-compile
    code = compile(expr, "<string>", "eval")
    for i in range(row_count):
        env = {names[j]: columns[j][i] for j in range(len(names))}
        if eval(code, {"__builtins__": {}}, env):
            indices.append(i)
    return indices

def run_benchmarks():
    print("--- Rust vs Python Benchmarks ---")
    
    # Benchmark SMCL
    smcl_sample = "{smcl}\n{title:Help for regress}\n{p 4 4 2}\n{bf:regress} fits a model of {it:depvar} on {it:indepvars}.\n{p_end}\n" * 1000
    t0 = time.perf_counter()
    py_smcl = python_smcl_to_markdown(smcl_sample)
    t1 = time.perf_counter()
    rust_smcl = rust_smcl_to_markdown(smcl_sample)
    t2 = time.perf_counter()
    print(f"SMCL (4000 lines): Python={t1-t0:.4f}s, Rust={t2-t1:.4f}s (Ratio: {(t1-t0)/(t2-t1):.1f}x)")

    # Benchmark Log Scan
    log_sample = "some output\n" * 50000 + "{err}variable not found\n{err}r(111);\n{search r(111), ...}\n"
    t0 = time.perf_counter()
    py_log = python_fast_scan_log(log_sample, 0)
    t1 = time.perf_counter()
    rust_log = rust_fast_scan_log(log_sample, 0)
    t2 = time.perf_counter()
    print(f"Log Scan (50000 lines): Python={t1-t0:.4f}s, Rust={t2-t1:.4f}s (Ratio: {(t1-t0)/(t2-t1):.1f}x)")

    # Benchmark Filtering
    N = 100000
    names = ["price", "mpg"]
    price = np.random.rand(N) * 10000
    mpg = np.random.rand(N) * 30
    expr = "(price > 5000) && (mpg < 20)"
    
    # Rust needs specific types
    t0 = time.perf_counter()
    # Mocking what the client would do: pass numpy arrays directly
    rust_res = rust_compute_filter_indices(expr, names, [price, mpg], [False, False])
    t1 = time.perf_counter()
    print(f"Filtering ({N} rows): Rust={t1-t0:.4f}s")
    
    # Python is too slow for 100k rows in a real eval loop helper, let's do 10k for comparison
    N_small = 10000
    price_s = price[:N_small]
    mpg_s = mpg[:N_small]
    expr_py = "(price > 5000) and (mpg < 20)"
    t0 = time.perf_counter()
    py_res = python_compute_filter(expr_py, names, [price_s, mpg_s])
    t1 = time.perf_counter()
    print(f"Filtering ({N_small} rows): Python={t1-t0:.4f}s")
    print(f"Extrapolated Python for {N} rows: {(t1-t0)*10:.4f}s (Ratio: {((t1-t0)*10)/(rust_res_t := (t1-t0 if 'rust_res_t' not in locals() else rust_res_t)):.1f}x)")
    # Correcting ratio calculation
    rust_N = (t1_rust := time.perf_counter()) - (t0_rust := time.perf_counter()) # placeholder
    t0_rust = time.perf_counter()
    rust_compute_filter_indices(expr, names, [price, mpg], [False, False])
    t1_rust = time.perf_counter()
    rust_time = t1_rust - t0_rust
    print(f"Actual Ratio for Filtering: {((t1-t0)*10)/rust_time:.1f}x")

if __name__ == "__main__":
    run_benchmarks()
