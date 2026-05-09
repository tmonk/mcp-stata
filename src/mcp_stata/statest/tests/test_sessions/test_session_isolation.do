* test_session_isolation.do
* The runner should run this in a fresh session.
* We assert that a global macro from a hypothetical previous run is NOT present.
st_assert_macro "$isolation_check", expected("")
global isolation_check = 1
