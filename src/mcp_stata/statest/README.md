# statest v0.1

`statest` is a native testing framework for Stata, integrated directly into `mcp-stata`. It provides a pytest-like experience for Stata `.do` files, with isolated sessions and structured assertion reporting.

## Features

- **Isolated Sessions**: Each test run starts a fresh Stata session (no leaking globals, macros, or datasets).
- **Mata Assertions**: Use `st_assert_scalar`, `st_assert_macro`, `st_assert_rc`, and `st_assert_matrix` for high-performance assertions.
- **Structured Results**: Failure metadata (expected vs actual, command, variable name) is captured and returned via the MCP tool.
- **Discovery**: Automatically finds `test_*.do` files in your project directory.

## MCP Tools

| Tool | Description |
| --- | --- |
| `stata_run_tests(path)` | Discover and run all tests under the specified path. |
| `stata_run_test(path)` | Run a single test `.do` file. |
| `stata_discover_tests(path)` | List all test files under the path without running them. |
| `stata_get_test_results()` | Retrieve structured results from the last run. |

## Writing Tests

Create a file named `test_example.do`:

```stata
* test_example.do
sysuse auto, clear
summarize price
st_assert_scalar r(mean), expected(6165.2568) tol(0.0001)
st_assert_scalar r(N), expected(74)

regress price mpg weight
st_assert_macro e(depvar), expected("price")
st_assert_rc 0, cmd("predict yhat")
```

## Available Assertions

- `st_assert_scalar val, expected(real) [tol(real)]`: Compare a numeric value or Stata scalar.
- `st_assert_macro macro_name, expected(string)`: Compare a Stata macro or string expression.
- `st_assert_rc expected_rc, cmd(string)`: Assert that a command returns a specific return code.
- `st_assert_matrix matrix_name, expected(matrix_name) [tol(real)]`: Compare two Stata matrices.

## How it works

`statest` injects a native Mata library into every Stata session. When an assertion fails, the test exits with `rc=9`, and the framework fetches the failure metadata from Stata scalars before cleaning up the session.
