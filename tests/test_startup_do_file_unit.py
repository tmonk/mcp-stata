
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
        startup_call = [c for c in calls if 'noisily do' in c]
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

if __name__ == '__main__':
    unittest.main()
