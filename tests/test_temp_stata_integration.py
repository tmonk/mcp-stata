import os
import pathlib
import pytest
from unittest.mock import patch, MagicMock
from mcp_stata.stata_client import StataClient
from mcp_stata.utils import get_writable_temp_dir
import mcp_stata.utils

@pytest.fixture
def mock_temp_dir(tmp_path):
    """Force a specific temp dir for the duration of the test."""
    target_dir = str((tmp_path / "stata_temp").resolve())
    os.makedirs(target_dir, exist_ok=True)
    mcp_stata.utils._temp_dir_cache = target_dir
    yield target_dir
    mcp_stata.utils._temp_dir_cache = None

def test_stata_client_uses_registered_temp_dir(mock_temp_dir):
    """Verify that StataClient methods use the validated temp directory."""
    client = StataClient()
    
    # 1. Test SMCL log path
    smcl_path = client._create_smcl_log_path()
    assert smcl_path.startswith(mock_temp_dir)
    assert os.path.dirname(smcl_path) == mock_temp_dir
    
    # 2. Test Streaming log path
    with patch("tempfile.NamedTemporaryFile") as mock_ntf:
        mock_ntf.return_value.name = "/mocked/path.log"
        client._create_streaming_log(trace=False)
        # Check that dir argument was passed correctly
        args, kwargs = mock_ntf.call_args
        assert kwargs["dir"] == mock_temp_dir

    # 3. Test Cache directory
    client._initialize_cache()
    assert client._preemptive_cache_dir.startswith(mock_temp_dir)
    assert os.path.dirname(client._preemptive_cache_dir) == mock_temp_dir

def test_stata_client_export_graph_uses_temp_dir(mock_temp_dir):
    """Verify export_graph uses valid temp directory for filename generation."""
    from unittest.mock import MagicMock
    client = StataClient()
    
    with patch("tempfile.NamedTemporaryFile") as mock_ntf:
        mock_ntf.return_value.__enter__.return_value.name = os.path.join(mock_temp_dir, "graph.pdf")
        
        # Mock resp to be successful
        mock_resp = MagicMock()
        mock_resp.success = True
        
        with patch.object(client, "_exec_no_capture_silent", return_value=mock_resp), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.stat") as mock_stat:
            
            mock_stat.return_value.st_size = 1024
            client.export_graph(format="pdf")
            
            # Find the call for the main export file
            ntf_calls = [call for call in mock_ntf.call_args_list if call.kwargs.get("prefix") == "mcp_stata_"]
            assert any(call.kwargs["dir"] == mock_temp_dir for call in ntf_calls)

def test_registration_during_client_ops(mock_temp_dir):
    """Verify that files created by StataClient are registered for cleanup."""
    client = StataClient()
    
    mcp_stata.utils._files_to_cleanup = set()
    
    smcl_path = client._create_smcl_log_path()
    assert pathlib.Path(smcl_path).absolute() in mcp_stata.utils._files_to_cleanup
    
    # Reset for next check
    mcp_stata.utils._files_to_cleanup = set()
    with patch("tempfile.NamedTemporaryFile") as mock_ntf:
        mock_ntf.return_value.name = os.path.join(mock_temp_dir, "stream.log")
        client._create_streaming_log(trace=False)
        assert pathlib.Path(os.path.join(mock_temp_dir, "stream.log")).absolute() in mcp_stata.utils._files_to_cleanup

def test_registration_cache_init(mock_temp_dir):
    """Verify that cache directory is registered for cleanup."""
    client = StataClient()
    mcp_stata.utils._dirs_to_cleanup = set()
    
    with patch("tempfile.mkdtemp") as mock_mkdtemp:
        mock_mkdtemp.return_value = os.path.join(mock_temp_dir, "cache_dir")
        client._initialize_cache()
        assert pathlib.Path(os.path.join(mock_temp_dir, "cache_dir")).absolute() in mcp_stata.utils._dirs_to_cleanup

def test_registration_graph_export_complex(mock_temp_dir):
    """Verify that all auxiliary files in complex graph export (PNG on Windows) are registered."""
    client = StataClient()
    mcp_stata.utils._files_to_cleanup = set()
    
    # Mock response for silent execution
    mock_resp = MagicMock()
    mock_resp.success = True

    with patch("mcp_stata.stata_client.is_windows", return_value=True), \
         patch.object(pathlib.Path, "exists", return_value=True), \
         patch.object(pathlib.Path, "stat") as mock_path_stat, \
         patch.object(client, "_exec_no_capture_silent", return_value=mock_resp), \
         patch.object(client, "_stata_exec_path", "/path/to/stata", create=True), \
         patch("mcp_stata.stata_client.subprocess.run") as mock_run:
        
        mock_path_stat.return_value.st_size = 1024
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        
        # We need to mock NamedTemporaryFile to return predictable names for registration check
        files = [
            os.path.join(mock_temp_dir, "final.png"),
            os.path.join(mock_temp_dir, "temp.gph"),
            os.path.join(mock_temp_dir, "export.do")
        ]
        
        # Create individual mocks for each call to __enter__
        file_mocks = []
        for f in files:
            m = MagicMock()
            m.name = f
            file_mocks.append(m)
        
        mock_ntf_instance = MagicMock()
        mock_ntf_instance.__enter__.side_effect = file_mocks

        with patch("tempfile.NamedTemporaryFile", return_value=mock_ntf_instance):
            try:
                client.export_graph(format="png")
            except Exception:
                pass # We don't care if it fails later, just checking registration
            
            for f in files:
                assert pathlib.Path(f).absolute() in mcp_stata.utils._files_to_cleanup
            
            # Also check the log file which is derived from do_path
            log_file = os.path.splitext(files[2])[0] + ".log"
            assert pathlib.Path(log_file).absolute() in mcp_stata.utils._files_to_cleanup
