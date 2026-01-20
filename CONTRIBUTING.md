# Contributing to mcp-stata

Thank you for your interest in contributing to mcp-stata! This guide will help you set up your development environment, build the native extensions, run tests, and understand the project structure.

## Table of Contents

- [Development Setup](#development-setup)
- [Building the Project](#building-the-project)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)

## Development Setup

### Prerequisites

- **Stata 17+** (Required for integration tests)
- **Python 3.12+**
- **Rust Toolchain (1.75+)** (Required for building the native sorter extension)
- **uv** (Recommended) or pip

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/tmonk/mcp-stata.git
   cd mcp-stata
   ```

2. Install dependencies with uv:
   ```bash
   # Install main dependencies and development tools
   uv sync --extra dev --no-install-project
   ```

   Or with pip:
   ```bash
   pip install -e .[dev]
   ```

3. Set up Stata path (if auto-discovery doesn't work):
   ```bash
   # macOS
   export STATA_PATH="/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp"

   # Windows
   set STATA_PATH="C:\Program Files\Stata18\StataMP-64.exe"
   ```

## Building the Project

The project is a mixed Python/Rust project. The high-performance UI sorting is implemented in Rust using [PyO3](https://pyo3.rs/).

### Local Development Build

To build and install the native extension into your current environment for development:

```bash
# Using maturin directly
maturin develop -m native_sorter/Cargo.toml
```

If you don't have `maturin` globally installed, use the version in your venv:
```bash
python -m maturin develop -m native_sorter/Cargo.toml
```

### Building Wheels

To build redistributable wheels for your current platform:

```bash
python -m build
```
Note: This uses `maturin` as the build backend (defined in `pyproject.toml`). It will automatically compile the Rust code and package it with the Python source.

## Testing

The test suite is divided into Python integration/unit tests and native Rust unit tests.

### 1. Rust Native Tests (Core Sorting Logic)

These tests run independently of Python and verify the high-performance sorting algorithms:

```bash
cd native_sorter
cargo test
```

### 2. Python Tests

Python tests are organized with pytest markers:

- **`requires_stata`**: Integration tests that execute real Stata commands.
- **`slow`**: Long-running tests (like build integration).

#### All Tests (Requires Stata)
```bash
pytest
```

#### Tests Without Stata (Fast/CI)
Useful for checking logic, UI components, and parsing without a Stata license:
```bash
pytest -v -m "not requires_stata"
```

#### Native Sorter Integration
Verify the bridge between Python and Rust:
```bash
pytest tests/test_native_sorter.py
```

### 3. Build Integration Tests

We verify that the package builds correctly and all binaries are functional:
```bash
# Run all build integration tests
pytest tests/test_build_integration.py -v -m slow

# Or use the convenience script
./scripts/test_build.sh
```
These tests verify that the package installs in a clean environment and all entry points/extensions function correctly.

### 4. Test Coverage

Generate a coverage report:
```bash
pytest --cov=mcp_stata --cov-report=term-missing
# Or generate an HTML report
pytest --cov=mcp_stata --cov-report=html
open htmlcov/index.html  # View the report
```

### 5. Writing Tests

When adding new tests:

1. **Mark Stata-dependent tests**:
```python
import pytest

# At module level for all tests
pytestmark = pytest.mark.requires_stata

# Or for individual tests
@pytest.mark.requires_stata
def test_my_stata_feature():
    pass
```

2. **Mark slow tests**:
```python
@pytest.mark.slow
def test_expensive_operation():
    pass
```

3. **Platform-specific tests**:
```python
import sys
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
```

## Submitting Changes

### Dependency Management

- Primary dependencies: `pyproject.toml`
- Lock file: `uv.lock`

When adding dependencies:
1. Add to `pyproject.toml`
2. Run `uv lock` (if using uv) to update the lock file.
3. Update build integration tests if the dependency is critical for the server's lifecycle.

### Pull Request Process

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Develop and Test**: 
   - Add Rust tests in `native_sorter/src/lib.rs` if modifying sorting logic.
   - Add Python tests in `tests/`.
   - Ensure `cargo test` and `pytest -v -m "not requires_stata"` pass.

3. **Run build integration tests**:
   ```bash
   ./scripts/test_build.sh
   ```

4. **Commit with clear messages**:
   Follow conventional commits if possible (e.g., `feat:`, `fix:`, `docs:`).

5. **Push and create a pull request**:
   ```bash
   git push origin feature/my-feature
   ```

### CI/CD

GitHub Actions automatically runs on all PRs:
- Runs all non-Stata tests (`pytest -v -m "not requires_stata"`)
- Compiles Rust on Ubuntu and runs native tests
- Tests on Ubuntu with Python 3.12/3.13
- Builds the package and tests entry points

The CI workflow is defined in `.github/workflows/build-test.yml` and `.github/workflows/release.yml`.

## Project Structure

- `src/mcp_stata/`: Python source code.
- `native_sorter/`: Rust source code for the high-performance extension.
- `tests/`: Project integration and unit tests.
- `scripts/`: Utilities for benchmarks, build testing, and version syncing.

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/tmonk/mcp-stata/issues)
- **Discussions**: [GitHub Discussions](https://github.com/tmonk/mcp-stata/discussions)
- **Author**: [Thomas Monk](https://tdmonk.com)

## License

By contributing to mcp-stata, you agree that your contributions will be licensed under the GNU Affero General Public License v3.0 or later.
