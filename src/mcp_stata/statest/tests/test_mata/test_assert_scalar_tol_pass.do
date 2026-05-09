* test_assert_scalar_tol_pass.do
sysuse auto, clear
summarize price
st_assert_scalar r(mean), expected(6165) tol(1.0)
