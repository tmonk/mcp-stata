* test_assert_macro_pass.do
sysuse auto, clear
regress price mpg
st_assert_macro e(cmd), expected("regress")
st_assert_macro e(depvar), expected("price")
