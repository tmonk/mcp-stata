import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from mcp_stata.stata_client import StataClient


def test_collect_profile_do_dirs_order(monkeypatch):
    fake_macro_values = {
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

    assert dirs == [
        "/ado/personal/",
        "/ado/site/",
        "/ado/plus/",
        "/ado/oldplace/",
        "/ado/extra/",
    ]
