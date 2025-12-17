"""Build integration end-to-end tests.

Tests that verify the package can be built, installed, and imported correctly.
Catches dependency compatibility issues before they reach production.
"""
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path
import pytest


@pytest.fixture
def temp_venv():
    """Create a temporary virtual environment for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        venv_path = Path(tmpdir) / "test_venv"
        yield venv_path


class TestBuildIntegration:
    """End-to-end tests for package build and installation."""

    @pytest.mark.slow
    def test_package_builds_successfully(self, tmp_path):
        """Test that the package can be built without errors."""
        project_root = Path(__file__).parent.parent

        # Build the package
        result = subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(tmp_path)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, f"Build failed:\n{result.stderr}"

        # Verify wheel and sdist were created
        built_files = list(tmp_path.glob("*"))
        wheel_files = list(tmp_path.glob("*.whl"))
        sdist_files = list(tmp_path.glob("*.tar.gz"))

        assert len(wheel_files) > 0, f"No wheel file created. Found: {built_files}"
        assert len(sdist_files) > 0, f"No source distribution created. Found: {built_files}"

    @pytest.mark.slow
    def test_package_imports_cleanly(self, temp_venv, tmp_path):
        """Test that the built package can be installed and imported without errors."""
        project_root = Path(__file__).parent.parent

        # Create virtual environment
        subprocess.run(
            [sys.executable, "-m", "venv", str(temp_venv)],
            check=True,
            timeout=60,
        )

        # Determine python executable in venv
        if sys.platform == "win32":
            python_exe = temp_venv / "Scripts" / "python.exe"
            pip_exe = temp_venv / "Scripts" / "pip.exe"
        else:
            python_exe = temp_venv / "bin" / "python"
            pip_exe = temp_venv / "bin" / "pip"

        # Build the package
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
            cwd=project_root,
            check=True,
            timeout=120,
        )

        # Get the wheel file
        wheel_file = next(tmp_path.glob("*.whl"))

        # Install the wheel in the test venv
        result = subprocess.run(
            [str(pip_exe), "install", str(wheel_file)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, f"Installation failed:\n{result.stderr}"

        # Test that the package can be imported
        import_test = subprocess.run(
            [str(python_exe), "-c", "from mcp_stata.server import main; print('OK')"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert import_test.returncode == 0, (
            f"Import failed:\n"
            f"stdout: {import_test.stdout}\n"
            f"stderr: {import_test.stderr}"
        )
        assert "OK" in import_test.stdout

    @pytest.mark.slow
    def test_critical_dependencies_importable(self, temp_venv, tmp_path):
        """Test that critical dependencies can be imported (catches httpx-type issues)."""
        project_root = Path(__file__).parent.parent

        # Create virtual environment
        subprocess.run(
            [sys.executable, "-m", "venv", str(temp_venv)],
            check=True,
            timeout=60,
        )

        # Determine python executable in venv
        if sys.platform == "win32":
            python_exe = temp_venv / "Scripts" / "python.exe"
            pip_exe = temp_venv / "Scripts" / "pip.exe"
        else:
            python_exe = temp_venv / "bin" / "python"
            pip_exe = temp_venv / "bin" / "pip"

        # Build and install
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
            cwd=project_root,
            check=True,
            timeout=120,
        )

        wheel_file = next(tmp_path.glob("*.whl"))
        subprocess.run(
            [str(pip_exe), "install", str(wheel_file)],
            check=True,
            timeout=120,
        )

        # Test critical imports that have caused issues before
        critical_imports = [
            "import mcp",
            "import httpx",
            "from httpx_sse import aconnect_sse",  # This caused the httpx.TransportError issue
            "from mcp.server.fastmcp import FastMCP",
            "from mcp_stata.server import main",
        ]

        for import_stmt in critical_imports:
            result = subprocess.run(
                [str(python_exe), "-c", f"{import_stmt}; print('OK')"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert result.returncode == 0, (
                f"Failed to import: {import_stmt}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
            assert "OK" in result.stdout, f"Import succeeded but no OK: {import_stmt}"

    @pytest.mark.slow
    def test_server_entry_point_exists(self, temp_venv, tmp_path):
        """Test that the mcp-stata command entry point is installed correctly."""
        project_root = Path(__file__).parent.parent

        # Create virtual environment
        subprocess.run(
            [sys.executable, "-m", "venv", str(temp_venv)],
            check=True,
            timeout=60,
        )

        # Determine executables
        if sys.platform == "win32":
            pip_exe = temp_venv / "Scripts" / "pip.exe"
            mcp_stata_exe = temp_venv / "Scripts" / "mcp-stata.exe"
        else:
            pip_exe = temp_venv / "bin" / "pip"
            mcp_stata_exe = temp_venv / "bin" / "mcp-stata"

        # Build and install
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
            cwd=project_root,
            check=True,
            timeout=120,
        )

        wheel_file = next(tmp_path.glob("*.whl"))
        subprocess.run(
            [str(pip_exe), "install", str(wheel_file)],
            check=True,
            timeout=120,
        )

        # Verify entry point exists
        assert mcp_stata_exe.exists(), f"mcp-stata entry point not found at {mcp_stata_exe}"

        # Verify it's executable
        assert mcp_stata_exe.stat().st_mode & 0o111, "mcp-stata is not executable"

    # @pytest.mark.slow
    # def test_dependency_constraints_enforced(self, temp_venv, tmp_path):
    #     """Test that dependency constraints in pyproject.toml are properly enforced."""
    #     project_root = Path(__file__).parent.parent

    #     # Create virtual environment
    #     subprocess.run(
    #         [sys.executable, "-m", "venv", str(temp_venv)],
    #         check=True,
    #         timeout=60,
    #     )

    #     # Determine executables
    #     if sys.platform == "win32":
    #         python_exe = temp_venv / "Scripts" / "python.exe"
    #         pip_exe = temp_venv / "Scripts" / "pip.exe"
    #     else:
    #         python_exe = temp_venv / "bin" / "python"
    #         pip_exe = temp_venv / "bin" / "pip"

    #     # Build and install
    #     subprocess.run(
    #         [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
    #         cwd=project_root,
    #         check=True,
    #         timeout=120,
    #     )

    #     wheel_file = next(tmp_path.glob("*.whl"))
    #     subprocess.run(
    #         [str(pip_exe), "install", str(wheel_file)],
    #         check=True,
    #         timeout=120,
    #     )

    #     # Check httpx version is constrained correctly (should be 0.27.x, not 0.28+)
    #     version_check = subprocess.run(
    #         [str(python_exe), "-c", "import httpx; print(httpx.__version__)"],
    #         capture_output=True,
    #         text=True,
    #         timeout=30,
    #     )

    #     assert version_check.returncode == 0, f"Failed to get httpx version:\n{version_check.stderr}"
    #     httpx_version = version_check.stdout.strip()

    #     # Parse version
    #     major, minor, *_ = httpx_version.split(".")
    #     assert int(major) == 0, f"Unexpected httpx major version: {httpx_version}"
    #     assert int(minor) == 27, (
    #         f"httpx version {httpx_version} doesn't match constraint >=0.27.0,<0.28.0. "
    #         "This could cause httpx_sse compatibility issues."
    #     )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "slow"])
