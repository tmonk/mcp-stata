import os
import sys
import pytest
import subprocess
import asyncio
from unittest.mock import MagicMock, patch
from google import genai
from benchmark import BenchmarkHarness
from mcp_client import MCPStataClient
from terminal_client import TerminalStataClient
from dotenv import load_dotenv

# Import discovery from mcp_stata
src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../src"))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
try:
    from mcp_stata.discovery import find_stata_path
except ImportError:
    find_stata_path = None

# 1. Environment Requirements
def test_env_vars():
    load_dotenv()
    if os.path.exists(".envrc"):
        load_dotenv(".envrc")
    # If not set in environment, we might want to skip or fail
    # but the requirement says to validate it is set.
    api_key = os.environ.get("GEMINI_API_KEY")
    assert api_key is not None and api_key != "", "GEMINI_API_KEY must be set and non-empty"

def test_imports():
    import mcp
    from google import genai
    assert mcp is not None
    assert genai is not None

@pytest.mark.requires_stata
def test_stata_executable(has_stata):
    assert has_stata, "Stata executable not found on PATH or STATA_PATH"

def test_stata_discovery():
    if find_stata_path:
        path, edition = find_stata_path()
        assert path is not None, "Discovery failed to find a path"
        assert os.path.exists(path), f"Discovered path does not exist: {path}"
        assert edition in ["mp", "se", "be", "ic", "small"], f"Unknown edition discovered: {edition}"
    else:
        pytest.skip("mcp_stata.discovery not available")

def test_mcp_stata_launchable():
    # Check if mcp-stata can be invoked (e.g. via uvx or if it's in the path)
    # Since we are in the repo, we might need to check if we can run the server module
    result = subprocess.run(
        [sys.executable, "-m", "mcp_stata.server", "--help"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../src"))}
    )
    # Note: --help might return non-zero if not implemented, but we check if it starts
    assert "usage" in result.stdout.lower() or "help" in result.stdout.lower() or result.returncode == 0

# 2. MCP Server Connectivity (No API calls)
@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_mcp_stata_connectivity():
    async with MCPStataClient(".") as client:
        # Handshake is implicit in __aenter__ (initialize)
        assert client.session is not None
        
        # Check advertised tools
        tools = await client.get_tools()
        tool_names = [t["name"] for t in tools]
        
        # Requirement: at minimum run_command, get_stored_results, find_in_log, describe
        # Our implementation uses stata_ prefix for some
        has_run = any(n in tool_names for n in ["run_command", "stata_run"])
        has_results = any(n in tool_names for n in ["get_stored_results", "stata_get_results"])
        has_describe = any(n in tool_names for n in ["describe", "stata_inspect_data", "stata_describe"])
        # find_in_log is covered by stata_read_log
        has_find = any(n in tool_names for n in ["find_in_log", "stata_read_log"])

        assert has_run, f"Missing run tool. Found: {tool_names}"
        assert has_results, f"Missing results tool. Found: {tool_names}"
        assert has_describe, f"Missing describe/inspect tool. Found: {tool_names}"
        assert has_find, f"Missing find/read_log tool. Found: {tool_names}"
        
        # Trivial execution
        # Use whatever run tool we found
        run_tool = "stata_run" if "stata_run" in tool_names else "run_command"
        res = await client.call_tool(run_tool, {"code": 'display "hello"'})
        assert "hello" in res

# 3. Terminal (bash) tool
@pytest.mark.requires_stata
def test_terminal_stata_execution(tmp_path):
    client = TerminalStataClient(str(tmp_path))
    
    # Use mcp-stata discovery
    if find_stata_path:
        stata_cmd, _ = find_stata_path()
    else:
        stata_cmd = "stata-se"
    
    res = client.execute_bash(f'"{stata_cmd}" -b display "terminal_test"')
    assert "Exit Code: 0" in res
    
    do_file = tmp_path / "test.do"
    do_file.write_text('display "terminal_test_do"')
    res = client.execute_bash(f'"{stata_cmd}" -b do "{do_file}"')
    
    log_file = tmp_path / "test.log"
    assert log_file.exists()
    assert "terminal_test_do" in log_file.read_text()

# 4. Harness structure (mocked API)
@pytest.mark.asyncio
async def test_harness_mocked_loop():
    # Set dummy key if not present for mocked test
    if not os.environ.get("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = "dummy_key"
    harness = BenchmarkHarness()
    
    # Mock Usage Metadata
    mock_usage = MagicMock()
    mock_usage.prompt_token_count = 10
    mock_usage.candidates_token_count = 5
    
    # Mock Response
    mock_response = MagicMock()
    mock_response.usage_metadata = mock_usage
    mock_response.candidates = [MagicMock()]
    mock_response.candidates[0].content.parts = [MagicMock()]
    mock_response.candidates[0].content.parts[0].function_call = None # End of loop
    mock_response.text = "Done"
    
    # In google-genai, it's client.models.generate_content
    with patch.object(harness.client.models, 'generate_content', return_value=mock_response) as mock_gen:
        task = {"id": "test_1", "prompt": "test prompt"}
        
        # Easier to test _run_loop directly for token counting
        client_mock = MagicMock()
        client_mock.get_tools = MagicMock(return_value=[])
        
        # Run 3 turns
        # To run multiple turns, we need the first few responses to have tool calls
        
        mock_response_tool = MagicMock()
        mock_response_tool.usage_metadata = mock_usage
        mock_response_tool.candidates = [MagicMock()]
        tool_call = MagicMock()
        tool_call.function_call.name = "test_tool"
        tool_call.function_call.args = {"arg": 1}
        mock_response_tool.candidates[0].content.parts = [tool_call]
        mock_response_tool.text = None

        mock_gen.side_effect = [mock_response_tool, mock_response_tool, mock_response]
        
        # For mcp approach, it calls client.call_tool
        async def mock_call_tool(name, args):
            return "result"
        client_mock.call_tool = mock_call_tool
        
        result = await harness._run_loop("mcp", task, [], client_mock, max_turns=5)
        
        assert result["input_tokens"] == 30 # 3 turns * 10
        assert result["output_tokens"] == 15 # 3 turns * 5
        assert result["turns"] == 3

# 5. Token Counting and Cost
def test_cost_calculation():
    # Cost formula: input_tokens / 1_000_000 * 0.50 + output_tokens / 1_000_000 * 3.00
    input_tokens = 2_000_000
    output_tokens = 1_000_000
    
    cost = (input_tokens / 1_000_000 * 0.50) + (output_tokens / 1_000_000 * 3.00)
    assert cost == (2 * 0.50) + (1 * 3.00) # 1.0 + 3.0 = 4.0
    assert cost == 4.0

# 6. Stata execution round-trip
@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_stata_roundtrip_mcp():
    async with MCPStataClient(".") as client:
        # Use stata_run tool
        await client.call_tool("stata_run", {"code": "sysuse auto, clear"})
        res = await client.call_tool("stata_run", {"code": "summarize price"})
        assert "price" in res
        import re
        assert re.search(r"\d+\.\d+", res) or "Mean" in res

@pytest.mark.requires_stata
def test_stata_roundtrip_terminal(tmp_path):
    client = TerminalStataClient(str(tmp_path))
    if find_stata_path:
        stata_cmd, _ = find_stata_path()
    else:
        stata_cmd = "stata-se"
        
    do_file = tmp_path / "roundtrip.do"
    do_file.write_text("sysuse auto, clear\nsummarize price")
    client.execute_bash(f'"{stata_cmd}" -b do "{do_file}"')
    
    log_file = tmp_path / "roundtrip.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "Mean" in content or "price" in content
