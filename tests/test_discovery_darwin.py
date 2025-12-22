import stat
import platform
from pathlib import Path

from mcp_stata.discovery import find_stata_path
import pytest
pytestmark = pytest.mark.skipif(platform.system() != "Darwin", reason="Darwin-only discovery tests")


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_darwin_stata_path_env_binary(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    binary_path = _make_executable(
        tmp_path / "Applications" / "StataNow" / "StataMP.app" / "Contents" / "MacOS" / "stata-mp"
    )
    # Quoted path with spaces and app bundle layout
    monkeypatch.setenv("STATA_PATH", f'"{binary_path}"')

    path, edition = find_stata_path()
    assert path == str(binary_path)
    assert edition == "mp"


def test_darwin_stata_path_env_app_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    app_dir = tmp_path / "Applications" / "Stata19Now" / "StataSE.app"
    binary_path = _make_executable(app_dir / "Contents" / "MacOS" / "stata-se")
    monkeypatch.setenv("STATA_PATH", str(app_dir))

    path, edition = find_stata_path()
    assert path == str(binary_path)
    assert edition == "se"


def test_darwin_stata_path_env_plain_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    install_dir = tmp_path / "usr" / "local" / "stata19"
    binary_path = _make_executable(install_dir / "stata")
    monkeypatch.setenv("STATA_PATH", str(install_dir))

    path, edition = find_stata_path()
    assert path == str(binary_path)
    assert edition == "be"
