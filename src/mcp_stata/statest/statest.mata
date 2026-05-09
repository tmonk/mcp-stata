* statest.mata - Mata testing library for mcp-stata

mata:

void statest_init_scalars()
{
    real matrix m
    m = st_numscalar("statest_assertion_index")
    if (length(m) == 0) {
        st_numscalar("statest_assertion_index", 0)
    }
}

void statest_capture_failure(string scalar cmd, string scalar var, real scalar actual, real scalar expected, real scalar tol)
{
    st_strscalar("statest_command", cmd)
    st_strscalar("statest_variable", var)
    st_numscalar("statest_actual", actual)
    st_numscalar("statest_expected", expected)
    st_numscalar("statest_tolerance", tol)
}

void statest_capture_failure_str(string scalar cmd, string scalar var, string scalar actual, string scalar expected)
{
    st_strscalar("statest_command", cmd)
    st_strscalar("statest_variable", var)
    st_strscalar("statest_actual_str", actual)
    st_strscalar("statest_expected_str", expected)
}

void statest_assert_scalar(real scalar actual, real scalar expected, real scalar tol)
{
    real matrix m
    real scalar idx
    real scalar passed
    
    statest_init_scalars()
    m = st_numscalar("statest_assertion_index")
    idx = (length(m) > 0 ? m[1,1] : 0) + 1
    st_numscalar("statest_assertion_index", idx)
    
    passed = (abs(actual - expected) <= tol)
    
    if (passed == 0) {
        statest_capture_failure("st_assert_scalar", "", actual, expected, tol)
        exit(9)
    }
}

void statest_assert_macro(string scalar actual, string scalar expected)
{
    real matrix m
    real scalar idx
    real scalar passed
    
    statest_init_scalars()
    m = st_numscalar("statest_assertion_index")
    idx = (length(m) > 0 ? m[1,1] : 0) + 1
    st_numscalar("statest_assertion_index", idx)
    
    passed = (actual == expected)
    
    if (passed == 0) {
        statest_capture_failure_str("st_assert_macro", "", actual, expected)
        exit(9)
    }
}

void statest_assert_rc(real scalar expected_rc, string scalar cmd)
{
    real matrix m
    real scalar idx
    real scalar actual_rc
    
    statest_init_scalars()
    m = st_numscalar("statest_assertion_index")
    idx = (length(m) > 0 ? m[1,1] : 0) + 1
    st_numscalar("statest_assertion_index", idx)
    
    st_strscalar("statest_rc_cmd", cmd)
    actual_rc = _stata(cmd)
    
    if (actual_rc != expected_rc) {
        statest_capture_failure("st_assert_rc", cmd, actual_rc, expected_rc, 0)
        exit(9)
    }
}

void statest_assert_matrix(string scalar name, string scalar expected_name, real scalar tol)
{
    real matrix m
    real scalar idx
    real matrix A, B
    real scalar passed
    
    statest_init_scalars()
    m = st_numscalar("statest_assertion_index")
    idx = (length(m) > 0 ? m[1,1] : 0) + 1
    st_numscalar("statest_assertion_index", idx)
    
    A = st_matrix(name)
    B = st_matrix(expected_name)
    
    if (rows(A) != rows(B) || cols(A) != cols(B)) {
        statest_capture_failure("st_assert_matrix", name, 0, 0, tol)
        st_strscalar("statest_error", "Matrix dimensions mismatch")
        exit(9)
    }
    
    passed = all(abs(A :- B) :<= tol)
    
    if (passed == 0) {
        statest_capture_failure("st_assert_matrix", name, 0, 0, tol)
        exit(9)
    }
}

end

program define statest_reset
    version 16
    mata: st_numscalar("statest_assertion_index", 0)
    capture scalar drop statest_command
    capture scalar drop statest_variable
    capture scalar drop statest_actual
    capture scalar drop statest_expected
    capture scalar drop statest_tolerance
    capture scalar drop statest_actual_str
    capture scalar drop statest_expected_str
end

/* Stata wrappers */

program define st_assert_scalar
    version 16
    syntax anything(name=actual), expected(real) [tol(real 0)]
    tempname val
    scalar `val' = `actual'
    mata: statest_assert_scalar(st_numscalar("`val'"), `expected', `tol')
end

program define st_assert_macro
    version 16
    syntax anything(name=actual), [expected(string)]
    local val = `actual'
    mata: statest_assert_macro(`"`val'"', `"`expected'"')
end

program define st_assert_rc
    version 16
    syntax anything(name=expected_rc), cmd(string)
    mata: statest_assert_rc(`expected_rc', `"`cmd'"')
end

program define st_assert_matrix
    version 16
    syntax anything(name=actual_name), expected(string) [tol(real 0)]
    mata: statest_assert_matrix("`actual_name'", "`expected'", `tol')
end
