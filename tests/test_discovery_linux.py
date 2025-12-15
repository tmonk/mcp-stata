import stat
from pathlib import Path

from mcp_stata import discovery


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_linux_prefers_path_binary(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(discovery.platform, "system", lambda: "Linux")

    binary_path = _make_executable(tmp_path / "bin" / "stata-mp")

    def fake_which(name: str):
        return str(binary_path) if name == "stata-mp" else None

    monkeypatch.setattr(discovery.shutil, "which", fake_which)

    path, edition = discovery.find_stata_path()
    assert path == str(binary_path)
    assert edition == "mp"


def test_linux_discovers_install_prefix(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(discovery.platform, "system", lambda: "Linux")
    monkeypatch.setattr(discovery.shutil, "which", lambda name: None)

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
        if pattern in watched:
            return [str(base_dir)]
        return []

    monkeypatch.setattr(discovery.glob, "glob", fake_glob)

    path, edition = discovery.find_stata_path()
    assert path == str(binary_path)
    assert edition == "se"
