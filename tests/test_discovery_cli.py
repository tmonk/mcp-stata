import os
import sys
from pathlib import Path

import pytest

# Import discovery with source fallback
try:
    from mcp_stata import discovery
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
    from mcp_stata import discovery


def test_discovery_cli_main_success(monkeypatch, tmp_path, capsys):
    # Create a fake executable path and point STATA_PATH at it
    fake_bin = tmp_path / "Program Files" / "Stata18" / "StataMP-64.exe"
    fake_bin.parent.mkdir(parents=True, exist_ok=True)
    fake_bin.write_text("stub")
    monkeypatch.setenv("STATA_PATH", str(fake_bin))
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")

    rc = discovery.main()
    captured = capsys.readouterr().out
    assert rc == 0
    assert "Stata executable" in captured
    assert str(fake_bin) in captured
    assert "mp" in captured


def test_discovery_cli_main_failure(monkeypatch, capsys):
    # Force failure by clearing env and making discovery search empty candidates
    monkeypatch.delenv("STATA_PATH", raising=False)
    monkeypatch.setattr(discovery.platform, "system", lambda: "NowhereOS")

    rc = discovery.main()
    captured = capsys.readouterr().out
    assert rc == 1
    assert "Discovery failed" in captured
