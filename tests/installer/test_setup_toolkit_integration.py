import pytest
import os
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
from types import SimpleNamespace

# Since we're in the repo, we can import directly
repo_root = Path(__file__).parent.parent.parent
sys.path.append(str(repo_root / "scripts" / "install"))

import setup_toolkit

@pytest.fixture
def mock_home(tmp_path):
    # Clear env vars that might override Path.home() based logic
    env_patch = {
        "XDG_CONFIG_HOME": str(tmp_path / ".config"),
        "APPDATA": str(tmp_path / "AppData/Roaming"),
        "USERPROFILE": str(tmp_path),
        "HOME": str(tmp_path)
    }
    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.dict(os.environ, env_patch):
        yield tmp_path

def test_configure_editor_mcp(mock_home):
    # Get platform-specific paths
    vscode_path = setup_toolkit.get_mcp_config_path("vscode", scope="user")
    claude_path = setup_toolkit.get_mcp_config_path("claude_desktop", scope="user")
    
    # Run configuration
    setup_toolkit.configure_editor_mcp("vscode", scope="user")
    setup_toolkit.configure_claude_desktop()
    
    assert vscode_path.exists()
    assert claude_path.exists()
    
    with open(claude_path, "r") as f:
        config = json.load(f)
    assert "mcp-stata" in config["mcpServers"]

def test_configure_codex(mock_home):
    codex_path = mock_home / ".codex/config.toml"
    
    setup_toolkit.configure_codex(scope="user")
    
    assert codex_path.exists()
    with open(codex_path, "r") as f:
        content = f.read()
    assert "[mcp_servers.mcp-stata]" in content
    assert 'command = "uvx"' in content

def test_configure_editor_mcp_existing(mock_home):
    vscode_path = setup_toolkit.get_mcp_config_path("vscode", scope="user")
    vscode_path.parent.mkdir(parents=True, exist_ok=True)
    
    existing_config = {"servers": {"other_server": {"command": "echo"}}}
    with open(vscode_path, "w") as f:
        json.dump(existing_config, f)
        
    setup_toolkit.configure_editor_mcp("vscode", scope="user")
    
    with open(vscode_path, "r") as f:
        config = json.load(f)
    
    assert "other_server" in config["servers"]
    assert "mcp-stata" in config["servers"]

def test_configure_claude_code():
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("subprocess.run") as mock_run:
        setup_toolkit.configure_claude_code()
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "claude" in args
        assert "mcp" in args
        assert "add" in args
        assert "mcp-stata" in args

def test_configure_project_scope_cursor(mock_home):
    project_root = mock_home / "project"
    cfg = project_root / ".cursor" / "mcp.json"
    setup_toolkit.configure_editor_mcp("cursor", scope="project", project_root=project_root)
    data = json.loads(cfg.read_text())
    assert "mcp-stata" in data["mcpServers"]
    assert "env" not in data["mcpServers"]["mcp-stata"]

def test_project_scope_omits_env_when_process_env_is_set(mock_home):
    project_root = mock_home / "project"
    with patch.dict(
        os.environ,
        {
            "STATA_PATH": "/very/wrong/stata/path",
            "MCP_STATA_STARTUP_DO_FILE": "/very/wrong/startup.do",
            "MCP_STATA_TEMP_DIR": "/very/wrong/temp/dir",
        },
        clear=False,
    ):
        cursor_cfg = project_root / ".cursor" / "mcp.json"
        setup_toolkit.configure_editor_mcp("cursor", scope="project", project_root=project_root)
        cursor_data = json.loads(cursor_cfg.read_text())
        assert "env" not in cursor_data["mcpServers"]["mcp-stata"]

        setup_toolkit.configure_claude_code(scope="project", project_root=project_root)
        claude_cfg = project_root / ".mcp.json"
        claude_data = json.loads(claude_cfg.read_text())
        assert "env" not in claude_data["mcpServers"]["mcp-stata"]

        setup_toolkit.configure_codex(scope="project", project_root=project_root)
        codex_cfg = project_root / ".codex" / "config.toml"
        codex_content = codex_cfg.read_text()
        assert "/very/wrong/stata/path" not in codex_content
        assert "/very/wrong/startup.do" not in codex_content
        assert "/very/wrong/temp/dir" not in codex_content
        assert "[mcp_servers.mcp-stata.env]" not in codex_content

def test_reinstall_removes_standalone_claude_config_when_marketplace_available(mock_home):
    claude_cfg = setup_toolkit.get_mcp_config_path("claude_desktop", scope="user")
    claude_cfg.parent.mkdir(parents=True, exist_ok=True)
    claude_cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mcp-stata": {
                        "command": "uvx",
                        "args": ["--from", "mcp-stata@1.0.0", "mcp-stata"],
                        "env": {"STATA_PATH": "/stale/path"},
                    }
                }
            }
        )
    )

    with patch.object(setup_toolkit, "install_claude_marketplace", return_value=True), \
         patch("shutil.which", return_value=None):
        written = setup_toolkit.install_for_agent(
            "claude",
            scope="user",
            version="9.9.9",
            latest=False,
            local_source=None,
            project_root=mock_home / "project",
        )

    data = json.loads(claude_cfg.read_text())
    assert "mcp-stata" not in data["mcpServers"]
    assert written == []  # written is for newly created config paths, but here we only modified (cleaned) existing ones

def test_reinstall_falls_back_to_standalone_claude_on_marketplace_failure(mock_home):
    claude_cfg = setup_toolkit.get_mcp_config_path("claude_desktop", scope="user")
    claude_cfg.parent.mkdir(parents=True, exist_ok=True)
    
    with patch.object(setup_toolkit, "install_claude_marketplace", return_value=False), \
         patch("shutil.which", return_value=None):
        written = setup_toolkit.install_for_agent(
            "claude",
            scope="user",
            version="9.9.9",
            latest=False,
            local_source=None,
            project_root=mock_home / "project",
        )

    data = json.loads(claude_cfg.read_text())
    assert "mcp-stata" in data["mcpServers"]
    assert "mcp-stata@9.9.9" in str(data["mcpServers"]["mcp-stata"]["args"])
    assert claude_cfg in written

def test_reinstall_removes_standalone_codex_config_when_marketplace_available(mock_home):
    project_root = mock_home / "project"
    codex_cfg = project_root / ".codex" / "config.toml"
    codex_cfg.parent.mkdir(parents=True, exist_ok=True)
    codex_cfg.write_text(
        "\n".join(
            [
                "[mcp_servers.mcp-stata]",
                'command = "uvx"',
                'args = ["--from", "mcp-stata@1.0.0", "mcp-stata"]',
                "[mcp_servers.mcp-stata.env]",
                'STATA_PATH = "/stale/path"',
                "",
            ]
        )
    )

    with patch.object(setup_toolkit, "install_codex_marketplace", return_value=True):
        written = setup_toolkit.install_for_agent(
            "codex",
            scope="project",
            version="9.9.9",
            latest=False,
            local_source=None,
            project_root=project_root,
        )

    content = codex_cfg.read_text()
    assert "[mcp_servers.mcp-stata]" not in content
    assert codex_cfg not in written

def test_reinstall_strips_existing_project_placeholder_env_blocks(mock_home):
    project_root = mock_home / "project"
    cursor_cfg = project_root / ".cursor" / "mcp.json"
    cursor_cfg.parent.mkdir(parents=True, exist_ok=True)
    cursor_cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mcp-stata": {
                        "command": "uvx",
                        "args": ["--from", "mcp-stata@1.0.0", "mcp-stata"],
                        "env": {
                            "STATA_PATH": "${STATA_PATH:-}",
                            "MCP_STATA_STARTUP_DO_FILE": "${MCP_STATA_STARTUP_DO_FILE:-}",
                            "MCP_STATA_TEMP_DIR": "${MCP_STATA_TEMP_DIR:-}",
                        },
                    }
                }
            }
        )
    )

    setup_toolkit.configure_editor_mcp("cursor", scope="project", project_root=project_root)
    cursor_data = json.loads(cursor_cfg.read_text())
    assert "env" not in cursor_data["mcpServers"]["mcp-stata"]

    codex_cfg = project_root / ".codex" / "config.toml"
    codex_cfg.parent.mkdir(parents=True, exist_ok=True)
    codex_cfg.write_text(
        "\n".join(
            [
                "[mcp_servers.mcp-stata]",
                'command = "uvx"',
                'args = ["--from", "mcp-stata@1.0.0", "mcp-stata"]',
                "[mcp_servers.mcp-stata.env]",
                'STATA_PATH = "${STATA_PATH:-}"',
                'MCP_STATA_STARTUP_DO_FILE = "${MCP_STATA_STARTUP_DO_FILE:-}"',
                'MCP_STATA_TEMP_DIR = "${MCP_STATA_TEMP_DIR:-}"',
                "",
            ]
        )
    )

    setup_toolkit.configure_codex(scope="project", project_root=project_root)
    codex_content = codex_cfg.read_text()
    assert "[mcp_servers.mcp-stata.env]" not in codex_content
    assert "${STATA_PATH:-}" not in codex_content

def test_build_parser_accepts_verbose_flag():
    parser = setup_toolkit.build_parser()
    args = parser.parse_args(["--verbose"])
    assert args.verbose is True

def test_run_logged_subprocess_appends_full_trace_to_log(mock_home, tmp_path):
    log_path = tmp_path / "install.log"
    with patch.object(setup_toolkit, "INSTALL_LOG_PATH", str(log_path)), \
         patch.object(setup_toolkit, "VERBOSE", False), \
         patch("subprocess.run", return_value=subprocess.CompletedProcess(["echo", "hi"], 0, stdout="hello\n", stderr="warn\n")):
        result = setup_toolkit.run_logged_subprocess(["echo", "hi"], check=True, quiet_console=True)

    assert result.returncode == 0
    log_text = log_path.read_text()
    assert "Running command:" in log_text
    assert "Command exit code: 0" in log_text
    assert "[VERBOSE] stdout:" in log_text
    assert "hello" in log_text
    assert "[VERBOSE] stderr:" in log_text
    assert "warn" in log_text

def test_main_dedupes_claude_desktop_and_claude_code_targets(mock_home):
    targets = [
        SimpleNamespace(name="claude-desktop", display_name="Claude Desktop"),
        SimpleNamespace(name="claude-code", display_name="Claude Code"),
    ]

    with patch.object(setup_toolkit, "check_uv", return_value=True), \
         patch.object(setup_toolkit, "detect_stata", return_value=(None, None)), \
         patch.object(setup_toolkit, "discover_agents", return_value=targets), \
         patch.object(setup_toolkit, "install_for_agent", return_value=[] ) as install_mock:
        rc = setup_toolkit.main([])

    assert rc == 0
    assert install_mock.call_count == 1
    assert install_mock.call_args.args[0] == "claude"

def test_main_reports_shared_claude_configuration_for_both_surfaces(mock_home, capsys):
    targets = [
        SimpleNamespace(name="claude-desktop", display_name="Claude Desktop"),
        SimpleNamespace(name="claude-code", display_name="Claude Code"),
    ]

    with patch.object(setup_toolkit, "check_uv", return_value=True), \
         patch.object(setup_toolkit, "detect_stata", return_value=(None, None)), \
         patch.object(setup_toolkit, "discover_agents", return_value=targets), \
         patch.object(setup_toolkit, "install_for_agent", return_value=[]):
        rc = setup_toolkit.main([])

    out = capsys.readouterr().out
    assert rc == 0
    assert "Agents: Claude Desktop, Claude Code" in out
    assert "Configuring Claude Desktop, Claude Code" in out
    assert "Applied shared configuration for: Claude Desktop, Claude Code" in out

def test_claude_marketplace_reinstall_cleans_our_old_entries_first(mock_home):
    project_root = mock_home / "project"
    calls = []

    def _record(cmd, check=False, **kwargs):
        calls.append((cmd, check))
        return MagicMock(returncode=0)

    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("subprocess.run", side_effect=_record):
        ok = setup_toolkit.install_claude_marketplace(scope="project", project_root=project_root)

    assert ok is True
    expected_prefixes = [
        ["claude", "plugin", "uninstall", "mcp-stata@mcp-stata-marketplace", "--scope", "project"],
        ["claude", "plugin", "uninstall", "mcp-stata", "--scope", "project"],
        ["claude", "plugin", "marketplace", "remove", "mcp-stata-marketplace"],
        ["claude", "plugin", "marketplace", "add", "tmonk/mcp-stata", "--scope", "project"],
        ["claude", "plugin", "install", "mcp-stata@mcp-stata-marketplace", "--scope", "project"],
    ]
    assert [cmd for cmd, _ in calls] == expected_prefixes
    assert [check for _, check in calls] == [False, False, False, False, False]

def test_codex_marketplace_reinstall_cleans_our_old_entries_first(mock_home):
    project_root = mock_home / "project"
    calls = []

    def _record(cmd, check=False, **kwargs):
        calls.append((cmd, check))
        return MagicMock(returncode=0)

    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("subprocess.run", side_effect=_record):
        ok = setup_toolkit.install_codex_marketplace(project_root=project_root)

    assert ok is True
    expected = [
        ["codex", "plugin", "marketplace", "remove", "mcp-stata"],
        ["codex", "plugin", "marketplace", "add", "tmonk/mcp-stata", "--sparse", ".agents/plugins"],
    ]
    assert [cmd for cmd, _ in calls] == expected
    assert [check for _, check in calls] == [False, False]

def test_install_gemini_extension(mock_home):
    link = setup_toolkit.install_gemini_extension()
    assert link.exists()
    assert link.is_symlink()

@pytest.mark.requires_stata
def test_stata_connection_verification():
    # This actually tries to run the verification logic
    # We need to make sure the script can find mcp_stata
    with patch("setup_toolkit.print_success") as mock_success:
        res = setup_toolkit.test_stata_connection()
        # If Stata is installed, this should return True or at least have found Stata
        assert res is True
        # Check if any call matches "Found Stata"
        assert any("Found Stata" in call.args[0] for call in mock_success.call_args_list)


def test_detect_stata_with_fallback():
    # Scenario: MP is found but broken, SE is found and works.
    # setup_toolkit.detect_stata() should return SE.
    mock_candidates = [
        ("/path/to/mp/stata-mp", "mp"),
        ("/path/to/se/stata-se", "se")
    ]
    
    with patch("mcp_stata.discovery.find_stata_candidates", return_value=mock_candidates), \
         patch("mcp_stata.discovery.verify_stata_install") as mock_verify:
        
        # MP fails, SE succeeds
        mock_verify.side_effect = lambda path, edition: edition == "se"
        
        path, edition = setup_toolkit.detect_stata()
        
        assert path == "/path/to/se/stata-se"
        assert edition == "se"
        assert mock_verify.call_count == 2
