import os
import platform
import pytest
from pathlib import Path

from mcp_stata.discovery import find_stata_path

# limit to Windows
@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")

def _touch_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stub")
    return path


def test_windows_stata_path_with_quotes(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    exe_path = _touch_file(tmp_path / "Program Files" / "Stata18" / "StataMP-64.exe")
    monkeypatch.setenv("STATA_PATH", f'"{exe_path}"')

    path, edition = find_stata_path()
    assert path == str(exe_path)
    assert edition == "mp"


def test_windows_stata_path_directory_value(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    install_dir = tmp_path / "Program Files" / "Stata18"
    exe_path = _touch_file(install_dir / "StataSE-64.exe")
    monkeypatch.setenv("STATA_PATH", f'"{install_dir}"')

    path, edition = find_stata_path()
    assert path == str(exe_path)
    assert edition == "se"


def test_windows_stata_path_with_backslashes(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    exe_path = _touch_file(tmp_path / "Program Files" / "Stata19Now" / "StataMP-64.exe")
    # Simulate a Windows-style env var with backslashes (e.g., C:\Program Files\Stata19Now\StataMP-64.exe)
    windows_style = str(exe_path).replace("/", "\\")
    monkeypatch.setenv("STATA_PATH", windows_style)

    path, edition = find_stata_path()
    assert path == str(exe_path)
    assert edition == "mp"


def test_windows_stata_path_directory_backslashes(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    install_dir = tmp_path / "Program Files" / "Stata19Now"
    exe_path = _touch_file(install_dir / "Stata-64.exe")
    windows_dir = str(install_dir).replace("/", "\\")
    monkeypatch.setenv("STATA_PATH", windows_dir)

    path, edition = find_stata_path()
    assert path == str(exe_path)
    assert edition == "be"


def test_windows_stata_path_with_backslashes_and_quotes(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    exe_path = _touch_file(tmp_path / "Program Files" / "Stata19Now" / "StataMP-64.exe")
    windows_style = str(exe_path).replace("/", "\\")
    monkeypatch.setenv("STATA_PATH", f'"{windows_style}"')

    path, edition = find_stata_path()
    assert path == str(exe_path)
    assert edition == "mp"
