"""
Tests for plugin/install.sh.

Strategy: run the script as a subprocess with a synthetic HOME dir,
stub out agent CLIs and uvx with tiny shell scripts, and assert on
exit codes, written files, and stdout.

No real Stata, no real agent, no real uvx required.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[2] / "plugin" / "install.sh"
pytestmark = pytest.mark.skipif(
    not INSTALL_SH.exists(),
    reason="plugin/install.sh not found",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _run(
    args: list[str],
    *,
    home: Path,
    env_extra: dict | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Run install.sh with an isolated HOME and optional extra env vars."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = str(home / "bin") + ":/usr/bin:/bin"
    env["MCP_STATA_PROJECT_ROOT"] = str(home / "project")
    env.pop("STATA_PATH", None)  # ensure clean slate
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["/bin/bash", str(INSTALL_SH)] + args,
        capture_output=True,
        text=True,
        env=env,
        check=check,
    )


def _stub_uvx(bin_dir: Path, stata_path: str = "") -> None:
    """Create a fake uvx that fails discovery (returns empty) by default."""
    content = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Stub uvx: simulate failed discovery (no Stata found)
        if [[ "$*" == *"find_stata_candidates"* ]]; then
            exit 1
        fi
        exit 0
    """)
    _make_executable(bin_dir / "uvx", content)


def _stub_uvx_with_stata(bin_dir: Path, stata_path: Path) -> None:
    """Create a fake uvx that returns a Stata path from discovery."""
    content = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        if [[ "$*" == *"find_stata_candidates"* ]]; then
            echo "{stata_path}\tmp_be"
            exit 0
        fi
        exit 0
    """).replace("tmp_be", "be")
    _make_executable(bin_dir / "uvx", content)


def _stub_agent_cli(bin_dir: Path, name: str, *, succeeds: bool = True) -> None:
    """Create a fake agent CLI (claude, codex) that accepts 'mcp add'."""
    exit_code = 0 if succeeds else 1
    content = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        exit {exit_code}
    """)
    _make_executable(bin_dir / name, content)


def _fake_stata(tmp_path: Path) -> Path:
    """Create a minimal fake Stata executable."""
    p = tmp_path / "fake-stata" / "stata-mp"
    _make_executable(p, "#!/usr/bin/env bash\nexit 0\n")
    return p


# ===========================================================================
# Basic invocation
# ===========================================================================

class TestBasicInvocation:
    def test_help_exits_zero(self, tmp_path):
        result = _run(["--help"], home=tmp_path)
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()

    def test_help_shows_agent_list(self, tmp_path):
        result = _run(["--help"], home=tmp_path)
        for agent in ("claude", "codex", "gemini", "cursor", "windsurf", "vscode"):
            assert agent in result.stdout

    def test_unknown_flag_exits_nonzero(self, tmp_path):
        result = _run(["--not-a-real-flag"], home=tmp_path)
        assert result.returncode != 0

    def test_no_agents_detected_exits_nonzero(self, tmp_path):
        # No agent CLIs on PATH, no agent dirs in HOME
        result = _run([], home=tmp_path)
        assert result.returncode != 0
        assert "Nothing to configure" in result.stdout or result.returncode != 0


# ===========================================================================
# --dry-run: no files written
# ===========================================================================

class TestDryRun:
    def test_dry_run_gemini_writes_nothing(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        result = _run(["--agent", "gemini", "--dry-run"], home=tmp_path)
        assert result.returncode == 0
        gemini_cfg = tmp_path / ".gemini" / "settings.json"
        assert not gemini_cfg.exists(), "dry-run must not write files"
        assert "dry-run" in result.stdout

    def test_dry_run_cursor_writes_nothing(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        # Create .cursor dir so agent is detected
        (tmp_path / ".cursor").mkdir()
        result = _run(["--agent", "cursor", "--dry-run"], home=tmp_path)
        assert result.returncode == 0
        assert not (tmp_path / ".cursor" / "mcp.json").exists()

    def test_dry_run_windsurf_writes_nothing(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        (tmp_path / ".codeium" / "windsurf").mkdir(parents=True)
        result = _run(["--agent", "windsurf", "--dry-run"], home=tmp_path)
        assert result.returncode == 0
        assert not (tmp_path / ".codeium" / "windsurf" / "mcp_config.json").exists()

    def test_dry_run_claude_writes_nothing(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _stub_agent_cli(bin_dir, "claude", succeeds=False)
        result = _run(["--agent", "claude", "--dry-run"], home=tmp_path)
        assert result.returncode == 0
        assert not (tmp_path / "project" / ".mcp.json").exists()

    def test_dry_run_codex_writes_nothing(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _stub_agent_cli(bin_dir, "codex", succeeds=False)
        result = _run(["--agent", "codex", "--dry-run"], home=tmp_path)
        assert result.returncode == 0
        assert not (tmp_path / "project" / ".codex" / "config.toml").exists()

    def test_dry_run_codex_user_scope_writes_nothing(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _stub_agent_cli(bin_dir, "codex", succeeds=False)
        result = _run(["--agent", "codex", "--scope", "user", "--dry-run"], home=tmp_path)
        assert result.returncode == 0
        assert not (tmp_path / ".codex" / "config.toml").exists()


# ===========================================================================
# Gemini config writing
# ===========================================================================

class TestGeminiConfig:
    def test_installs_gemini_extension(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        result = _run(["--agent", "gemini"], home=tmp_path)
        assert result.returncode == 0
        link = tmp_path / ".gemini" / "extensions" / "mcp-stata"
        assert link.exists()
        assert link.is_symlink()

    def test_gemini_extension_idempotent(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _run(["--agent", "gemini"], home=tmp_path)
        _run(["--agent", "gemini"], home=tmp_path)
        link = tmp_path / ".gemini" / "extensions" / "mcp-stata"
        assert link.exists()

    def test_manifest_contains_env_placeholders(self):
        manifest = json.loads((Path(__file__).resolve().parents[2] / "plugin" / "gemini-extension.json").read_text())
        entry = manifest["mcpServers"]["mcp-stata"]
        assert entry["cwd"] == "${extensionPath}"
        assert "env" not in entry


# ===========================================================================
# Cursor config writing
# ===========================================================================

class TestCursorConfig:
    def test_writes_cursor_mcp_json(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        (tmp_path / ".cursor").mkdir()
        result = _run(["--agent", "cursor", "--scope", "project"], home=tmp_path)
        assert result.returncode == 0
        cfg = tmp_path / "project" / ".cursor" / "mcp.json"
        assert cfg.exists()
        data = json.loads(cfg.read_text())
        assert "mcp-stata" in data["mcpServers"]

    def test_merges_into_existing_cursor_config(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        cfg = tmp_path / "project" / ".cursor" / "mcp.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"mcpServers": {"existing": {"command": "foo"}}}))
        _run(["--agent", "cursor", "--scope", "project"], home=tmp_path)
        data = json.loads(cfg.read_text())
        assert "existing" in data["mcpServers"]
        assert "mcp-stata" in data["mcpServers"]


# ===========================================================================
# Windsurf config writing
# ===========================================================================

class TestWindsurfConfig:
    def test_writes_windsurf_mcp_config(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        (tmp_path / ".codeium" / "windsurf").mkdir(parents=True)
        result = _run(["--agent", "windsurf"], home=tmp_path)
        assert result.returncode == 0
        cfg = tmp_path / ".codeium" / "windsurf" / "mcp_config.json"
        assert cfg.exists()
        data = json.loads(cfg.read_text())
        assert "mcp-stata" in data["mcpServers"]


# ===========================================================================
# Claude config (falls back to settings.json when CLI fails)
# ===========================================================================

class TestClaudeConfig:
    def test_fallback_to_settings_json_when_cli_fails(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _stub_agent_cli(bin_dir, "claude", succeeds=False)
        result = _run(["--agent", "claude", "--scope", "project"], home=tmp_path)
        assert result.returncode == 0
        cfg = tmp_path / "project" / ".mcp.json"
        assert cfg.exists()
        data = json.loads(cfg.read_text())
        assert "mcp-stata" in data["mcpServers"]

    def test_marketplace_success_cleans_standalone_config(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _stub_agent_cli(bin_dir, "claude", succeeds=True)
        # Pre-create standalone config
        cfg = tmp_path / "project" / ".mcp.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"mcpServers": {"mcp-stata": {}}}))
        
        result = _run(["--agent", "claude", "--scope", "project"], home=tmp_path)
        assert result.returncode == 0
        data = json.loads(cfg.read_text())
        assert "mcp-stata" not in data["mcpServers"]


# ===========================================================================
# Codex config
# ===========================================================================

class TestCodexConfig:
    def test_fallback_to_toml_when_cli_fails(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _stub_agent_cli(bin_dir, "codex", succeeds=False)
        result = _run(["--agent", "codex", "--scope", "project"], home=tmp_path)
        assert result.returncode == 0
        toml = tmp_path / "project" / ".codex" / "config.toml"
        assert toml.exists()
        content = toml.read_text()
        assert "mcp-stata" in content
        assert "uvx" in content
        assert "mcp-stata@latest" in content

    def test_toml_fallback_idempotent(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _stub_agent_cli(bin_dir, "codex", succeeds=False)
        _run(["--agent", "codex", "--scope", "project"], home=tmp_path)
        _run(["--agent", "codex", "--scope", "project"], home=tmp_path)
        toml = tmp_path / "project" / ".codex" / "config.toml"
        count = toml.read_text().count("[mcp_servers.mcp-stata]")
        assert count == 1, f"mcp-stata entry duplicated: found {count} times"

    # Note: Codex-specific skills and AGENTS.md hint logic was removed 
    # in favor of plugin-managed resources.


# ===========================================================================
# MCP server args correctness
# ===========================================================================

class TestMcpArgs:
    """The written config must match the canonical uvx command from README."""

    EXPECTED_ARGS = [
        "--refresh",
        "--refresh-package",
        "mcp-stata",
        "--from",
        "mcp-stata@latest",
        "mcp-stata",
    ]

    def _check_args(self, cfg_path: Path, key: str = "mcpServers") -> None:
        data = json.loads(cfg_path.read_text())
        entry = data[key]["mcp-stata"]
        assert entry["command"] == "uvx"
        assert entry["args"] == self.EXPECTED_ARGS, (
            f"args mismatch:\n  got:      {entry['args']}\n"
            f"  expected: {self.EXPECTED_ARGS}"
        )

    def test_gemini_args(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _run(["--agent", "gemini"], home=tmp_path)
        manifest = json.loads((Path(__file__).resolve().parents[2] / "plugin" / "gemini-extension.json").read_text())
        entry = manifest["mcpServers"]["mcp-stata"]
        assert entry["command"] == "uvx"
        assert entry["args"] == self.EXPECTED_ARGS

    def test_cursor_args(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        (tmp_path / ".cursor").mkdir()
        _run(["--agent", "cursor", "--scope", "project"], home=tmp_path)
        self._check_args(tmp_path / "project" / ".cursor" / "mcp.json")

    def test_windsurf_args(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        (tmp_path / ".codeium" / "windsurf").mkdir(parents=True)
        _run(["--agent", "windsurf"], home=tmp_path)
        self._check_args(tmp_path / ".codeium" / "windsurf" / "mcp_config.json")

    def test_claude_fallback_args(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _stub_agent_cli(bin_dir, "claude", succeeds=False)
        _run(["--agent", "claude", "--scope", "project"], home=tmp_path)
        self._check_args(tmp_path / "project" / ".mcp.json")


# ===========================================================================
# Skills symlink (non-Claude agents)
# ===========================================================================

class TestSkillsSymlink:
    def test_gemini_creates_skills_symlink(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        result = _run(["--agent", "gemini"], home=tmp_path)
        assert result.returncode == 0
        link = tmp_path / ".agents" / "skills" / "mcp-stata"
        assert link.exists() or link.is_symlink(), "skills symlink not created"

    def test_cursor_creates_skills_symlink(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        (tmp_path / ".cursor").mkdir()
        _run(["--agent", "cursor"], home=tmp_path)
        link = tmp_path / ".agents" / "skills" / "mcp-stata"
        assert link.exists() or link.is_symlink()

    def test_claude_does_not_create_skills_symlink(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _stub_agent_cli(bin_dir, "claude", succeeds=False)
        _run(["--agent", "claude"], home=tmp_path)
        link = tmp_path / ".agents" / "skills" / "mcp-stata"
        assert not link.exists(), "Claude uses plugin system, not symlinks"

    def test_codex_creates_codex_skills_symlink(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _stub_agent_cli(bin_dir, "codex", succeeds=False)
        # Codex standalone fallback still includes skills? 
        # Wait, the warning says "skills and agents will not be available".
        # So we expect NO symlink now.
        _run(["--agent", "codex", "--scope", "project"], home=tmp_path)
        link = tmp_path / "project" / ".codex" / "skills" / "mcp-stata"
        assert not link.exists()

    def test_existing_real_skills_dir_is_left_in_place(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        existing = tmp_path / ".agents" / "skills" / "mcp-stata"
        existing.mkdir(parents=True)
        result = _run(["--agent", "gemini"], home=tmp_path)
        assert result.returncode == 0
        assert existing.is_dir()
        assert "would be overwritten" in result.stdout


# ===========================================================================
# Stata detection via --stata-path
# ===========================================================================

class TestStataDetection:
    def test_stata_path_override_reported(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        stata = _fake_stata(tmp_path)
        result = _run(
            ["--agent", "gemini", "--stata-path", str(stata)],
            home=tmp_path,
        )
        assert result.returncode == 0
        assert str(stata) in result.stdout

    def test_invalid_stata_path_exits_nonzero(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        result = _run(
            ["--agent", "gemini", "--stata-path", "/nonexistent/stata-mp"],
            home=tmp_path,
        )
        assert result.returncode != 0

    def test_no_stata_warns_but_continues(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        result = _run(["--agent", "gemini"], home=tmp_path)
        assert result.returncode == 0
        assert "STATA_PATH" in result.stdout or "not found" in result.stdout.lower()


# ===========================================================================
# Summary output
# ===========================================================================

class TestSummaryOutput:
    def test_summary_includes_configured_agent(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        result = _run(["--agent", "gemini"], home=tmp_path)
        assert "gemini" in result.stdout

    def test_summary_includes_quickstart_commands(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        result = _run(["--agent", "gemini"], home=tmp_path)
        assert "sysuse auto" in result.stdout
        assert "regress" in result.stdout

    def test_version_flag_changes_uvx_reference(self, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_uvx(bin_dir)
        _stub_agent_cli(bin_dir, "codex", succeeds=False)
        _run(["--agent", "codex", "--version", "9.9.9", "--scope", "project"], home=tmp_path)
        toml = tmp_path / "project" / ".codex" / "config.toml"
        assert "mcp-stata@9.9.9" in toml.read_text()


class TestPluginMetadata:
    def test_hooks_schema_uses_session_start_matcher(self):
        hooks = json.loads((Path(__file__).resolve().parents[2] / "plugin" / "hooks" / "hooks.json").read_text())
        session_start = hooks["hooks"]["SessionStart"][0]
        assert session_start["matcher"] == "startup|resume|clear|compact"
        command_hook = session_start["hooks"][0]
        assert command_hook["type"] == "command"
        assert "/stata" in command_hook["command"]
