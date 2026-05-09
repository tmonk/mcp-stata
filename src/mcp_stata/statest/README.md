# statest v0.1

`statest` is a native testing framework for Stata, integrated directly into `mcp-stata`. It provides a `pytest`-equivalent experience for Stata, enabling automated testing of `.do` files with isolated sessions and structured assertion reporting.

## Features

- **Isolated Sessions**: Each test runs in a fresh, isolated Stata session by default, preventing state leakage (globals, macros, datasets) between tests.
- **Parallel Execution**: Run test suites in parallel across multiple Stata processes using the `parallel` flag and `max_workers` setting.
- **Mata-Powered Assertions**: High-performance assertions for scalars, macros, return codes, and matrices.
- **Fixture System**: Flexible suite-level and test-level setup and teardown logic.
- **JUnit XML Support**: Export test results to JUnit XML for seamless integration with GitHub Actions, Jenkins, and other CI/CD pipelines.
- **Rich Failure Metadata**: Precisely locate failures with assertion indices, expected vs. actual values, and log excerpts.

## MCP Tools

| Tool | Parameters | Description |
|---|---|---|
| `stata_run_tests` | `path`, `parallel`, `max_workers`, `junit_xml_path` | Discover and run all `test_*.do` files under `path`. |
| `stata_run_test` | `path`, `session_id` | Run a single test `.do` file. |
| `stata_discover_tests` | `path` | List all discoverable test files without running them. |
| `stata_get_test_results` | `session_id` | Retrieve the full structured result state of the last run. |

## File Conventions

| File | Scope | When it runs |
|---|---|---|
| `statest_conftest.do` | Suite-level | Once before the suite starts, in a dedicated session. |
| `statest_setup.do` | Per-test | In the test's own session, before the test file. |
| `statest_teardown.do` | Per-test | In the test's own session, after the test file (always runs, even on failure). |

> [!NOTE]
> `statest_setup.do` and `statest_teardown.do` are looked up in the same directory as the test file.

## Assertion API

Assertions are implemented in Mata and exposed as Stata programs. They capture failure metadata **before** throwing `rc 9`, ensuring the framework can report exactly what went wrong.

```stata
* Scalar equality with optional tolerance
st_assert_scalar r(mean), expected(6165.257) tol(0.001)

* Macro/String equality
st_assert_macro e(cmd), expected("regress")

* Expected failure (asserts a command throws a specific rc)
st_assert_rc 111, cmd("use nonexistent.dta")

* Matrix equality with tolerance
st_assert_matrix r(table), expected(M) tol(0.001)
```

## Example Test File

```stata
* test_means.do
sysuse auto, clear
summarize price
st_assert_scalar r(mean), expected(6165.257) tol(0.001)
st_assert_scalar r(N), expected(74)
```

## Parallel & CI Integration

### Parallel Execution
When `parallel: true` is passed to `stata_run_tests`, tests are distributed across workers (defaulting to 4). This is optimized for Stata MP licenses.

### CI Export
To generate reports for CI/CD systems:
```json
{
  "path": "tests/",
  "junit_xml_path": "reports/results.xml"
}
```

## Failure Reporting
On failure, `statest` returns a structured object including:
- `assertion_index`: Which assertion failed in the file.
- `expected` vs `actual`: The raw values compared.
- `log_excerpt`: The last 20 lines of the test's Stata log for rapid debugging.
- `setup_rc` and `teardown_rc`: Visibility into fixture failures.
