* test_assert_scalar_fail.do
sysuse auto, clear
summarize price
st_assert_scalar r(mean), expected(5000)
