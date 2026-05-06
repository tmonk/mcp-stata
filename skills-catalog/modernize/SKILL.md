# Modern Stata Skill

Guide for AI agents to write modern, efficient, and robust Stata code.

## Core Principles

1.  **Use Frames Instead of Preserve/Restore**: Data frames (introduced in Stata 16) allow multiple datasets to coexist in memory. They are significantly faster than `preserve`/`restore` because they avoid disk I/O.
2.  **Use gtools for Large Datasets**: `gtools` (e.g., `gcollapse`, `gegen`, `gregress`) provides C-based implementations of common Stata commands that are much faster on large datasets.
3.  **High-Dimensional Fixed Effects**: Use `reghdfe` for regressions with many fixed effects. It is faster and more stable than using factor variables with `regress`.
4.  **Avoid #delimit**: Use `///` for line continuation. It is more readable and less prone to errors when copying/pasting code snippets.
5.  **Use Dynamic Paths**: Use locals or globals for base paths instead of `cd`. This makes do-files more portable.

## Anti-Patterns and Replacements

| Legacy Pattern | Modern Replacement | Why? |
| :--- | :--- | :--- |
| `preserve` / `restore` | `frame create temp ...` / `frame change ...` | Faster, avoids disk I/O, cleaner state management. |
| `regress y x i.id` | `reghdfe y x, absorb(id)` | Faster, avoids creating thousands of dummy variables. |
| `egen m = mean(x), by(id)` | `gegen m = mean(x), by(id)` | `gtools` is significantly faster for large data. |
| `drop _all` / `clear` | `clear all` / `frame reset` | Ensure all system state (globals, programs, frames) is cleared. |
| `#delimit ;` | `///` at the end of lines | Standard in modern Stata, easier to debug. |
| `quietly { ... }` | `qui ...` or `frames` | Keep code concise. |

## Detailed Examples

### 1. Advanced Frame Management
Frames allow you to keep multiple datasets in memory simultaneously, which is essential for "what-if" analysis or complex merges.

**Example: Computing Group Statistics Without Disk I/O**
```stata
// Traditional Way (Slow disk I/O)
preserve
    collapse (mean) mean_val=val (sd) sd_val=val, by(group_id)
    tempfile stats
    save "`stats'"
restore
merge m:1 group_id using "`stats'"

// Modern Way (Frames - Memory Only)
frame put group_id val, frame(stats)
frame stats {
    collapse (mean) mean_val=val (sd) sd_val=val, by(group_id)
}
frlink m:1 group_id, frame(stats)
frget mean_val sd_val, from(stats)
```

**Example: Multi-Step Data Cleaning with Frames**
```stata
frame create cleaning
frame cleaning {
    use raw_data.dta
    drop if missing(id)
    gen new_var = x * y
}
// Default frame remains untouched until you are ready
```

**Example: Side-by-Side Comparison**
```stata
frame create analysis
frame analysis: use data_cleaned.dta
// Keep original data in 'default' frame, run regressions in 'analysis'
frame analysis: reghdfe y x, absorb(id)
```

### 2. High-Performance gtools
`gtools` provides massive speedups for large datasets (millions of rows).

**Example: Fast Aggregation and Deduping**
```stata
// Instead of slow standard commands:
duplicates drop id date, force
isid id date
collapse (sum) revenue (mean) price, by(id)

// Use gtools:
gduplicates drop id date, force
gisid id date
gcollapse (sum) revenue (mean) price, by(id)
```

**Example: Rapid Regression Diagnostics**
```stata
// Instead of regress:
gregress y x1 x2 x3, by(group)
```

**Example: Efficient Tagging**
```stata
// Instead of:
egen tag = tag(id date)
// Use gtools:
gegen tag = tag(id date)
```

### 5. Portable Dynamic Paths
Avoid hardcoded paths and `cd` commands. Use a single source of truth for paths.

**Example: Project-Wide Path Configuration**
```stata
// Define at the top of your master do-file
global PROJ_ROOT "/Users/username/projects/research_paper"
global DATA_RAW  "${PROJ_ROOT}/data/raw"
global DATA_INT  "${PROJ_ROOT}/data/intermediate"
global OUTPUT    "${PROJ_ROOT}/output"

// Usage
use "${DATA_RAW}/survey_2023.dta", clear
save "${DATA_INT}/cleaned.dta", replace
export excel "${OUTPUT}/tables.xlsx", sheet("Table 1")
```

**Example: Robust Tempfile Management**
```stata
tempfile my_results
gcollapse (mean) x, by(id)
save "`my_results'"
// No need to worry about path collisions or cleanup
```

**Example: Cross-Platform Compatibility**
Always use forward slashes `/`, even on Windows. Stata handles them correctly, and it prevents do-files from breaking when shared.

---

## Testing & Validation
Use `stata_manage_session(action="detect")` to verify your environment has necessary packages (`gtools`, `reghdfe`) installed. Use `stata_inspect_data(action="lint")` to check your do-files for legacy anti-patterns like `cd` or `preserve`.
