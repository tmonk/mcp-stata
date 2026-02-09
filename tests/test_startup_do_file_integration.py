import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from mcp_stata.stata_client import StataClient


def test_collect_profile_do_dirs_order(monkeypatch):
    fake_macro_values = {
        "mcp_sysdir_stata": "/opt/stata/",
        "mcp_sysdir_personal": "/ado/personal/",
        "mcp_sysdir_site": "/ado/site/",
        "mcp_sysdir_plus": "/ado/plus/",
        "mcp_sysdir_oldplace": "/ado/oldplace/",
        "mcp_adopath": "/ado/site/\n/ado/plus/\n/ado/extra/",
    }

    class FakeMacro:
        @staticmethod
        def getGlobal(name):
            return fake_macro_values.get(name, "")

    monkeypatch.setitem(sys.modules, "sfi", SimpleNamespace(Macro=FakeMacro))

    client = StataClient()
    client.stata = MagicMock()

    dirs = client._collect_profile_do_dirs()

    cwd = os.getcwd()
    assert dirs == [
        "/opt/stata/",
        cwd,
        "/ado/personal/",
        "/ado/site/",
        "/ado/plus/",
        "/ado/oldplace/",
        "/ado/extra/",
    ]


def test_prime_profile_do_cache_finds_first_match(monkeypatch, tmp_path):
    """_prime_profile_do_cache picks only the first sysprofile.do and profile.do."""
    # Create two directories, each with a profile.do
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "sysprofile.do").write_text("* sys a\n")
    (dir_b / "sysprofile.do").write_text("* sys b\n")
    (dir_a / "profile.do").write_text("* profile a\n")
    (dir_b / "profile.do").write_text("* profile b\n")

    fake_macro_values = {
        "mcp_sysdir_stata": str(dir_a) + "/",
        "mcp_sysdir_personal": str(dir_b) + "/",
        "mcp_sysdir_site": "",
        "mcp_sysdir_plus": "",
        "mcp_sysdir_oldplace": "",
        "mcp_adopath": "",
    }

    class FakeMacro:
        @staticmethod
        def getGlobal(name):
            return fake_macro_values.get(name, "")

    monkeypatch.setitem(sys.modules, "sfi", SimpleNamespace(Macro=FakeMacro))

    client = StataClient()
    client.stata = MagicMock()
    client._prime_profile_do_cache()

    # Only the first match from each search should be cached.
    assert client._sysprofile_do_path == str(dir_a / "sysprofile.do")
    assert client._profile_do_path == str(dir_a / "profile.do")
