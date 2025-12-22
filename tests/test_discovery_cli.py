import platform

from mcp_stata import discovery


def test_discovery_cli_main_success(monkeypatch, tmp_path, capsys):
    # Create a fake executable path and point STATA_PATH at it
    fake_bin = tmp_path / "Program Files" / "Stata18" / "StataMP-64.exe"
    fake_bin.parent.mkdir(parents=True, exist_ok=True)
    fake_bin.write_text("stub")
    monkeypatch.setenv("STATA_PATH", str(fake_bin))
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    rc = discovery.main()
    captured = capsys.readouterr().out
    assert rc == 0
    assert "Stata executable" in captured
    assert str(fake_bin) in captured
    assert "mp" in captured


def test_discovery_cli_main_failure(monkeypatch, capsys):
    # Force failure by making discovery search empty candidates
    monkeypatch.delenv("STATA_PATH", raising=False)
    
    # Mock _detect_system directly to bypass os.name check
    monkeypatch.setattr(discovery, "_detect_system", lambda: "NowhereOS")
    
    rc = discovery.main()
    captured = capsys.readouterr().out
    assert rc == 1
    assert "Discovery failed" in captured
