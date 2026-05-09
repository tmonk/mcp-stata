"""Unit tests for scripts/sync_server_version.py."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Load the script as a module without requiring hatch / Stata at import time
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "maintenance" / "sync_server_version.py"


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_server_version", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sync = _load_sync_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _write_md(path: Path, frontmatter: str, body: str = "# Body\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n\n{body}")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


# ===========================================================================
# sync_json_toplevel
# ===========================================================================

class TestSyncJsonToplevel:
    def test_updates_version(self, tmp_path):
        p = tmp_path / "plugin.json"
        _write_json(p, {"name": "mcp-stata", "version": "1.0.0"})
        changed = sync.sync_json_toplevel(p, "2.0.0")
        assert changed is True
        assert _read_json(p)["version"] == "2.0.0"

    def test_preserves_other_fields(self, tmp_path):
        p = tmp_path / "plugin.json"
        _write_json(p, {"name": "mcp-stata", "version": "1.0.0", "author": "Tom"})
        sync.sync_json_toplevel(p, "2.0.0")
        data = _read_json(p)
        assert data["name"] == "mcp-stata"
        assert data["author"] == "Tom"

    def test_idempotent(self, tmp_path):
        p = tmp_path / "plugin.json"
        _write_json(p, {"version": "2.0.0"})
        changed = sync.sync_json_toplevel(p, "2.0.0")
        assert changed is False

    def test_missing_file_warns_and_returns_false(self, tmp_path, capsys):
        p = tmp_path / "nonexistent.json"
        changed = sync.sync_json_toplevel(p, "2.0.0")
        assert changed is False
        assert "Warning" in capsys.readouterr().err

    def test_output_is_valid_json_with_trailing_newline(self, tmp_path):
        p = tmp_path / "plugin.json"
        _write_json(p, {"version": "1.0.0"})
        sync.sync_json_toplevel(p, "2.0.0")
        raw = p.read_text()
        assert raw.endswith("\n")
        json.loads(raw)  # must parse cleanly


# ===========================================================================
# sync_json_nested
# ===========================================================================

class TestSyncJsonNested:
    def _marketplace(self, version: str) -> dict:
        return {
            "name": "mcp-stata",
            "plugins": [{"name": "mcp-stata", "version": version}],
        }

    def test_updates_nested_version(self, tmp_path):
        p = tmp_path / "marketplace.json"
        _write_json(p, self._marketplace("1.0.0"))
        changed = sync.sync_json_nested(p, "2.0.0")
        assert changed is True
        data = _read_json(p)
        assert data["plugins"][0]["version"] == "2.0.0"

    def test_idempotent(self, tmp_path):
        p = tmp_path / "marketplace.json"
        _write_json(p, self._marketplace("2.0.0"))
        changed = sync.sync_json_nested(p, "2.0.0")
        assert changed is False

    def test_updates_all_plugin_entries(self, tmp_path):
        p = tmp_path / "marketplace.json"
        _write_json(p, {
            "plugins": [
                {"name": "a", "version": "1.0.0"},
                {"name": "b", "version": "1.0.0"},
            ]
        })
        sync.sync_json_nested(p, "3.0.0")
        data = _read_json(p)
        assert all(e["version"] == "3.0.0" for e in data["plugins"])

    def test_no_plugins_key_is_no_op(self, tmp_path):
        p = tmp_path / "marketplace.json"
        _write_json(p, {"name": "mcp-stata"})
        changed = sync.sync_json_nested(p, "2.0.0")
        assert changed is False

    def test_missing_file_warns_and_returns_false(self, tmp_path, capsys):
        p = tmp_path / "nonexistent.json"
        changed = sync.sync_json_nested(p, "2.0.0")
        assert changed is False
        assert "Warning" in capsys.readouterr().err


# ===========================================================================
# sync_markdown_frontmatter
# ===========================================================================

class TestSyncMarkdownFrontmatter:
    def test_updates_version_in_frontmatter(self, tmp_path):
        p = tmp_path / "SKILL.md"
        _write_md(p, "name: stata-toolkit\nversion: 1.0.0\n")
        changed = sync.sync_markdown_frontmatter(p, "2.0.0")
        assert changed is True
        assert "version: 2.0.0" in p.read_text()

    def test_idempotent(self, tmp_path):
        p = tmp_path / "SKILL.md"
        _write_md(p, "name: stata-toolkit\nversion: 2.0.0\n")
        changed = sync.sync_markdown_frontmatter(p, "2.0.0")
        assert changed is False

    def test_does_not_alter_body_content(self, tmp_path):
        p = tmp_path / "SKILL.md"
        body = "version: old content in body should survive\n"
        _write_md(p, "version: 1.0.0\n", body)
        sync.sync_markdown_frontmatter(p, "2.0.0")
        text = p.read_text()
        # frontmatter version updated
        assert "version: 2.0.0" in text
        # body line unchanged (only first frontmatter occurrence replaced)
        assert "version: old content in body should survive" in text

    def test_no_version_in_frontmatter_returns_false(self, tmp_path):
        p = tmp_path / "SKILL.md"
        _write_md(p, "name: stata-toolkit\n")
        changed = sync.sync_markdown_frontmatter(p, "2.0.0")
        assert changed is False

    def test_missing_file_warns_and_returns_false(self, tmp_path, capsys):
        p = tmp_path / "nonexistent.md"
        changed = sync.sync_markdown_frontmatter(p, "2.0.0")
        assert changed is False
        assert "Warning" in capsys.readouterr().err

    def test_preserves_other_frontmatter_fields(self, tmp_path):
        p = tmp_path / "SKILL.md"
        _write_md(p, "name: stata-toolkit\nversion: 1.0.0\nauthor: Tom\n")
        sync.sync_markdown_frontmatter(p, "2.0.0")
        text = p.read_text()
        assert "name: stata-toolkit" in text
        assert "author: Tom" in text


# ===========================================================================
# sync_server_json
# ===========================================================================

class TestSyncServerJson:
    def _server_json(self, version: str) -> dict:
        return {
            "version": version,
            "packages": [{"identifier": "mcp-stata", "version": version}],
        }

    def test_updates_top_level_version(self, tmp_path, monkeypatch):
        p = tmp_path / "server.json"
        _write_json(p, self._server_json("1.0.0"))
        monkeypatch.setattr(sync, "SERVER_JSON", p)
        changed = sync.sync_server_json("2.0.0")
        assert changed is True
        assert _read_json(p)["version"] == "2.0.0"

    def test_updates_package_version(self, tmp_path, monkeypatch):
        p = tmp_path / "server.json"
        _write_json(p, self._server_json("1.0.0"))
        monkeypatch.setattr(sync, "SERVER_JSON", p)
        sync.sync_server_json("2.0.0")
        data = _read_json(p)
        assert data["packages"][0]["version"] == "2.0.0"

    def test_idempotent(self, tmp_path, monkeypatch):
        p = tmp_path / "server.json"
        _write_json(p, self._server_json("2.0.0"))
        monkeypatch.setattr(sync, "SERVER_JSON", p)
        changed = sync.sync_server_json("2.0.0")
        assert changed is False

    def test_missing_server_json_exits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SERVER_JSON", tmp_path / "missing.json")
        with pytest.raises(SystemExit):
            sync.sync_server_json("2.0.0")

    def test_non_mcp_stata_package_not_updated(self, tmp_path, monkeypatch):
        p = tmp_path / "server.json"
        _write_json(p, {
            "version": "1.0.0",
            "packages": [{"identifier": "other-pkg", "version": "1.0.0"}],
        })
        monkeypatch.setattr(sync, "SERVER_JSON", p)
        sync.sync_server_json("2.0.0")
        data = _read_json(p)
        assert data["packages"][0]["version"] == "1.0.0"  # untouched


# ===========================================================================
# main() — integration with mocked get_version and full plugin tree
# ===========================================================================

class TestMain:
    def _build_plugin_tree(self, root: Path, version: str) -> None:
        """Create a minimal plugin directory mirroring real structure."""
        # JSON top-level
        for rel in [
            ".claude-plugin/plugin.json",
            ".codex-plugin/plugin.json",
            "gemini-extension.json",
        ]:
            _write_json(root / rel, {"name": "mcp-stata", "version": version})

        # JSON nested
        _write_json(root / ".agents/plugins/marketplace.json", {
            "plugins": [{"name": "mcp-stata", "version": version}]
        })
        _write_json(root / ".claude-plugin/marketplace.json", {
            "plugins": [{"name": "mcp-stata", "version": version}]
        })

        # Markdown skills and manifests
        for skill in ["stata-toolkit", "stata-run", "stata-inspect"]:
            _write_md(
                root / "skills" / skill / "SKILL.md",
                f"name: {skill}\ndescription: {skill} description\n",
            )
            _write_json(root / "skills" / skill / "manifest.json", {"version": version})

        # Markdown agents and manifests
        for agent in ["stata-analyst", "stata-debugger"]:
            _write_md(
                root / "agents" / f"{agent}.md",
                f"name: {agent}\ndescription: {agent} description\n",
            )
            _write_json(root / "agents" / f"{agent}.manifest.json", {"version": version})

    def test_main_updates_all_files(self, tmp_path, monkeypatch, capsys):
        server = tmp_path / "server.json"
        _write_json(server, {
            "version": "1.0.0",
            "packages": [{"identifier": "mcp-stata", "version": "1.0.0"}],
        })
        plugin = tmp_path / "plugin"
        self._build_plugin_tree(plugin, "1.0.0")

        monkeypatch.setattr(sync, "SERVER_JSON", server)
        monkeypatch.setattr(sync, "PLUGIN_DIR", plugin)
        monkeypatch.setattr(sync, "PLUGIN_JSON_FILES", [
            plugin / ".claude-plugin/plugin.json",
            plugin / ".codex-plugin/plugin.json",
            plugin / "gemini-extension.json",
        ])
        monkeypatch.setattr(sync, "PLUGIN_JSON_NESTED", [
            plugin / ".agents/plugins/marketplace.json",
            plugin / ".claude-plugin/marketplace.json",
        ])
        monkeypatch.setattr(sync, "PLUGIN_MANIFEST_GLOB", [
            plugin / "skills" / "*" / "manifest.json",
            plugin / "agents" / "*.manifest.json",
        ])
        monkeypatch.setattr(sync, "CATALOG_GENERATOR", tmp_path / "missing.py")
        monkeypatch.setattr(sync, "get_version", lambda: "2.0.0")

        sync.main()

        # server.json
        assert _read_json(server)["version"] == "2.0.0"
        # plugin JSON
        assert _read_json(plugin / ".claude-plugin/plugin.json")["version"] == "2.0.0"
        assert _read_json(plugin / ".codex-plugin/plugin.json")["version"] == "2.0.0"
        assert _read_json(plugin / "gemini-extension.json")["version"] == "2.0.0"
        # marketplace nested
        data = _read_json(plugin / ".agents/plugins/marketplace.json")
        assert data["plugins"][0]["version"] == "2.0.0"
        data = _read_json(plugin / ".claude-plugin/marketplace.json")
        assert data["plugins"][0]["version"] == "2.0.0"
        # manifests
        for skill in ["stata-toolkit", "stata-run", "stata-inspect"]:
            data = _read_json(plugin / "skills" / skill / "manifest.json")
            assert data["version"] == "2.0.0"
        for agent in ["stata-analyst", "stata-debugger"]:
            data = _read_json(plugin / "agents" / f"{agent}.manifest.json")
            assert data["version"] == "2.0.0"

        out = capsys.readouterr().out
        assert "2.0.0" in out

    def test_main_reports_already_up_to_date(self, tmp_path, monkeypatch, capsys):
        server = tmp_path / "server.json"
        _write_json(server, {"version": "2.0.0", "packages": []})
        plugin = tmp_path / "plugin"
        self._build_plugin_tree(plugin, "2.0.0")

        monkeypatch.setattr(sync, "SERVER_JSON", server)
        monkeypatch.setattr(sync, "PLUGIN_DIR", plugin)
        monkeypatch.setattr(sync, "PLUGIN_JSON_FILES", [
            plugin / ".claude-plugin/plugin.json",
        ])
        monkeypatch.setattr(sync, "PLUGIN_JSON_NESTED", [])
        monkeypatch.setattr(sync, "PLUGIN_MANIFEST_GLOB", [])
        monkeypatch.setattr(sync, "CATALOG_GENERATOR", tmp_path / "missing.py")
        monkeypatch.setattr(sync, "get_version", lambda: "2.0.0")

        sync.main()
        out = capsys.readouterr().out
        assert "0 file(s) updated" in out

    def test_main_partial_update(self, tmp_path, monkeypatch, capsys):
        """Only stale files get 'updated' label; current files get 'ok'."""
        server = tmp_path / "server.json"
        _write_json(server, {"version": "2.0.0", "packages": []})
        plugin = tmp_path / "plugin"
        # One file at old version, one at new
        _write_json(plugin / ".claude-plugin/plugin.json", {"version": "1.0.0"})
        _write_json(plugin / ".codex-plugin/plugin.json", {"version": "2.0.0"})

        monkeypatch.setattr(sync, "SERVER_JSON", server)
        monkeypatch.setattr(sync, "PLUGIN_DIR", plugin)
        monkeypatch.setattr(sync, "PLUGIN_JSON_FILES", [
            plugin / ".claude-plugin/plugin.json",
            plugin / ".codex-plugin/plugin.json",
        ])
        monkeypatch.setattr(sync, "PLUGIN_JSON_NESTED", [])
        monkeypatch.setattr(sync, "PLUGIN_MANIFEST_GLOB", [])
        monkeypatch.setattr(sync, "CATALOG_GENERATOR", tmp_path / "missing.py")
        monkeypatch.setattr(sync, "get_version", lambda: "2.0.0")

        sync.main()
        out = capsys.readouterr().out
        assert "1 file(s) updated" in out

    def test_real_plugin_dir_all_at_current_version(self, monkeypatch, capsys):
        """Smoke test: real plugin/ tree should already be at current version."""
        real_root = Path(__file__).resolve().parents[2]
        real_version = json.loads(
            (real_root / "pyproject.toml").read_text().split('version = "')[1].split('"')[0]
            if False else "{}"  # avoid TOML parsing — read pyproject directly
        )
        # Read version directly from pyproject.toml
        text = (real_root / "pyproject.toml").read_text()
        import re
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        assert m, "Could not parse version from pyproject.toml"
        version = m.group(1)

        monkeypatch.setattr(sync, "get_version", lambda: version)
        sync.main()
        out = capsys.readouterr().out
        # No files should need updating — 0 file(s) updated
        assert "0 file(s) updated" in out

    def test_main_runs_catalog_generator_when_present(self, tmp_path, monkeypatch):
        server = tmp_path / "server.json"
        _write_json(server, {"version": "2.0.0", "packages": []})
        plugin = tmp_path / "plugin"
        self._build_plugin_tree(plugin, "2.0.0")
        generator = tmp_path / "generate.py"
        generator.write_text("print('generated')\n")

        monkeypatch.setattr(sync, "SERVER_JSON", server)
        monkeypatch.setattr(sync, "PLUGIN_DIR", plugin)
        monkeypatch.setattr(sync, "PLUGIN_JSON_FILES", [])
        monkeypatch.setattr(sync, "PLUGIN_JSON_NESTED", [])
        monkeypatch.setattr(sync, "PLUGIN_MANIFEST_GLOB", [])
        monkeypatch.setattr(sync, "CATALOG_GENERATOR", generator)
        monkeypatch.setattr(sync, "get_version", lambda: "2.0.0")

        called = {}

        def fake_check_call(args, cwd=None):
            called["args"] = args
            called["cwd"] = cwd

        monkeypatch.setattr(sync.subprocess, "check_call", fake_check_call)
        sync.main()
        assert called["args"][1] == str(generator)
