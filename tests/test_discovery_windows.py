<<<<<<< Updated upstream
import os
import sys
from pathlib import Path

try:
    from mcp_stata import discovery
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
    from mcp_stata import discovery


def _touch_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stub")
    return path


def test_windows_stata_path_with_quotes(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")

    exe_path = _touch_file(tmp_path / "Program Files" / "Stata18" / "StataMP-64.exe")
    monkeypatch.setenv("STATA_PATH", f'"{exe_path}"')

    path, edition = discovery.find_stata_path()
    assert path == str(exe_path)
    assert edition == "mp"


def test_windows_stata_path_directory_value(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")

    install_dir = tmp_path / "Program Files" / "Stata18"
    exe_path = _touch_file(install_dir / "StataSE-64.exe")
    monkeypatch.setenv("STATA_PATH", f'"{install_dir}"')

    path, edition = discovery.find_stata_path()
    assert path == str(exe_path)
    assert edition == "se"
=======
import os
import sys
from pathlib import Path

try:
    from mcp_stata import discovery
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
    from mcp_stata import discovery


def _touch_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stub")
    return path


def test_windows_stata_path_with_quotes(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")

    exe_path = _touch_file(tmp_path / "Program Files" / "Stata18" / "StataMP-64.exe")
    monkeypatch.setenv("STATA_PATH", f'"{exe_path}"')

    path, edition = discovery.find_stata_path()
    assert path == str(exe_path)
    assert edition == "mp"


def test_windows_stata_path_directory_value(monkeypatch, tmp_path):
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")

    install_dir = tmp_path / "Program Files" / "Stata18"
    exe_path = _touch_file(install_dir / "StataSE-64.exe")
    monkeypatch.setenv("STATA_PATH", f'"{install_dir}"')

    path, edition = discovery.find_stata_path()
    assert path == str(exe_path)
    assert edition == "se"
>>>>>>> Stashed changes
