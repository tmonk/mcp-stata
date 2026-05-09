* test_assert_scalar_pass.do
sysuse auto, clear
summarize price
st_assert_scalar r(mean), expected(6165.2568) tol(0.0001)
st_assert_scalar r(N), expected(74)


