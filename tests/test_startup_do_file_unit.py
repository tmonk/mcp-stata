
import os
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


if __name__ == '__main__':
    unittest.main()
