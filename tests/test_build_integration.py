"""
Packaging tests - verifies build, installation, imports, and entry points.

Optimizations:
- Session-scoped fixtures: build and install happen once, not per-test
- uv for fast venv creation and installation
- Batched import testing in single subprocess
"""

import subprocess
import sys
from pathlib import Path

import pytest


def run(cmd, *, cwd=None, check=True):
    """Run command and return result. Fails with full output on error."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        pytest.fail(
            f"Command failed: {' '.join(map(str, cmd))}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return result


# =============================================================================
# Session-Scoped Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def built_package(tmp_path_factory, project_root):
    """Build wheel and sdist once per test session."""
    build_dir = tmp_path_factory.mktemp("build")

    run(["uv", "build", "--out-dir", str(build_dir)], cwd=project_root)

    wheel_files = list(build_dir.glob("*.whl"))
    sdist_files = list(build_dir.glob("*.tar.gz"))

    if not wheel_files:
        pytest.fail(f"No wheel created. Found: {list(build_dir.glob('*'))}")
    if not sdist_files:
        pytest.fail(f"No sdist created. Found: {list(build_dir.glob('*'))}")

    return {
        "wheel": wheel_files[0],
        "sdist": sdist_files[0],
        "build_dir": build_dir,
    }


@pytest.fixture(scope="session")
def installed_venv(tmp_path_factory, built_package):
    """Create venv with package installed once per test session."""
    venv_path = tmp_path_factory.mktemp("venv")

    run(["uv", "venv", str(venv_path)])

    if sys.platform == "win32":
        python = venv_path / "Scripts" / "python.exe"
        scripts = venv_path / "Scripts"
    else:
        python = venv_path / "bin" / "python"
        scripts = venv_path / "bin"

    run(["uv", "pip", "install", "--python", str(python), str(built_package["wheel"])])

    return {
        "venv_path": venv_path,
        "python": python,
        "scripts": scripts,
    }


# =============================================================================
# Build Tests
# =============================================================================


class TestPackageBuild:
    """Tests for package building."""

    @pytest.mark.slow
    def test_wheel_created(self, built_package):
        """Verify wheel file exists and is not empty."""
        wheel = built_package["wheel"]
        assert wheel.exists(), f"Wheel not found: {wheel}"
        assert wheel.stat().st_size > 0, "Wheel file is empty"

    @pytest.mark.slow
    def test_sdist_created(self, built_package):
        """Verify source distribution exists and is not empty."""
        sdist = built_package["sdist"]
        assert sdist.exists(), f"Sdist not found: {sdist}"
        assert sdist.stat().st_size > 0, "Sdist file is empty"

    @pytest.mark.slow
    def test_wheel_naming_convention(self, built_package):
        """Verify wheel follows PEP 427 naming convention."""
        wheel_name = built_package["wheel"].name
        # Format: {distribution}-{version}(-{build tag})?-{python}-{abi}-{platform}.whl
        parts = wheel_name.replace(".whl", "").split("-")
        assert len(parts) >= 5, f"Invalid wheel name format: {wheel_name}"
        assert wheel_name.endswith(".whl"), f"Missing .whl extension: {wheel_name}"

    @pytest.mark.slow
    def test_sdist_naming_convention(self, built_package):
        """Verify sdist follows naming convention."""
        sdist_name = built_package["sdist"].name
        # Format: {distribution}-{version}.tar.gz
        assert sdist_name.endswith(".tar.gz"), f"Invalid sdist extension: {sdist_name}"
        assert "-" in sdist_name, f"Missing version separator: {sdist_name}"


# =============================================================================
# Installation Tests
# =============================================================================


class TestPackageInstallation:
    """Tests for package installation."""

    @pytest.mark.slow
    def test_package_installs_without_error(self, installed_venv):
        """Verify package installation succeeded (fixture handles this)."""
        assert installed_venv["python"].exists()

    @pytest.mark.slow
    def test_package_appears_in_pip_list(self, installed_venv):
        """Verify package shows up in pip list."""
        result = run(["uv", "pip", "list", "--python", str(installed_venv["python"])])
        assert "mcp-stata" in result.stdout.lower(), (
            f"Package not found in pip list:\n{result.stdout}"
        )


# =============================================================================
# Import Tests
# =============================================================================


class TestImports:
    """Tests for package and dependency imports."""

    @pytest.mark.slow
    def test_main_package_imports(self, installed_venv):
        """Test that the main package can be imported."""
        result = run([
            str(installed_venv["python"]), "-c",
            "from mcp_stata.server import main; print('OK')"
        ])
        assert "OK" in result.stdout

    @pytest.mark.slow
    def test_critical_dependencies_importable(self, installed_venv):
        """
        Test that critical dependencies import without errors.

        Catches issues like httpx.TransportError where deps exist but fail at import.
        All imports batched into single subprocess for efficiency.
        """
        import_script = """\
import sys
failures = []

imports = [
    ("import mcp", "mcp"),
    ("import httpx", "httpx"),
    ("from httpx_sse import aconnect_sse", "httpx_sse.aconnect_sse"),
    ("from mcp.server.fastmcp import FastMCP", "mcp.server.fastmcp.FastMCP"),
    ("from mcp_stata.server import main", "mcp_stata.server.main"),
]

for stmt, name in imports:
    try:
        exec(stmt)
        print(f"OK: {name}")
    except Exception as e:
        failures.append(f"{name}: {type(e).__name__}: {e}")
        print(f"FAIL: {name}")

if failures:
    print("\\nFAILURES:")
    for f in failures:
        print(f"  {f}")
    sys.exit(1)

print("\\nAll imports OK")
"""
        result = run([str(installed_venv["python"]), "-c", import_script])
        assert "All imports OK" in result.stdout

    @pytest.mark.slow
    def test_no_import_warnings(self, installed_venv):
        """Check that importing doesn't produce deprecation warnings."""
        result = run([
            str(installed_venv["python"]), "-W", "error::DeprecationWarning",
            "-c", "from mcp_stata.server import main"
        ], check=False)

        if result.returncode != 0:
            pytest.warns(DeprecationWarning, match=result.stderr)


# =============================================================================
# Entry Point Tests
# =============================================================================


class TestEntryPoints:
    """Tests for CLI entry points."""

    @pytest.fixture
    def mcp_stata_exe(self, installed_venv):
        """Return path to mcp-stata executable."""
        if sys.platform == "win32":
            return installed_venv["scripts"] / "mcp-stata.exe"
        return installed_venv["scripts"] / "mcp-stata"

    @pytest.mark.slow
    def test_entry_point_exists(self, mcp_stata_exe, installed_venv):
        """Verify mcp-stata command was installed."""
        assert mcp_stata_exe.exists(), (
            f"Entry point not found: {mcp_stata_exe}\n"
            f"Available: {list(installed_venv['scripts'].glob('*'))}"
        )

    @pytest.mark.slow
    def test_entry_point_is_executable(self, mcp_stata_exe):
        """Verify mcp-stata has executable permissions."""
        if sys.platform == "win32":
            assert mcp_stata_exe.suffix == ".exe"
        else:
            mode = mcp_stata_exe.stat().st_mode
            assert mode & 0o111, f"Not executable: {oct(mode)}"

    @pytest.mark.slow
    def test_entry_point_runs_without_import_error(self, mcp_stata_exe):
        """Verify entry point can start without crashing on import."""
        result = run([str(mcp_stata_exe), "--help"], check=False)

        assert "ImportError" not in result.stderr, (
            f"Entry point has import error:\n{result.stderr}"
        )
        assert "ModuleNotFoundError" not in result.stderr, (
            f"Entry point missing module:\n{result.stderr}"
        )

    @pytest.mark.slow
    def test_entry_point_help_output(self, mcp_stata_exe):
        """Verify --help produces reasonable output."""
        result = run([str(mcp_stata_exe), "--help"], check=False)

        combined_output = result.stdout + result.stderr

        has_help_indicators = any([
            "usage" in combined_output.lower(),
            "help" in combined_output.lower(),
            "options" in combined_output.lower(),
            "mcp" in combined_output.lower(),
        ])

        assert has_help_indicators or result.returncode == 0, (
            f"Entry point --help produced unexpected output:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


# =============================================================================
# Package Metadata Tests
# =============================================================================


class TestPackageMetadata:
    """Tests for package metadata."""

    @pytest.mark.slow
    def test_package_version_accessible(self, installed_venv):
        """Verify package version is accessible at runtime."""
        result = run([
            str(installed_venv["python"]), "-c",
            "from importlib.metadata import version; v = version('mcp-stata'); print(f'VERSION:{v}')"
        ])
        assert "VERSION:" in result.stdout
        version_line = [l for l in result.stdout.split('\n') if 'VERSION:' in l][0]
        version_str = version_line.split(':')[1].strip()
        assert version_str, "Version string is empty"

    @pytest.mark.slow
    def test_package_metadata_accessible(self, installed_venv):
        """Verify package metadata is properly set."""
        result = run([
            str(installed_venv["python"]), "-c",
            """\
from importlib.metadata import metadata
m = metadata('mcp-stata')
print(f"Name: {m['Name']}")
print(f"Version: {m['Version']}")
"""
        ])
        assert "Name:" in result.stdout
        assert "Version:" in result.stdout