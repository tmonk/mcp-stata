use numpy::PyReadonlyArray1;
use pyo3::prelude::*;
use pyo3::types::PyModule;
use rayon::prelude::*;
use std::cmp::Ordering;

const PAR_SORT_THRESHOLD: usize = 2_500;

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
    }

    #[test]
    fn test_argsort_numeric_core_single_column() {
        let col = [3.0, 1.0, f64::NAN, 2.0];
        let arrays = vec![col.as_slice()];
        let res = argsort_numeric_core(&arrays, &[false], &[true]);
        assert_eq!(res, vec![1, 3, 0, 2]);
    }

    #[test]
    fn test_argsort_numeric_core_multi_column() {
        let col1 = [2.0, 1.0, 1.0, 2.0];
        let col2 = [4.0, 3.0, 1.0, 2.0];
        let arrays = vec![col1.as_slice(), col2.as_slice()];
        let res = argsort_numeric_core(&arrays, &[false, true], &[true, true]);
        assert_eq!(res, vec![1, 2, 0, 3]);
    }

    #[test]
    fn test_argsort_mixed_core() {
        let nums = vec![2.0, 1.0, f64::NAN, 1.0];
        let text = vec![Some("b".to_string()), Some("a".to_string()), None, Some("c".to_string())];
        let parsed = vec![
            ColumnData::Numeric(nums.as_slice()),
            ColumnData::Text(text.as_slice())
        ];
        let res = argsort_mixed_core(&parsed, &[false, false], &[true, true]);
        assert_eq!(res, vec![1, 3, 0, 2]);
    }
}

#[pymodule]
fn _native_sorter(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(argsort_numeric, m)?)?;
    m.add_function(wrap_pyfunction!(argsort_mixed, m)?)?;
    Ok(())
}