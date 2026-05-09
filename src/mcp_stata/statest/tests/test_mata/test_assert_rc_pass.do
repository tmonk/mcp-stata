* test_assert_rc_pass.do
st_assert_rc 601, cmd("use nonexistent.dta")
st_assert_rc 198, cmd("summarize, nonexistent_option")

