
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

if __name__ == '__main__':
    unittest.main()
