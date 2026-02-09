import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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


# ---------------------------------------------------------------------------
# Live Stata tests — require real Stata (``stata_client`` fixture)
# ---------------------------------------------------------------------------

@pytest.mark.requires_stata
class TestClearAllRestoresPrograms:
    """Programs from startup .do files must survive ``clear all``."""

    def test_profile_do_program_survives_clear_all(self, stata_client):
        """add_numbers from profile.do is restored after ``clear all``.

        Relies on the real profile.do at
        ``~/Documents/Stata/ado/personal/profile.do`` being loaded
        during init.  Skipped when no profile.do is discovered.
        """
        client = stata_client
        if not client._profile_do_path:
            pytest.skip("No profile.do discovered — cannot test")

        # Ensure startup programs are loaded (another parallel test may
        # have dropped them without triggering the reload hook).
        client._load_startup_do_file()

        # 1) Confirm add_numbers is available.
        res1 = client.run_command_structured("add_numbers 3 4", echo=False)
        assert res1.rc == 0, f"add_numbers not available at startup: {res1.stdout}"
        assert "7" in res1.stdout

        # 2) clear all — wipes user programs.
        res_clear = client.run_command_structured("clear all", echo=False)
        assert res_clear.rc == 0, f"clear all failed: {res_clear.stdout}"

        # 3) add_numbers should be back (sentinel → reload).
        res2 = client.run_command_structured("add_numbers 10 20", echo=False)
        assert res2.rc == 0, (
            f"add_numbers NOT restored after clear all (rc={res2.rc}): "
            f"{res2.stdout}"
        )
        assert "30" in res2.stdout

    def test_env_startup_program_survives_clear_all(self, stata_client):
        """Program from MCP_STATA_STARTUP_DO_FILE survives ``clear all``.

        Uses a temp .do file so the test is self-contained.
        """
        client = stata_client

        with tempfile.NamedTemporaryFile(
            suffix=".do", mode="w", delete=False
        ) as tf:
            tf.write(
                "capture program drop _test_surv\n"
                "program define _test_surv\n"
                "    display \"survived\"\n"
                "end\n"
            )
            startup_path = tf.name

        old_env = os.environ.get("MCP_STATA_STARTUP_DO_FILE")
        os.environ["MCP_STATA_STARTUP_DO_FILE"] = startup_path

        # Reset profile cache so the next load picks up the env var.
        saved_checked = client._profile_do_checked
        saved_sys = client._sysprofile_do_path
        saved_prof = client._profile_do_path
        try:
            # Load manually (simulates what init() does).
            client._load_startup_do_file()

            # 1) Program available.
            res1 = client.run_command_structured("_test_surv", echo=False)
            assert res1.rc == 0, f"_test_surv not available: {res1.stdout}"
            assert "survived" in res1.stdout

            # 2) clear all.
            client.run_command_structured("clear all", echo=False)

            # 3) Should be restored.
            res2 = client.run_command_structured("_test_surv", echo=False)
            assert res2.rc == 0, (
                f"_test_surv NOT restored after clear all (rc={res2.rc}): "
                f"{res2.stdout}"
            )
            assert "survived" in res2.stdout
        finally:
            # Restore state.
            if old_env is None:
                os.environ.pop("MCP_STATA_STARTUP_DO_FILE", None)
            else:
                os.environ["MCP_STATA_STARTUP_DO_FILE"] = old_env
            client._profile_do_checked = saved_checked
            client._sysprofile_do_path = saved_sys
            client._profile_do_path = saved_prof
            # Clean up temp program.
            try:
                client.stata.run(
                    "capture program drop _test_surv", echo=False
                )
            except Exception:
                pass
            if os.path.exists(startup_path):
                os.unlink(startup_path)

    def test_program_drop_all_restores(self, stata_client):
        """Program from startup .do file survives ``program drop _all``."""
        client = stata_client

        with tempfile.NamedTemporaryFile(
            suffix=".do", mode="w", delete=False
        ) as tf:
            tf.write(
                "capture program drop _test_pdrop\n"
                "program define _test_pdrop\n"
                "    display \"pdrop_ok\"\n"
                "end\n"
            )
            startup_path = tf.name

        old_env = os.environ.get("MCP_STATA_STARTUP_DO_FILE")
        os.environ["MCP_STATA_STARTUP_DO_FILE"] = startup_path

        saved_checked = client._profile_do_checked
        saved_sys = client._sysprofile_do_path
        saved_prof = client._profile_do_path
        try:
            client._load_startup_do_file()

            res1 = client.run_command_structured("_test_pdrop", echo=False)
            assert res1.rc == 0, f"_test_pdrop not available: {res1.stdout}"

            # program drop _all
            client.run_command_structured("program drop _all", echo=False)

            res2 = client.run_command_structured("_test_pdrop", echo=False)
            assert res2.rc == 0, (
                f"_test_pdrop NOT restored after program drop _all: {res2.stdout}"
            )
            assert "pdrop_ok" in res2.stdout
        finally:
            if old_env is None:
                os.environ.pop("MCP_STATA_STARTUP_DO_FILE", None)
            else:
                os.environ["MCP_STATA_STARTUP_DO_FILE"] = old_env
            client._profile_do_checked = saved_checked
            client._sysprofile_do_path = saved_sys
            client._profile_do_path = saved_prof
            try:
                client.stata.run(
                    "capture program drop _test_pdrop", echo=False
                )
            except Exception:
                pass
            if os.path.exists(startup_path):
                os.unlink(startup_path)
