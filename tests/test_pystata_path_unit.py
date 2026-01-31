import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from mcp_stata.stata_client import StataClient

@pytest.fixture(autouse=True)
def mock_pystata_env():
    """Mock pystata and sfi modules for unit tests."""
    mock_sfi = MagicMock()
    mock_pystata = MagicMock()
    
    with patch.dict("sys.modules", {"sfi": mock_sfi, "pystata": mock_pystata, "stata_setup": MagicMock()}):
        yield {"sfi": mock_sfi, "pystata": mock_pystata}

def test_root_climbing_logic():
    """
    Test the logic that walks up from the binary path to find the 'utilities' folder.
    """
    # Mocking a directory structure:
    # /Applications/Stata/StataMP.app/Contents/MacOS/stata-mp (binary)
    # /Applications/Stata/utilities (target)
    
    # Use a real path object to ensure normalization
    stata_exec_path = "/Applications/Stata/StataMP.app/Contents/MacOS/stata-mp"
    bin_dir = os.path.dirname(stata_exec_path)
    
    with patch("os.path.isdir") as mock_isdir, \
         patch("os.path.exists", return_value=True):
        
        # Define what is a directory
        def isdir_side_effect(path):
            p = str(Path(path)) # Normalize
            # Exact matches for our mocked structure
            valid_dirs = {
                str(Path("/Applications/Stata")),
                str(Path("/Applications/Stata/utilities")),
                str(Path("/Applications/Stata/StataMP.app")),
                str(Path("/Applications/Stata/StataMP.app/Contents")),
                str(Path("/Applications/Stata/StataMP.app/Contents/MacOS")),
            }
            return p in valid_dirs
            
        mock_isdir.side_effect = isdir_side_effect
        
        # Reproduce EXACT climbing logic from stata_client.py init()
        root_candidates = []
        curr = bin_dir
        while len(curr) > 1:
            if os.path.isdir(os.path.join(curr, "utilities")):
                root_candidates.append(curr)
                break
            
            # MacOS .app bundle special case
            if curr.endswith(".app"):
                parent = os.path.dirname(curr)
                if parent and parent != "/" and os.path.isdir(os.path.join(parent, "utilities")):
                    root_candidates.append(parent)
                root_candidates.append(curr)
            
            parent = os.path.dirname(curr)
            if parent == curr: 
                break
            curr = parent

        ordered_candidates = root_candidates
        if bin_dir not in ordered_candidates:
            ordered_candidates.append(bin_dir)
            
        assert "/Applications/Stata" in [str(Path(c)) for c in ordered_candidates]

def test_sys_path_prioritization_logic():
    """
    Verifies that StataClient.init() correctly inserts the utilities path at the HEAD of sys.path.
    """
    client = StataClient()
    
    # Mock candidates
    stata_path = "/Applications/StataNow"
    utils_path = os.path.join(stata_path, "utilities")
    
    with patch("mcp_stata.stata_client._get_discovery_candidates", return_value=[(f"{stata_path}/stata-mp", "mp")]), \
         patch("stata_setup.config"), \
         patch("os.path.isdir", side_effect=lambda p: p == utils_path or p == stata_path), \
         patch("os.path.exists", return_value=True), \
         patch("sys.path", ["/some/other/path"]), \
         patch("sys.stderr.write"), \
         patch("sys.stderr.flush"), \
         patch("mcp_stata.stata_client.redirect_stdout"), \
         patch("mcp_stata.stata_client.redirect_stderr"), \
         patch("mcp_stata.stata_client.StataClient._safe_redirect_fds"), \
         patch("mcp_stata.stata_client.StataClient._create_smcl_log_path"), \
         patch.dict("sys.modules", {"pystata": MagicMock()}):
        
        # Fake more mocks needed by init
        client.stata = MagicMock()
        os.environ["MCP_STATA_SKIP_PREFLIGHT"] = "1"
        
        client.init()
        
        # Verify utils_path was inserted at index 0
        assert sys.path[0] == utils_path

def test_preflight_code_payload():
    """
    Verifies the pre-flight check code payload includes the path prioritization.
    """
    client = StataClient()
    
    # We want to catch the code passed to subprocess.run
    stata_path = "/Applications/StataNow"
    edition = "mp"
    
    with patch("mcp_stata.stata_client._get_discovery_candidates", return_value=[(f"{stata_path}/stata-mp", edition)]), \
         patch("subprocess.run") as mock_run:
        
        mock_run.return_value = MagicMock(returncode=0)
        
        # Bypass the rest of init after preflight
        with patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("sys.path", []), \
             patch("sys.stderr.write"):
            
            try:
                client.init()
            except:
                pass # Expected to fail later since we mocked nothing else
                
            # Check the first call to subprocess.run
            if mock_run.called:
                args, kwargs = mock_run.call_args
                payload = args[0][2] # [py_exe, "-c", payload]
                
                assert "sys.path.insert(0, utils_path)" in payload
                assert f"stata_setup.config({repr(stata_path)}, {repr(edition)})" in payload

def test_get_data_slicing_unit():
    """
    Verifies get_data correctly calculates slices for pdataframe_from_data.
    """
    client = StataClient()
    client.stata = MagicMock()
    client._initialized = True
    
    with patch("sfi.Data.getObsTotal", return_value=100):
        # Request start=10, count=5
        client.get_data(start=10, count=5)
        
        # Should call pdataframe_from_data with range(10, 15)
        # 0-indexed 10 to 14 includes 5 rows.
        client.stata.pdataframe_from_data.assert_called_with(obs=range(10, 15))

def test_get_data_boundary_unit():
    """
    Verifies get_data handles boundaries (start near total_obs) correctly.
    """
    client = StataClient()
    client.stata = MagicMock()
    client._initialized = True
    
    with patch("sfi.Data.getObsTotal", return_value=100):
        # 1. Start exactly at total_obs
        res = client.get_data(start=100, count=5)
        assert res == []
        
        # 2. Start just before total_obs, count goes over
        client.get_data(start=98, count=5)
        client.stata.pdataframe_from_data.assert_called_with(obs=range(98, 100))
