import stat
import platform
import shutil
import glob
from pathlib import Path

import pytest

from mcp_stata.discovery import find_stata_path

# Linux-only: these discovery cases rely on Linux filesystem layout/exec bits.
pytestmark = [pytest.mark.skipif(platform.system() != "Linux", reason="Linux-only discovery tests"), pytest.mark.requires_stata]


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_linux_prefers_path_binary(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    binary_path = _make_executable(tmp_path / "bin" / "stata-mp")

    def fake_which(name: str):
        return str(binary_path) if name == "stata-mp" else None

    monkeypatch.setattr(shutil, "which", fake_which)

    path, edition = find_stata_path()
    assert path == str(binary_path)
    assert edition == "mp"


def test_linux_discovers_install_prefix(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(shutil, "which", lambda name: None)

    base_dir = tmp_path / "stata18"
    binary_path = _make_executable(base_dir / "stata-se")

    def fake_glob(pattern: str):
        watched = {
            "/usr/local/stata*",
            "/usr/local/Stata*",
            "/opt/stata*",
            "/opt/Stata*",
            str(tmp_path / "stata"),
            str(tmp_path / "Stata"),
        }
        if pattern in watched or pattern.startswith(str(tmp_path / "stata")) or pattern.startswith(str(tmp_path / "Stata")):
            return [str(base_dir)]
        return []

    monkeypatch.setattr(glob, "glob", fake_glob)

    path, edition = find_stata_path()
    assert path == str(binary_path)
    assert edition == "se"


def test_linux_stata_path_env_binary(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    binary_path = _make_executable(tmp_path / "opt" / "stata19" / "stata-mp")
    monkeypatch.setenv("STATA_PATH", f'"{binary_path}"')

    path, edition = find_stata_path()
    assert path == str(binary_path)
    assert edition == "mp"


def test_linux_stata_path_env_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    install_dir = tmp_path / "usr" / "local" / "stata19"
    binary_path = _make_executable(install_dir / "stata-ic")
    monkeypatch.setenv("STATA_PATH", str(install_dir))

    path, edition = find_stata_path()
    assert path == str(binary_path)
    assert edition == "be"
