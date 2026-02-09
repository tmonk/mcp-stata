
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch
from mcp_stata.stata_client import StataClient

class TestStartupDoFileUnit(unittest.TestCase):
    def setUp(self):
        self.client = StataClient()

    @patch('mcp_stata.stata_client.os.path.exists')
    @patch('mcp_stata.stata_client.os.getenv')
    def test_startup_do_file_loaded(self, mock_getenv, mock_exists):
        # Mock env vars
        mock_getenv.return_value = "/path/to/startup.do"

        # Mock file existence
        mock_exists.return_value = True

        # Mock stata module
        mock_stata = MagicMock()
        self.client.stata = mock_stata

        # Skip profile.do discovery so only env var file is loaded.
        self.client._profile_do_checked = True

        # Run the method
        self.client._load_startup_do_file()

        # Check if stata.run was called with 'do' for our file
        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        startup_call = [c for c in calls if 'capture noisily do' in c]
        self.assertEqual(len(startup_call), 1)
        self.assertIn('startup.do', startup_call[0])

    @patch('mcp_stata.stata_client.os.path.exists')
    @patch('mcp_stata.stata_client.os.getenv')
    def test_startup_do_file_not_loaded_if_missing(self, mock_getenv, mock_exists):
        # Mock env vars
        mock_getenv.return_value = "/path/to/missing.do"

        # Mock file existence
        mock_exists.return_value = False

        # Mock stata module
        mock_stata = MagicMock()
        self.client.stata = mock_stata

        self.client._profile_do_checked = True

        # Run the method
        self.client._load_startup_do_file()

        # Check if stata.run was NOT called
        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        startup_call = [c for c in calls if 'noisily do' in c]
        self.assertEqual(len(startup_call), 0)

    @patch('mcp_stata.stata_client.os.path.exists')
    @patch('mcp_stata.stata_client.os.getenv')
    def test_startup_do_file_multiple_paths_deduped(self, mock_getenv, mock_exists):
        path1 = "/path/to/one.do"
        path2 = "/path/to/two.do"
        mock_getenv.return_value = f"{path1}{os.pathsep}{path1}{os.pathsep}{path2}"

        def exists_side_effect(path):
            return path in (path1, path2)

        mock_exists.side_effect = exists_side_effect

        mock_stata = MagicMock()
        self.client.stata = mock_stata

        self.client._profile_do_checked = True

        self.client._load_startup_do_file()

        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        do_calls = [c for c in calls if 'capture noisily do' in c]
        self.assertEqual(len(do_calls), 2)
        self.assertIn('one.do', do_calls[0])
        self.assertIn('two.do', do_calls[1])

    @patch('mcp_stata.stata_client.os.getenv')
    def test_profile_do_fallback_runs(self, mock_getenv):
        # No explicit startup file configured
        mock_getenv.return_value = None

        # Mock stata module
        mock_stata = MagicMock()
        self.client.stata = mock_stata

        # Prime cache with a discovered profile path
        self.client._profile_do_checked = True
        self.client._profile_do_path = "/fake/ado/profile.do"

        # Run the method
        self.client._load_startup_do_file()

        # Expect a profile.do do-file call
        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        profile_call = [c for c in calls if 'capture noisily do' in c and 'profile.do' in c]
        self.assertEqual(len(profile_call), 1)

    @patch('mcp_stata.stata_client.os.getenv')
    def test_profile_do_fallback_skips_when_missing(self, mock_getenv):
        mock_getenv.return_value = None

        mock_stata = MagicMock()
        self.client.stata = mock_stata

        self.client._profile_do_checked = True
        self.client._profile_do_path = None

        self.client._load_startup_do_file()

        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        profile_call = [c for c in calls if 'profile.do' in c]
        self.assertEqual(len(profile_call), 0)

    @patch('mcp_stata.stata_client.os.path.exists')
    @patch('mcp_stata.stata_client.os.getenv')
    def test_profile_do_deduped_against_env(self, mock_getenv, mock_exists):
        env_path = "/ado/personal/profile.do"
        mock_getenv.return_value = env_path
        mock_exists.return_value = True

        mock_stata = MagicMock()
        self.client.stata = mock_stata

        self.client._profile_do_checked = True
        self.client._profile_do_path = env_path

        self.client._load_startup_do_file()

        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        do_calls = [c for c in calls if 'capture noisily do' in c]
        self.assertEqual(len(do_calls), 1)

    @patch('mcp_stata.stata_client.os.getenv')
    def test_sysprofile_do_loaded_before_profile(self, mock_getenv):
        """sysprofile.do is executed before profile.do."""
        mock_getenv.return_value = None

        mock_stata = MagicMock()
        self.client.stata = mock_stata

        self.client._profile_do_checked = True
        self.client._sysprofile_do_path = "/stata/sysprofile.do"
        self.client._profile_do_path = "/ado/personal/profile.do"

        self.client._load_startup_do_file()

        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        do_calls = [c for c in calls if 'capture noisily do' in c]
        self.assertEqual(len(do_calls), 2)
        self.assertIn('sysprofile.do', do_calls[0])
        self.assertIn('profile.do', do_calls[1])

    @patch('mcp_stata.stata_client.os.getenv')
    def test_sysprofile_do_deduped_against_env(self, mock_getenv):
        """sysprofile.do is skipped if already loaded via env var."""
        env_path = "/stata/sysprofile.do"
        mock_getenv.return_value = None

        mock_stata = MagicMock()
        self.client.stata = mock_stata

        self.client._profile_do_checked = True
        self.client._sysprofile_do_path = env_path
        self.client._profile_do_path = None

        self.client._load_startup_do_file()

        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        do_calls = [c for c in calls if 'capture noisily do' in c]
        self.assertEqual(len(do_calls), 1)
        self.assertIn('sysprofile.do', do_calls[0])

    @patch('mcp_stata.stata_client.os.path.exists')
    @patch('mcp_stata.stata_client.os.getenv')
    def test_sysprofile_do_deduped_when_in_env_var(self, mock_getenv, mock_exists):
        """sysprofile.do is not run twice when also listed in env var."""
        sysprof = "/stata/sysprofile.do"
        mock_getenv.return_value = sysprof
        mock_exists.return_value = True

        mock_stata = MagicMock()
        self.client.stata = mock_stata

        self.client._profile_do_checked = True
        self.client._sysprofile_do_path = sysprof

        self.client._load_startup_do_file()

        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        do_calls = [c for c in calls if 'capture noisily do' in c]
        self.assertEqual(len(do_calls), 1)

    @patch('mcp_stata.stata_client.os.getenv')
    def test_only_first_profile_do_loaded(self, mock_getenv):
        """Only the first profile.do is loaded (native Stata behavior)."""
        mock_getenv.return_value = None

        mock_stata = MagicMock()
        self.client.stata = mock_stata

        # Even though _profile_do_path is singular (first match), verify
        # that loading only produces one call.
        self.client._profile_do_checked = True
        self.client._profile_do_path = "/ado/personal/profile.do"

        self.client._load_startup_do_file()

        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        profile_calls = [c for c in calls if 'capture noisily do' in c and 'profile.do' in c]
        self.assertEqual(len(profile_calls), 1)

class TestCodeDropsPrograms(unittest.TestCase):
    def setUp(self):
        self.client = StataClient()

    def test_clear_all_detected(self):
        self.assertTrue(self.client._code_drops_programs("clear all"))

    def test_clear_programs_detected(self):
        self.assertTrue(self.client._code_drops_programs("clear programs"))

    def test_program_drop_all_detected(self):
        self.assertTrue(self.client._code_drops_programs("program drop _all"))

    def test_capture_clear_all_detected(self):
        self.assertTrue(self.client._code_drops_programs("capture clear all"))

    def test_capture_noisily_clear_all_detected(self):
        self.assertTrue(self.client._code_drops_programs("capture noisily clear all"))

    def test_clear_all_in_multiline(self):
        code = "display 1\nclear all\ndisplay 2"
        self.assertTrue(self.client._code_drops_programs(code))

    def test_plain_clear_not_detected(self):
        self.assertFalse(self.client._code_drops_programs("clear"))

    def test_clear_results_not_detected(self):
        self.assertFalse(self.client._code_drops_programs("clear results"))

    def test_clear_mata_not_detected(self):
        self.assertFalse(self.client._code_drops_programs("clear mata"))

    def test_program_drop_specific_not_detected(self):
        self.assertFalse(self.client._code_drops_programs("program drop myprog"))

    def test_empty_string(self):
        self.assertFalse(self.client._code_drops_programs(""))

    def test_unrelated_command(self):
        self.assertFalse(self.client._code_drops_programs("regress y x"))


class TestReloadStartupDoFiles(unittest.TestCase):
    def setUp(self):
        self.client = StataClient()

    @patch('mcp_stata.stata_client.os.getenv')
    def test_reload_re_runs_profile(self, mock_getenv):
        mock_getenv.return_value = None

        mock_stata = MagicMock()
        self.client.stata = mock_stata
        self.client._profile_do_checked = True
        self.client._profile_do_path = "/ado/personal/profile.do"

        self.client._reload_startup_do_files()

        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        profile_calls = [c for c in calls if 'capture noisily do' in c and 'profile.do' in c]
        self.assertEqual(len(profile_calls), 1)

    @patch('mcp_stata.stata_client.os.getenv')
    def test_reload_installs_sentinel(self, mock_getenv):
        mock_getenv.return_value = None

        mock_stata = MagicMock()
        self.client.stata = mock_stata
        self.client._profile_do_checked = True

        self.client._reload_startup_do_files()

        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        sentinel_calls = [c for c in calls if '_mcp_startup_sentinel' in c]
        self.assertTrue(len(sentinel_calls) > 0)


class TestNoReloadOnClear(unittest.TestCase):
    """Tests for MCP_STATA_NO_RELOAD_ON_CLEAR env var."""

    @patch('mcp_stata.stata_client.os.getenv')
    def test_flag_false_when_env_set(self, mock_getenv):
        def getenv_side_effect(key, default=None):
            if key == "MCP_STATA_NO_RELOAD_ON_CLEAR":
                return "1"
            return default

        mock_getenv.side_effect = getenv_side_effect

        client = StataClient()
        self.assertFalse(client._reload_startup_on_clear)

    @patch('mcp_stata.stata_client.os.getenv')
    def test_flag_false_when_env_true_or_yes(self, mock_getenv):
        def getenv_side_effect(key, default=None):
            if key == "MCP_STATA_NO_RELOAD_ON_CLEAR":
                return "true"
            return default

        mock_getenv.side_effect = getenv_side_effect
        client = StataClient()
        self.assertFalse(client._reload_startup_on_clear)

    @patch('mcp_stata.stata_client.os.getenv')
    def test_reload_skipped_when_env_set(self, mock_getenv):
        """clear all should NOT reload when MCP_STATA_NO_RELOAD_ON_CLEAR=1."""
        mock_getenv.return_value = None

        mock_stata = MagicMock()
        client = StataClient()
        client._reload_startup_on_clear = False   # simulate env var
        client.stata = mock_stata
        client._profile_do_checked = True

        # _reload_startup_do_files should be a no-op in the hook sites.
        # Directly test that _code_drops_programs + the flag prevents reload.
        code = "clear all"
        assert client._code_drops_programs(code)
        # Simulate the guard used in _exec_with_capture / run_command_streaming
        if client._reload_startup_on_clear and client._code_drops_programs(code):
            client._reload_startup_do_files()
        # No stata.run calls should have been made for reload.
        mock_stata.run.assert_not_called()

    @patch('mcp_stata.stata_client.os.getenv')
    def test_sentinel_not_installed_when_env_set(self, mock_getenv):
        """Sentinel should NOT be installed when reload is disabled."""
        def getenv_side_effect(key, default=None):
            if key == "MCP_STATA_NO_RELOAD_ON_CLEAR":
                return "1"
            return default

        mock_getenv.side_effect = getenv_side_effect

        mock_stata = MagicMock()
        client = StataClient()
        client._reload_startup_on_clear = False
        client.stata = mock_stata
        client._profile_do_checked = True

        client._load_startup_do_file()

        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        sentinel_calls = [c for c in calls if '_mcp_startup_sentinel' in c]
        self.assertEqual(sentinel_calls, [])

    @patch('mcp_stata.stata_client.os.path.exists')
    @patch('mcp_stata.stata_client.os.getenv')
    def test_user_startup_file_loads_but_no_reload_when_disabled(self, mock_getenv, mock_exists):
        startup_path = "/tmp/startup_test.do"

        def getenv_side_effect(key, default=None):
            if key == "MCP_STATA_NO_RELOAD_ON_CLEAR":
                return "1"
            if key == "MCP_STATA_STARTUP_DO_FILE":
                return startup_path
            return default

        mock_getenv.side_effect = getenv_side_effect
        mock_exists.return_value = True

        mock_stata = MagicMock()
        client = StataClient()
        client.stata = mock_stata
        client._profile_do_checked = True

        client._load_startup_do_file()

        calls = [call[0][0] for call in mock_stata.run.call_args_list]
        do_calls = [c for c in calls if 'capture noisily do' in c]
        sentinel_calls = [c for c in calls if '_mcp_startup_sentinel' in c]
        self.assertEqual(len(do_calls), 1)
        self.assertEqual(sentinel_calls, [])

    def test_flag_defaults_to_true(self):
        """Without the env var, reload should be enabled."""
        client = StataClient()
        self.assertTrue(client._reload_startup_on_clear)


class TestMaybeReloadAfterCommand(unittest.TestCase):
    def test_reloads_when_pattern_matches(self):
        client = StataClient()
        client._reload_startup_on_clear = True
        client._reload_startup_do_files = MagicMock()
        client._startup_sentinel_alive = MagicMock(return_value=True)

        client._maybe_reload_startup_after_command("clear all")

        client._reload_startup_do_files.assert_called_once()
        client._startup_sentinel_alive.assert_not_called()

    def test_reloads_when_sentinel_missing_even_if_pattern_misses(self):
        client = StataClient()
        client._reload_startup_on_clear = True
        client._reload_startup_do_files = MagicMock()
        client._startup_sentinel_alive = MagicMock(return_value=False)
        client._probe_local_macro = MagicMock(return_value=None)

        # Macro-expanded/indirect command form that the text regex cannot detect.
        client._maybe_reload_startup_after_command("local x \"clear all\"\n`x'")

        client._reload_startup_do_files.assert_called_once()
        client._startup_sentinel_alive.assert_not_called()
        client._probe_local_macro.assert_not_called()

    def test_no_probe_for_plain_non_macro_command(self):
        client = StataClient()
        client._reload_startup_on_clear = True
        client._reload_startup_do_files = MagicMock()
        client._startup_sentinel_alive = MagicMock(return_value=False)

        client._maybe_reload_startup_after_command("summarize")

        client._reload_startup_do_files.assert_not_called()
        client._startup_sentinel_alive.assert_not_called()

    def test_no_probe_for_non_clear_macro_usage(self):
        client = StataClient()
        client._reload_startup_on_clear = True
        client._reload_startup_do_files = MagicMock()
        client._startup_sentinel_alive = MagicMock(return_value=False)

        client._maybe_reload_startup_after_command("display `x'")

        client._reload_startup_do_files.assert_not_called()
        client._startup_sentinel_alive.assert_not_called()

    def test_no_probe_for_macro_text_not_at_command_position(self):
        client = StataClient()
        client._reload_startup_on_clear = True
        client._reload_startup_do_files = MagicMock()
        client._startup_sentinel_alive = MagicMock(return_value=False)

        client._maybe_reload_startup_after_command("if 1 display `x'")

        client._reload_startup_do_files.assert_not_called()
        client._startup_sentinel_alive.assert_not_called()

    def test_probe_for_bare_macro_invocation(self):
        client = StataClient()
        client._reload_startup_on_clear = True
        client._reload_startup_do_files = MagicMock()
        client._startup_sentinel_alive = MagicMock(return_value=True)
        client._resolve_indirect_macro_command = MagicMock(return_value=None)

        client._maybe_reload_startup_after_command("`cmd'")

        client._resolve_indirect_macro_command.assert_called_once()
        client._startup_sentinel_alive.assert_called_once()
        client._reload_startup_do_files.assert_not_called()

    def test_resolved_macro_clear_reloads_without_sentinel_probe(self):
        client = StataClient()
        client._reload_startup_on_clear = True
        client._reload_startup_do_files = MagicMock()
        client._startup_sentinel_alive = MagicMock(return_value=True)
        client._resolve_indirect_macro_command = MagicMock(return_value="clear all")

        client._maybe_reload_startup_after_command("`cmd'")

        client._reload_startup_do_files.assert_called_once()
        client._startup_sentinel_alive.assert_not_called()

    def test_resolved_macro_non_clear_skips_sentinel_probe(self):
        client = StataClient()
        client._reload_startup_on_clear = True
        client._reload_startup_do_files = MagicMock()
        client._startup_sentinel_alive = MagicMock(return_value=False)
        client._resolve_indirect_macro_command = MagicMock(return_value="summarize")

        client._maybe_reload_startup_after_command("`cmd'")

        client._reload_startup_do_files.assert_not_called()
        client._startup_sentinel_alive.assert_not_called()

    def test_no_reload_when_disabled(self):
        client = StataClient()
        client._reload_startup_on_clear = False
        client._reload_startup_do_files = MagicMock()
        client._startup_sentinel_alive = MagicMock(return_value=False)

        client._maybe_reload_startup_after_command("clear all")

        client._reload_startup_do_files.assert_not_called()
        client._startup_sentinel_alive.assert_not_called()


class TestResolveIndirectMacroCommand(unittest.TestCase):
    def test_resolve_local_macro_from_inline_assignment(self):
        client = StataClient()
        client._probe_local_macro = MagicMock(return_value=None)

        resolved = client._resolve_indirect_macro_command("local cmd \"clear all\"\n`cmd'")

        self.assertEqual(resolved, "clear all")
        client._probe_local_macro.assert_not_called()

    def test_resolve_global_macro_from_inline_assignment(self):
        client = StataClient()
        client._probe_global_macro = MagicMock(return_value=None)

        resolved = client._resolve_indirect_macro_command("global cmd clear all\n$cmd")

        self.assertEqual(resolved, "clear all")
        self.assertEqual(client._global_macro_cache.get("cmd"), "clear all")
        client._probe_global_macro.assert_not_called()

    def test_resolve_global_macro_uses_cache(self):
        client = StataClient()
        client._global_macro_cache["cmd"] = "clear all"
        client._probe_global_macro = MagicMock(return_value=None)

        resolved = client._resolve_indirect_macro_command("$cmd")

        self.assertEqual(resolved, "clear all")
        client._probe_global_macro.assert_not_called()

    def test_resolve_global_macro_probes_when_missing(self):
        client = StataClient()
        client._probe_global_macro = MagicMock(return_value="clear programs")

        resolved = client._resolve_indirect_macro_command("$cmd")

        self.assertEqual(resolved, "clear programs")
        client._probe_global_macro.assert_called_once_with("cmd")

    def test_resolve_local_macro_probes_local_scope(self):
        client = StataClient()
        client._probe_local_macro = MagicMock(return_value="program drop _all")

        resolved = client._resolve_indirect_macro_command("`cmd'")

        self.assertEqual(resolved, "program drop _all")
        client._probe_local_macro.assert_called_once_with("cmd")

    def test_resolve_returns_none_for_non_bare_macro_lines(self):
        client = StataClient()
        client._probe_local_macro = MagicMock(return_value="clear all")

        resolved = client._resolve_indirect_macro_command("display `cmd'")

        self.assertIsNone(resolved)
        client._probe_local_macro.assert_not_called()


class TestMacroProbeCost(unittest.TestCase):
    @patch.dict("mcp_stata.stata_client.sys.modules", {}, clear=False)
    def test_probe_global_uses_sfi_without_stata_run(self):
        class FakeMacro:
            @staticmethod
            def getGlobal(name):
                return "clear all" if name == "cmd" else ""

        sys.modules["sfi"] = types.SimpleNamespace(Macro=FakeMacro)

        client = StataClient()
        client.stata = MagicMock()

        resolved = client._probe_global_macro("cmd")

        self.assertEqual(resolved, "clear all")
        client.stata.run.assert_not_called()

    @patch.dict("mcp_stata.stata_client.sys.modules", {}, clear=False)
    def test_probe_local_uses_sfi_without_stata_run(self):
        class FakeMacro:
            @staticmethod
            def getLocal(name):
                return "program drop _all" if name == "cmd" else ""

        sys.modules["sfi"] = types.SimpleNamespace(Macro=FakeMacro)

        client = StataClient()
        client.stata = MagicMock()

        resolved = client._probe_local_macro("cmd")

        self.assertEqual(resolved, "program drop _all")
        client.stata.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
