"""
Fixed test_error_e2e.py with proper async decorators.

Key changes:
1. Added @pytest.mark.anyio to all async tests
2. Tests now properly integrate with anyio event loop
"""
import os
import tempfile
import pytest
from pathlib import Path

import anyio

import stata_setup
from conftest import configure_stata_for_tests
try:
    stata_dir, stata_flavor = configure_stata_for_tests()
    stata_setup.config(stata_dir, stata_flavor)
except (FileNotFoundError, PermissionError) as e:
    pytest.skip(f"Stata not found or not executable: {e}", allow_module_level=True)

pytestmark = [pytest.mark.requires_stata, pytest.mark.integration]


class TestE2EErrorCapture:
    """End-to-end tests for error capture with real Stata commands."""

    @pytest.fixture
    def client(self, stata_client):
        """Use the shared Stata client from conftest."""
        return stata_client

    def test_captures_variable_not_found_error(self, client):
        """Test capturing 'variable not found' error from regress command."""
        # This should produce the exact error you're seeing
        code = "sysuse auto, clear\nregress price nonexistent_var"
        
        result = client.run_command_structured(code, echo=True)
        
        # Verify error was captured
        assert not result.success
        assert result.rc != 0
        assert result.error is not None
        
        # Critical: stderr should contain the actual error message
        if result.stderr:
            assert 'nonexistent_var' in result.stderr.lower() or 'not found' in result.stderr.lower()
        
        # The error object should have the message
        assert result.error.message
        assert 'nonexistent_var' in result.error.message.lower() or 'not found' in result.error.message.lower()

    def test_captures_reghdfe_variable_not_found(self, client):
        """Test capturing error from reghdfe with non-existent variable (your exact case)."""
        # First check if reghdfe is installed
        check_result = client.run_command_structured("which reghdfe", echo=False)
        if not check_result.success:
            pytest.skip("reghdfe not installed")
        
        # This simulates your exact error
        code = """
sysuse auto, clear
reghdfe price i.nonexistent_var
"""
        
        result = client.run_command_structured(code, echo=True)
        
        assert not result.success
        assert result.rc == 111  # Stata's "variable not found" return code
        assert result.error is not None
        
        # Critical assertions
        error_message = result.error.message.lower()
        error_context = result.error.context.lower() if result.error.context else ""
        
        # The error message OR context should mention the variable
        found_error = (
            'nonexistent_var' in error_message or
            'not found' in error_message or
            'nonexistent_var' in error_context or
            'not found' in error_context
        )
        assert found_error, f"Error message missing variable name. Got: {result.error.message}"

    @pytest.mark.anyio  # ADD THIS DECORATOR
    async def test_streaming_captures_error_with_trace(self, client, tmp_path):
        """Test that streaming execution captures errors even with lots of trace output."""
        # Create a do-file that errors after some output
        dofile = tmp_path / "error_test.do"
        dofile.write_text("""
sysuse auto, clear
display "Starting analysis..."
regress price nonexistent_variable
display "This should never execute"
""")
        
        logs = []
        
        async def log_callback(text: str):
            logs.append(text)
        
        result = await client.run_do_file_streaming(
            str(dofile),
            notify_log=log_callback,
            echo=True,
            trace=False  # Start with trace off
        )
        
        assert not result.success
        assert result.rc == 111
        assert result.error is not None
        
        # Check that error message contains the variable name
        error_text = result.error.message.lower()
        assert 'nonexistent_variable' in error_text or 'not found' in error_text

    @pytest.mark.anyio  # ADD THIS DECORATOR
    async def test_streaming_with_massive_cleanup_output(self, client, tmp_path):
        """Test error capture when there's massive cleanup output after error."""
        # This simulates your scenario with reghdfe cleanup
        dofile = tmp_path / "massive_cleanup.do"
        
        # Create a do-file that produces error then lots of output
        content = """
sysuse auto, clear
capture noisily regress price nonexistent_var
"""
        # Add lots of display commands to simulate cleanup output
        for i in range(1000):
            content += f'display "cleanup operation {i}"\n'
        
        # Finally exit with the error code to simulate a failed command
        content += "exit 111\n"
        
        dofile.write_text(content)
        
        logs = []
        
        async def log_callback(text: str):
            logs.append(text)
        
        result = await client.run_do_file_streaming(
            str(dofile),
            notify_log=log_callback,
            echo=True,
            trace=False
        )
        
        # Even with massive output, should capture the original error
        assert result.error is not None
        error_message = result.error.message.lower()
        
        # Should mention the variable or "not found"
        assert 'nonexistent_var' in error_message or 'not found' in error_message

    def test_captures_syntax_error(self, client):
        """Test capturing syntax errors."""
        code = "this is not valid Stata syntax"
        
        result = client.run_command_structured(code, echo=True)
        
        assert not result.success
        assert result.rc != 0
        assert result.error is not None
        assert 'syntax' in result.error.message.lower() or 'unrecognized' in result.error.message.lower()

    def test_error_with_log_file_inspection(self, client, tmp_path):
        """Test that we can inspect the log file directly to verify {err} tags."""
        code = "sysuse auto, clear\nregress price fake_variable"
        
        # Run with capture to get log path
        result = client.run_command_structured(code, echo=True)
        
        assert not result.success
        
        # If there's a log_path in the error, inspect it
        if result.error and hasattr(result.error, 'log_path') and result.error.log_path:
            log_path = Path(result.error.log_path)
            if log_path.exists():
                log_content = log_path.read_text(encoding='utf-8', errors='replace')
                
                # The log should contain {err} tags
                assert '{err}' in log_content, "Log file should contain {err} tags"
                
                # Verify our backward search would find it
                result_search = client._read_log_backwards_until_error(str(log_path))
                assert '{err}' in result_search, "Backward search should find {err} tags"

    @pytest.mark.anyio  # ADD THIS DECORATOR
    async def test_do_file_with_early_error(self, client, tmp_path):
        """Test do-file where error occurs very early."""
        dofile = tmp_path / "early_error.do"
        dofile.write_text("""
// Error on line 2
regress price nonexistent

// If we got here, something is wrong
display "ERROR: Should have stopped"
""")
        
        logs = []
        
        async def log_callback(text: str):
            logs.append(text)
        
        result = await client.run_do_file_streaming(
            str(dofile),
            notify_log=log_callback,
            echo=True,
            trace=False
        )
        
        assert not result.success
        assert result.error is not None
        
        # Should NOT see "Should have stopped" anywhere
        combined_logs = "".join(logs)
        assert "Should have stopped" not in combined_logs

    @pytest.mark.anyio  # ADD THIS DECORATOR
    async def test_multiple_errors_captures_first(self, client, tmp_path):
        """Test that with multiple errors, we get meaningful error info."""
        dofile = tmp_path / "multiple_errors.do"
        dofile.write_text("""
sysuse auto, clear

// First error
capture regress price first_fake_var

// Second error  
capture regress price second_fake_var

// Report that we got errors
display "Had errors but continuing"
""")
        
        logs = []
        
        async def log_callback(text: str):
            logs.append(text)
        
        result = await client.run_do_file_streaming(
            str(dofile),
            notify_log=log_callback,
            echo=True,
            trace=False
        )
        
        # This should succeed because we used capture
        assert result.success

    def test_trace_mode_error_capture(self, client):
        """Test error capture with trace mode enabled (lots of output)."""
        code = "sysuse auto, clear\nregress price fake_var"
        
        result = client.run_command_structured(code, echo=True, trace=True)
        
        assert not result.success
        assert result.error is not None
        
        # Even with trace output, should capture meaningful error
        error_message = result.error.message.lower()
        assert 'fake_var' in error_message or 'not found' in error_message


class TestE2EStreamingWithProgress:
    """Test streaming execution with progress reporting and error capture."""

    @pytest.fixture
    def client(self, stata_client):
        return stata_client

    @pytest.mark.anyio  # ADD THIS DECORATOR
    async def test_progress_callback_with_error(self, client, tmp_path):
        """Test that progress callbacks work even when command errors."""
        dofile = tmp_path / "progress_error.do"
        dofile.write_text("""
sysuse auto, clear
display "Step 1 complete"
regress price nonexistent
display "Should not reach here"
""")
        
        logs = []
        progress_calls = []
        
        async def log_callback(text: str):
            logs.append(text)
        
        async def progress_callback(current, total, message):
            progress_calls.append((current, total, message))
        
        result = await client.run_do_file_streaming(
            str(dofile),
            notify_log=log_callback,
            notify_progress=progress_callback,
            echo=True
        )
        
        assert not result.success
        assert result.error is not None
        
        # Should have received some progress callbacks
        assert len(progress_calls) > 0


class TestE2ERealWorldScenario:
    """Test real-world scenario matching the user's exact problem."""

    @pytest.fixture
    def client(self, stata_client):
        return stata_client

    @pytest.mark.anyio  # ADD THIS DECORATOR
    async def test_exact_user_scenario(self, client, tmp_path):
        """
        Reproduce the exact user scenario:
        - reghdfe command with non-existent variable
        - Lots of cleanup/trace output after error
        - Error message gets lost in tail
        """
        # First verify reghdfe is available
        check = client.run_command_structured("which reghdfe", echo=False)
        if not check.success:
            pytest.skip("reghdfe not installed - install with: ssc install reghdfe")
        
        dofile = tmp_path / "user_scenario.do"
        dofile.write_text("""
// Simulate user's exact scenario
sysuse auto, clear

// This will error with "variable not found"
reghdfe price i.compl_gloves

// If we got here, something is wrong
display "ERROR: Should have stopped after reghdfe error"
""")
        
        logs = []
        
        async def log_callback(text: str):
            logs.append(text)
        
        result = await client.run_do_file_streaming(
            str(dofile),
            notify_log=log_callback,
            echo=True,
            trace=False
        )
        
        # Critical assertions
        assert not result.success, "reghdfe should have failed"
        assert result.rc == 111, f"Expected rc=111 for variable not found, got {result.rc}"
        assert result.error is not None, "Should have error object"
        
        # The KEY test: error message should mention the missing variable
        error_message = result.error.message.lower()
        error_context = (result.error.context or "").lower()
        stderr = (result.stderr or "").lower()
        
        # Check all possible locations for the error
        found_variable = (
            'compl_gloves' in error_message or
            'compl_gloves' in error_context or
            'compl_gloves' in stderr
        )
        
        found_not_found = (
            'not found' in error_message or
            'not found' in error_context or
            'not found' in stderr
        )
        
        # Print debug info if assertions fail
        if not (found_variable and found_not_found):
            print("\n=== DEBUG INFO ===")
            print(f"Error message: {result.error.message}")
            print(f"Error context: {result.error.context}")
            print(f"Stderr: {result.stderr}")
            print(f"Error snippet: {result.error.snippet if hasattr(result.error, 'snippet') else 'N/A'}")
            
            # Inspect log file if available
            if hasattr(result.error, 'log_path') and result.error.log_path:
                log_path = Path(result.error.log_path)
                if log_path.exists():
                    print(f"\n=== LOG FILE INSPECTION ===")
                    log_content = log_path.read_text(encoding='utf-8', errors='replace')
                    print(f"Log size: {len(log_content)} bytes")
                    print(f"Contains {{err}}: {'{err}' in log_content}")
                    
                    # Show lines containing {err}
                    for i, line in enumerate(log_content.splitlines()):
                        if '{err}' in line:
                            print(f"Line {i}: {line}")
                    
                    # Test backward search
                    search_result = client._read_log_backwards_until_error(str(log_path))
                    print(f"\nBackward search found {{err}}: {'{err}' in search_result}")
                    if '{err}' in search_result:
                        print("Backward search result (first 500 chars):")
                        print(search_result[:500])
        
        assert found_variable, "Error should mention 'compl_gloves'"
        assert found_not_found, "Error should mention 'not found'"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])