* test_assert_macro_fail.do
sysuse auto, clear
regress price mpg
st_assert_macro e(cmd), expected("summarize")
