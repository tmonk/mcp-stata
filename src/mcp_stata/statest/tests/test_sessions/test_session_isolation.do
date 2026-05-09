* test_session_isolation.do
* If this is isolated, this global should not exist from other tests
* (Assuming no other test sets it, or they run in fresh sessions)
if "$S_isolation" != "" {
    display "Isolation failure!"
    exit 9
}
global S_isolation = "done"
st_assert_macro "$S_isolation", expected("done")
