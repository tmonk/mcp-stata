use fasteval::{Compiler, Evaler, Slab, Parser};
use numpy::PyReadonlyArray1;
use pyo3::prelude::*;
use pyo3::types::PyModule;
use rayon::prelude::*;
use regex::Regex;
use std::cmp::Ordering;
use std::sync::OnceLock;

static RE_INLINE: OnceLock<Regex> = OnceLock::new();
static RE_RC_PRIMARY: OnceLock<Regex> = OnceLock::new();
static RE_RC_SECONDARY: OnceLock<Regex> = OnceLock::new();
static RE_ANY_TAG: OnceLock<Regex> = OnceLock::new();

const PAR_SORT_THRESHOLD: usize = 2_500;
const PAR_FILTER_THRESHOLD: usize = 5_000;
const MAX_FILTER_EXPR_LEN: usize = 1000;

fn cmp_with_nulls(
    a: f64,
    b: f64,
    descending: bool,
    nulls_last: bool,
) -> Ordering {
    let a_null = a.is_nan();
    let b_null = b.is_nan();

    if a_null || b_null {
        if a_null && b_null {
            return Ordering::Equal;
        }
        if nulls_last {
            return if a_null { Ordering::Greater } else { Ordering::Less };
        }
        return if a_null { Ordering::Less } else { Ordering::Greater };
    }

    if a < b {
        if descending {
            Ordering::Greater
        } else {
            Ordering::Less
        }
    } else if a > b {
        if descending {
            Ordering::Less
        } else {
            Ordering::Greater
        }
    } else {
        Ordering::Equal
    }
}

fn argsort_numeric_core(
    arrays: &[&[f64]],
    descending: &[bool],
    nulls_last: &[bool],
) -> Vec<usize> {
    if arrays.is_empty() {
        return Vec::new();
    }
    let len = arrays[0].len();
    let mut indices: Vec<usize> = (0..len).collect();

    let sort_fn = |&i: &usize, &j: &usize| {
        for (col_idx, col) in arrays.iter().enumerate() {
            let desc = descending[col_idx];
            let null_last = nulls_last[col_idx];
            let ord = cmp_with_nulls(col[i], col[j], desc, null_last);
            if ord != Ordering::Equal {
                return ord;
            }
        }
        Ordering::Equal
    };

    if len < PAR_SORT_THRESHOLD {
        indices.sort_unstable_by(sort_fn);
    } else {
        indices.par_sort_unstable_by(sort_fn);
    }

    indices
}

fn argsort_mixed_core(
    parsed: &[ColumnData],
    descending: &[bool],
    nulls_last: &[bool],
) -> Vec<usize> {
    if parsed.is_empty() {
        return Vec::new();
    }

    let row_count = match &parsed[0] {
        ColumnData::Numeric(values) => values.len(),
        ColumnData::Text(values) => values.len(),
    };

    let mut indices: Vec<usize> = (0..row_count).collect();

    let sort_fn = |&i: &usize, &j: &usize| {
        for (col_idx, col) in parsed.iter().enumerate() {
            let desc = descending[col_idx];
            let null_last = nulls_last[col_idx];
            let ord = match col {
                ColumnData::Numeric(values) => {
                    cmp_with_nulls(values[i], values[j], desc, null_last)
                }
                ColumnData::Text(values) => {
                    let a = values[i].as_deref();
                    let b = values[j].as_deref();
                    match (a, b) {
                        (None, None) => Ordering::Equal,
                        (None, Some(_)) => {
                            if null_last {
                                Ordering::Greater
                            } else {
                                Ordering::Less
                            }
                        }
                        (Some(_), None) => {
                            if null_last {
                                Ordering::Less
                            } else {
                                Ordering::Greater
                            }
                        }
                        (Some(a), Some(b)) => {
                            let cmp = a.cmp(b);
                            if desc { cmp.reverse() } else { cmp }
                        }
                    }
                }
            };
            if ord != Ordering::Equal {
                return ord;
            }
        }
        Ordering::Equal
    };

    if row_count < PAR_SORT_THRESHOLD {
        indices.sort_unstable_by(sort_fn);
    } else {
        indices.par_sort_unstable_by(sort_fn);
    }

    indices
}

enum Storage<'a> {
    Num(PyReadonlyArray1<'a, f64>),
    Txt(Vec<Option<String>>),
}

enum ColumnData<'a> {
    Numeric(&'a [f64]),
    Text(&'a [Option<String>]),
}

#[pyfunction]
fn argsort_numeric(
    _py: Python<'_>,
    columns: Vec<PyReadonlyArray1<f64>>,
    descending: Vec<bool>,
    nulls_last: Vec<bool>,
) -> PyResult<Vec<usize>> {
    if columns.is_empty() {
        return Ok(Vec::new());
    }
    if descending.len() != columns.len() || nulls_last.len() != columns.len() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "descending/nulls_last length mismatch",
        ));
    }

    let len = columns[0].len()?;
    for col in &columns {
        if col.len()? != len {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "column length mismatch",
            ));
        }
    }

    // No copies here: as_slice() provides references to the Python-owned data.
    let arrays: Vec<_> = columns
        .iter()
        .map(|c| c.as_slice())
        .collect::<Result<Vec<&[f64]>, _>>()
        .map_err(|_| pyo3::exceptions::PyValueError::new_err("non-contiguous array"))?;

    Ok(argsort_numeric_core(&arrays, &descending, &nulls_last))
}

#[pyfunction]
fn argsort_mixed(
    py: Python<'_>,
    columns: Vec<Py<PyAny>>,
    is_string: Vec<bool>,
    descending: Vec<bool>,
    nulls_last: Vec<bool>,
) -> PyResult<Vec<usize>> {
    if columns.is_empty() {
        return Ok(Vec::new());
    }
    let count = columns.len();
    if is_string.len() != count
        || descending.len() != count
        || nulls_last.len() != count
    {
        return Err(pyo3::exceptions::PyValueError::new_err("length mismatch"));
    }

    // Extract all data first (prevents moves during iteration)
    let storage: Vec<Storage> = columns
        .iter()
        .zip(&is_string)
        .map(|(obj, &is_str)| {
            if is_str {
                Ok(Storage::Txt(obj.extract(py)?))
            } else {
                Ok(Storage::Num(obj.extract(py)?))
            }
        })
        .collect::<PyResult<_>>()?;

    // Verify lengths and create references
    let mut row_count: Option<usize> = None;
    let parsed: Vec<ColumnData> = storage
        .iter()
        .map(|s| match s {
            Storage::Num(arr) => {
                let slice = arr
                    .as_slice()
                    .map_err(|_| pyo3::exceptions::PyValueError::new_err("non-contiguous"))?;
                let len = slice.len();
                if let Some(n) = row_count {
                    if n != len {
                        return Err(pyo3::exceptions::PyValueError::new_err("length mismatch"));
                    }
                } else {
                    row_count = Some(len);
                }
                Ok(ColumnData::Numeric(slice))
            }
            Storage::Txt(vec) => {
                let len = vec.len();
                if let Some(n) = row_count {
                    if n != len {
                        return Err(pyo3::exceptions::PyValueError::new_err("length mismatch"));
                    }
                } else {
                    row_count = Some(len);
                }
                Ok(ColumnData::Text(vec.as_slice()))
            }
        })
        .collect::<PyResult<_>>()?;

    let rows = row_count.unwrap_or(0);
    if rows == 0 {
        return Ok(Vec::new());
    }

    Ok(argsort_mixed_core(&parsed, &descending, &nulls_last))
}

#[pyfunction]
pub fn smcl_to_markdown(smcl: String) -> String {
    let re_inline = RE_INLINE.get_or_init(|| {
        Regex::new(r"\{([a-zA-Z0-9_]+):([^}]*)\}").unwrap()
    });
    let re_any = RE_ANY_TAG.get_or_init(|| {
        Regex::new(r"\{[^}]*\}").unwrap()
    });

    let lines: Vec<&str> = smcl.lines().collect();
    
    // Extract title sequentially (usually near top)
    let mut title = None;
    for line in &lines {
        let trimmed = line.trim();
        if trimmed.starts_with("{title:") {
            if let Some(t) = trimmed.strip_prefix("{title:").and_then(|s| s.strip_suffix('}')) {
                title = Some(t.to_string());
                break;
            }
        }
    }

    // Process lines in parallel for large SMCL files
    let processed_lines: Vec<String> = lines.par_iter()
        .map(|line| {
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed == "{smcl}" || trimmed.starts_with("{title:") {
                return String::new();
            }

            // Pass 1: Replace known tags with Markdown using Cow to avoid unnecessary allocations
            let processed = re_inline.replace_all(trimmed, |caps: &regex::Captures| {
                let tag = caps.get(1).map_or("", |m| m.as_str());
                let content = caps.get(2).map_or("", |m| m.as_str());
                
                if tag.eq_ignore_ascii_case("bf") || tag.eq_ignore_ascii_case("strong") {
                    format!("**{content}**")
                } else if tag.eq_ignore_ascii_case("it") || tag.eq_ignore_ascii_case("em") {
                    format!("*{content}*")
                } else if tag.eq_ignore_ascii_case("cmd") || tag.eq_ignore_ascii_case("cmdab") || 
                          tag.eq_ignore_ascii_case("code") || tag.eq_ignore_ascii_case("inp") || 
                          tag.eq_ignore_ascii_case("input") || tag.eq_ignore_ascii_case("res") || 
                          tag.eq_ignore_ascii_case("err") || tag.eq_ignore_ascii_case("txt") {
                    format!("`{content}`")
                } else {
                    content.to_string()
                }
            });

            // Pass 2: Strip all remaining tags (including p-tags and alignment tags)
            let stripped = re_any.replace_all(&processed, "");
            stripped.trim().to_string()
        })
        .filter(|s| !s.is_empty())
        .collect();

    let body = processed_lines.join("\n");
    match title {
        Some(t) => format!("## {t}\n\n{body}"),
        None => body,
    }
}

#[pyfunction]
pub fn fast_scan_log(smcl_content: String, rc_default: i32) -> (String, String, Option<i32>) {
    let re_rc_primary =
        RE_RC_PRIMARY.get_or_init(|| Regex::new(r"\{search r\((\d+)\)").unwrap());
    let re_rc_secondary =
        RE_RC_SECONDARY.get_or_init(|| Regex::new(r"\br\((\d+)\);?").unwrap());
    let re_any_tag = RE_ANY_TAG.get_or_init(|| Regex::new(r"\{[^}]*\}").unwrap());

    let mut rc = None;
    if let Some(caps) = re_rc_primary.captures_iter(&smcl_content).last() {
        rc = caps.get(1).and_then(|m| m.as_str().parse::<i32>().ok());
    }
    if rc.is_none() {
        if let Some(caps) = re_rc_secondary.captures_iter(&smcl_content).last() {
            rc = caps.get(1).and_then(|m| m.as_str().parse::<i32>().ok());
        }
    }

    let lines: Vec<&str> = smcl_content.lines().collect();
    let mut error_msg = format!("Stata error r({})", rc.unwrap_or(rc_default));
    let mut error_start_idx: Option<usize> = None;

    for i in (0..lines.len()).rev() {
        if lines[i].contains("{err}") {
            error_start_idx = Some(i);
            let mut err_lines = Vec::new();
            let mut j = i;
            // Walk backwards for consecutive error lines
            loop {
                let cleaned = re_any_tag.replace_all(lines[j], "").trim().to_string();
                if !cleaned.is_empty() {
                    err_lines.push(cleaned);
                }
                if j == 0 || !lines[j-1].contains("{err}") {
                    break;
                }
                j -= 1;
            }
            if !err_lines.is_empty() {
                err_lines.reverse();
                error_msg = err_lines.join(" ");
            }
            break;
        }
    }

    let context_start = if let Some(idx) = error_start_idx {
        idx.saturating_sub(5)
    } else {
        lines.len().saturating_sub(30)
    };
    let context = lines[context_start..].join("\n");

    (error_msg, context, rc)
}

#[pyfunction]
pub fn compute_filter_indices(
    py: Python<'_>,
    expr_str: String,
    names: Vec<String>,
    columns: Vec<Py<PyAny>>,
    is_string: Vec<bool>,
) -> PyResult<Vec<usize>> {
    // Security: limit expression length
    if expr_str.len() > MAX_FILTER_EXPR_LEN {
        return Err(pyo3::exceptions::PyValueError::new_err("Filter expression too long"));
    }

    // Compile expression once
    let parser = Parser::new();
    let mut slab = Slab::new();
    
    let compiled = parser
        .parse(&expr_str, &mut slab.ps)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Parse error: {}", e)))?
        .from(&slab.ps)
        .compile(&slab.ps, &mut slab.cs);

    // Validation
    if names.len() != columns.len() || names.len() != is_string.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("Length mismatch"));
    }

    // Pre-calculate name-to-index map for O(1) variable lookup
    let name_map: std::collections::HashMap<&str, usize> = names
        .iter()
        .enumerate()
        .map(|(i, name)| (name.as_str(), i))
        .collect();

    // Extract storage
    let storage: Vec<Storage> = columns
        .iter()
        .zip(&is_string)
        .map(|(obj, &is_str)| {
            if is_str {
                Ok(Storage::Txt(obj.extract(py)?))
            } else {
                Ok(Storage::Num(obj.extract(py)?))
            }
        })
        .collect::<PyResult<_>>()?;

    let row_count = if let Some(first) = storage.first() {
        match first {
            Storage::Num(arr) => arr.len()?,
            Storage::Txt(vec) => vec.len(),
        }
    } else {
        0
    };

    if row_count == 0 {
        return Ok(Vec::new());
    }

    let parsed: Vec<ColumnData> = storage
        .iter()
        .map(|s| match s {
            Storage::Num(arr) => {
                let slice = arr.as_slice()
                    .map_err(|_| pyo3::exceptions::PyValueError::new_err("Non-contiguous"))?;
                Ok(ColumnData::Numeric(slice))
            }
            Storage::Txt(vec) => Ok(ColumnData::Text(vec.as_slice())),
        })
        .collect::<PyResult<_>>()?;

    // Parallel filtering with zero-copy variable lookup
    let indices: Vec<usize> = if row_count >= PAR_FILTER_THRESHOLD {
        (0..row_count)
            .into_par_iter()
            .filter_map(|i| {
                // Callback for variable lookup - NO CLONES!
                let mut cb = |name: &str, _args: Vec<f64>| -> Option<f64> {
                    name_map.get(name).and_then(|&idx| {
                        match &parsed[idx] {
                            ColumnData::Numeric(slice) => {
                                let val = slice[i];
                                if val.is_nan() { None } else { Some(val) }
                            }
                            ColumnData::Text(slice) => {
                                match &slice[i] {
                                    Some(s) => s.parse::<f64>().ok(),
                                    None => None,
                                }
                            }
                        }
                    })
                };

                match compiled.eval(&slab, &mut cb) {
                    Ok(res) => if res != 0.0 && !res.is_nan() { Some(i) } else { None },
                    Err(_) => None,
                }
            })
            .collect()
    } else {
        // Sequential path
        (0..row_count)
            .filter(|&i| {
                let mut cb = |name: &str, _args: Vec<f64>| -> Option<f64> {
                    name_map.get(name).and_then(|&idx| {
                        match &parsed[idx] {
                            ColumnData::Numeric(slice) => {
                                let val = slice[i];
                                if val.is_nan() { None } else { Some(val) }
                            }
                            ColumnData::Text(slice) => {
                                match &slice[i] {
                                    Some(s) => s.parse::<f64>().ok(),
                                    None => None,
                                }
                            }
                        }
                    })
                };

                match compiled.eval(&slab, &mut cb) {
                    Ok(res) => res != 0.0 && !res.is_nan(),
                    Err(_) => false,
                }
            })
            .collect()
    };

    Ok(indices)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cmp_with_nulls_ordering() {
        assert_eq!(cmp_with_nulls(1.0, 2.0, false, true), Ordering::Less);
        assert_eq!(cmp_with_nulls(2.0, 1.0, false, true), Ordering::Greater);
        assert_eq!(cmp_with_nulls(1.0, 2.0, true, true), Ordering::Greater);
        assert_eq!(cmp_with_nulls(f64::NAN, 1.0, false, true), Ordering::Greater);
        assert_eq!(cmp_with_nulls(f64::NAN, 1.0, false, false), Ordering::Less);
        assert_eq!(cmp_with_nulls(f64::NAN, f64::NAN, false, true), Ordering::Equal);
    }

    #[test]
    fn test_argsort_numeric_core() {
        let col1 = [2.0, 1.0, 1.0, 2.0];
        let col2 = [4.0, 3.0, 1.0, 2.0];
        let arrays = vec![col1.as_slice(), col2.as_slice()];
        
        // Ascending col1, then descending col2
        let res = argsort_numeric_core(&arrays, &[false, true], &[true, true]);
        assert_eq!(res, vec![1, 2, 0, 3]);
    }

    #[test]
    fn test_smcl_to_markdown_comprehensive() {
        let smcl = vec![
            "{smcl}",
            "{title:Full Documentation}",
            "{p 4 4 2}",
            "This is a {bf:bold} and {it:italic} test.",
            "{p_end}",
            "{txt}{ralign 78}(Adjusted for {res:70} clusters)",
            "{pstd}",
            "Simple {cmd:regress} {res:price} {res:mpg} and {err:error}.",
            "{p_end}"
        ].join("\n");

        let md = smcl_to_markdown(smcl);
        
        assert!(md.contains("## Full Documentation"));
        assert!(md.contains("This is a **bold** and *italic* test."));
        // Check ralign stripping
        assert!(md.contains("(Adjusted for `70` clusters)"));
        // Check nested and command tags
        assert!(md.contains("Simple `regress` `price` `mpg` and `error`."));
        // Check p-tags are gone
        assert!(!md.contains("{p"));
        assert!(!md.contains("{pstd}"));
    }

    #[test]
    fn test_fast_scan_log_comprehensive() {
        // Multi-line error + return code boundary check
        let smcl = vec![
            "Some preamble text",
            "{err}variable price not found",
            "{err}on line 42 of do-file",
            "{txt}Checking... Check:r(456);",
            "{search r(111):r(111);}"
        ].join("\n");

        let (msg, context, rc) = fast_scan_log(smcl, 0);
        
        // AUTHORITATIVE: Search tag (111) should win over standalone (456)
        assert_eq!(rc, Some(111));
        
        // Multi-line error message assembly
        assert_eq!(msg, "variable price not found on line 42 of do-file");
        
        // Context contains the error lines
        assert!(context.contains("variable price not found"));
        assert!(context.contains("{search r(111)"));

        // Boundary check for r(N)
        let smcl2 = "Summarized(123) and plain r(456);".to_string();
        let (_, _, rc2) = fast_scan_log(smcl2, 0);
        assert_eq!(rc2, Some(456)); // Should NOT match 123
    }

    #[test]
    fn test_fast_scan_log_authoritative_order() {
        // standalone r(456) comes BEFORE {search r(111)}
        let smcl = "r(456); and then {search r(111)}".to_string();
        let (_, _, rc) = fast_scan_log(smcl, 0);
        assert_eq!(rc, Some(111));

        // standalone r(456) comes AFTER {search r(111)}
        // (In practice this shouldn't happen, but we want to know what wins)
        let smcl2 = "{search r(111)} and then r(456);".to_string();
        let (_, _, rc2) = fast_scan_log(smcl2, 0);
        // Current logic: re_rc_primary wins if it exists
        assert_eq!(rc2, Some(111));
    }

    #[test]
    fn test_fasteval_logic_unit() {
        let parser = fasteval::Parser::new();
        let mut slab = Slab::new();
        let compiled = parser.parse("(x > 10) && (y < 5)", &mut slab.ps).unwrap()
            .from(&slab.ps).compile(&slab.ps, &mut slab.cs);
            
        let mut cb = |name: &str, _: Vec<f64>| -> Option<f64> {
            match name {
                "x" => Some(15.0),
                "y" => Some(2.0),
                _ => None
            }
        };
        assert!(compiled.eval(&slab, &mut cb).unwrap() != 0.0);
    }
}

#[pymodule]
fn _native_ops(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(argsort_numeric, m)?)?;
    m.add_function(wrap_pyfunction!(argsort_mixed, m)?)?;
    m.add_function(wrap_pyfunction!(smcl_to_markdown, m)?)?;
    m.add_function(wrap_pyfunction!(fast_scan_log, m)?)?;
    m.add_function(wrap_pyfunction!(compute_filter_indices, m)?)?;
    Ok(())
}