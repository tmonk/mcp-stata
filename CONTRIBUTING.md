# Contributing to mcp-stata

Thank you for your interest in contributing to mcp-stata! This guide will help you set up your development environment, run tests, and understand the project structure.

## Table of Contents

- [Development Setup](#development-setup)
- [Building the Package](#building-the-package)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)

## Development Setup

### Prerequisites

- **Stata 17+** (required for integration tests)
- **Python 3.12+**
- **uv** (recommended) or pip

### Installation

1. Clone the repository:
```bash
git clone https://github.com/tmonk/mcp-stata.git
cd mcp-stata
```

2. Install dependencies with uv:
```bash
# Install main dependencies
uv sync --no-install-project

# Install with development dependencies
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

## Building the Package

### Local Build

Build the package locally to test distribution:

```bash
python -m build
```

This creates wheel (`.whl`) and source distribution (`.tar.gz`) files in the `dist/` directory.

### Build Integration Tests

We have comprehensive build integration tests to catch dependency issues before release:

```bash
# Run all build integration tests
pytest tests/test_build_integration.py -v -m slow

# Or use the convenience script
./scripts/test_build.sh
```

These tests:
- Build the package from source
- Install in a clean virtual environment
- Verify all critical imports work
- Check that entry points are installed correctly
- Catch dependency compatibility issues (like the httpx 0.28 incident)

## Testing

### Test Organization

Tests are organized with pytest markers:

- **`requires_stata`**: Tests that need Stata installed (integration, server, token efficiency tests)
- **`slow`**: Long-running tests (build integration tests)
- **`integration`**: Integration tests requiring external resources

### Running Tests

#### All Tests (requires Stata)

```bash
pytest
```

#### Tests Without Stata

Run all tests that don't require Stata (useful for CI or systems without Stata):

```bash
pytest -v -m "not requires_stata"
```

This runs:
- Discovery tests (finding Stata installations)
- SMCL/help parsing tests
- Build integration tests

### Test Coverage

Generate a coverage report:

```bash
pytest --cov=mcp_stata --cov-report=html
open htmlcov/index.html  # View the report
```

### Writing Tests

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

### Dependency Management

- Dependencies are managed in `pyproject.toml`
- Lock file: `uv.lock`

When adding dependencies:

1. Add to `pyproject.toml`
2. Run `uv lock` to update lock file
3. Add build integration tests if the dependency is critical

## Submitting Changes

### Pull Request Process

1. **Create a feature branch**:
```bash
git checkout -b feature/my-feature
```

2. **Make your changes** and add tests

3. **Run the full test suite**:
```bash
# With Stata
pytest

# Without Stata (as CI does)
pytest -v -m "not requires_stata"
```

4. **Run build integration tests**:
```bash
./scripts/test_build.sh
```

5. **Commit with clear messages**:
```bash
git commit -m "Add feature: description of change"
```

6. **Push and create a pull request**:
```bash
git push origin feature/my-feature
```

### CI/CD

GitHub Actions automatically runs on all PRs:

- Runs all non-Stata tests (`pytest -v -m "not requires_stata"`)
- Tests on Ubuntu with Python 3.12
- Builds the package and tests installation
- Verifies critical imports and entry points

The CI workflow is defined in `.github/workflows/build-test.yml`.

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/tmonk/mcp-stata/issues)
- **Discussions**: [GitHub Discussions](https://github.com/tmonk/mcp-stata/discussions)
- **Author**: [Thomas Monk](https://tdmonk.com)

## License

By contributing to mcp-stata, you agree that your contributions will be licensed under the GNU Affero General Public License v3.0 or later.
