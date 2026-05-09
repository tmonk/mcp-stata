* test_session_teardown.do
* Verify that we can run a test that just exits normally.
sysuse auto, clear
summarize price
st_assert_scalar r(N), expected(74)

exit 0
