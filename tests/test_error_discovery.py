"""
Fixed test_error_discovery.py with proper async decorators.
"""
import os
import tempfile
from pathlib import Path
import pytest


import stata_setup
from conftest import configure_stata_for_tests
try:
    stata_dir, stata_flavor = configure_stata_for_tests()
    stata_setup.config(stata_dir, stata_flavor)
except (FileNotFoundError, PermissionError) as e:
    pytest.skip(f"Stata not found or not executable: {e}", allow_module_level=True)

pytestmark = [pytest.mark.requires_stata, pytest.mark.integration]


class TestDiagnosticErrorCapture:
    """Diagnostic tests to figure out where error info goes."""

    @pytest.fixture
    def client(self, stata_client):
        return stata_client

    def test_diagnostic_raw_log_inspection(self, client, tmp_path):
        """
        Test 1: Inspect the raw log file to see what Stata actually writes.
        """
        print("\n" + "="*80)
        print("DIAGNOSTIC TEST 1: Raw Log File Inspection")
        print("="*80)
        
        code = "sysuse auto, clear\nregress price nonexistent_var"
        
        # Use a custom log file location for inspection
        log_file = tmp_path / "diagnostic.log"
        
        # Run the command with log output
        try:
            from io import StringIO
            import sys
            
            # Capture what happens
            output = StringIO()
            errors = StringIO()
            
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            
            try:
                sys.stdout = output
                sys.stderr = errors
                
                # Run with the internal API that writes to a log
                result = client.run_command_structured(code, echo=True)
                
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
            
            captured_stdout = output.getvalue()
            captured_stderr = errors.getvalue()
            
            print(f"\nCapture stdout length: {len(captured_stdout)}")
            print(f"Captured stderr length: {len(captured_stderr)}")
            print(f"Result success: {result.success}")
            print(f"Result rc: {result.rc}")
            
            if result.error:
                print(f"\nError message: {result.error.message}")
                print(f"Error context: {result.error.context}")
                
                if hasattr(result.error, 'log_path') and result.error.log_path:
                    log_path = Path(result.error.log_path)
                    if log_path.exists():
                        print(f"\nLog file exists: {log_path}")
                        log_content = log_path.read_text(encoding='utf-8', errors='replace')
                        print(f"Log file size: {len(log_content)} bytes")
                        
                        # Check for {err} tags
                        err_count = log_content.count('{err}')
                        print(f"Number of {{err}} tags in log: {err_count}")
                        
                        if err_count > 0:
                            # Find and display lines with {err}
                            print("\nLines containing {err}:")
                            for i, line in enumerate(log_content.splitlines()):
                                if '{err}' in line:
                                    print(f"  Line {i}: {line[:100]}")
                            
                            # Test backward search on this file
                            print("\nTesting backward search...")
                            search_result = client._read_log_backwards_until_error(str(log_path))
                            print(f"Backward search found {{err}}: {'{err}' in search_result}")
                            
                            if '{err}' in search_result:
                                # Extract the error line
                                for line in search_result.splitlines():
                                    if '{err}' in line:
                                        print(f"  Error line: {line}")
                                        break
                        else:
                            print("\n⚠️  WARNING: No {err} tags found in log file!")
                            print("First 1000 chars of log:")
                            print(log_content[:1000])
                            print("\nLast 1000 chars of log:")
                            print(log_content[-1000:])
            
            # Check if error info is in stdout/stderr instead
            if '{err}' in captured_stdout:
                print("\n✓ Found {err} tags in captured stdout")
            if '{err}' in captured_stderr:
                print("\n✓ Found {err} tags in captured stderr")
            
        except Exception as e:
            print(f"\nException during test: {e}")
            import traceback
            traceback.print_exc()

    def test_diagnostic_log_writing_path(self, client):
        """
        Test 2: Check how logs are written - stdout vs stderr vs file.
        """
        print("\n" + "="*80)
        print("DIAGNOSTIC TEST 2: Log Writing Path")
        print("="*80)
        
        # Create a simple error
        code = "use nonexistent.dta"
        
        # This will use the _exec_with_capture method
        result = client._exec_with_capture(code, echo=True)
        
        print(f"\nResult success: {result.success}")
        print(f"Result rc: {result.rc}")
        print(f"Stdout length: {len(result.stdout) if result.stdout else 0}")
        print(f"Stderr length: {len(result.stderr) if result.stderr else 0}")
        
        if result.stdout:
            print(f"\nStdout contains {{err}}: {'{err}' in result.stdout}")
            if '{err}' in result.stdout:
                print("First 500 chars of stdout:")
                print(result.stdout[:500])
        
        if result.stderr:
            print(f"\nStderr contains {{err}}: {'{err}' in result.stderr if result.stderr else False}")
            if result.stderr and '{err}' in result.stderr:
                print("First 500 chars of stderr:")
                print(result.stderr[:500])
        
        if result.error:
            print(f"\nError message: {result.error.message}")
            print(f"Error contains {{err}}: {'{err}' in result.error.message}")

    @pytest.mark.anyio  # ADD THIS DECORATOR
    async def test_diagnostic_streaming_log_path(self, client, tmp_path):
        """
        Test 3: Check what gets written to the streaming log file.
        """
        print("\n" + "="*80)
        print("DIAGNOSTIC TEST 3: Streaming Log File")
        print("="*80)
        
        dofile = tmp_path / "diagnostic_stream.do"
        dofile.write_text("""
sysuse auto, clear
display "Before error"
regress price fake_variable
display "After error (should not appear)"
""")
        
        logs = []
        log_path_holder = {}
        
        async def log_callback(text: str):
            logs.append(text)
            # Try to extract log path
            try:
                import json
                data = json.loads(text)
                if data.get('event') == 'log_path':
                    log_path_holder['path'] = data.get('path')
            except:
                pass
        
        result = await client.run_do_file_streaming(
            str(dofile),
            notify_log=log_callback,
            echo=True,
            trace=False
        )
        
        print(f"\nResult success: {result.success}")
        print(f"Result rc: {result.rc}")
        print(f"Number of log callbacks: {len(logs)}")
        
        if 'path' in log_path_holder:
            log_path = Path(log_path_holder['path'])
            print(f"\nLog file: {log_path}")
            
            if log_path.exists():
                log_content = log_path.read_text(encoding='utf-8', errors='replace')
                print(f"Log file size: {len(log_content)} bytes")
                print(f"Contains {{err}}: {'{err}' in log_content}")
                
                if '{err}' in log_content:
                    print("\nLines with {err}:")
                    for line in log_content.splitlines():
                        if '{err}' in line:
                            print(f"  {line[:100]}")
                else:
                    print("\n⚠️  WARNING: No {err} tags in streaming log!")
                    print("\nSearching for 'fake_variable':", 'fake_variable' in log_content)
                    print("Searching for 'not found':", 'not found' in log_content.lower())
                    
                    # Show relevant parts
                    lines = log_content.splitlines()
                    for i, line in enumerate(lines):
                        if 'fake_variable' in line.lower() or 'not found' in line.lower():
                            # Show context around this line
                            start = max(0, i-2)
                            end = min(len(lines), i+3)
                            print(f"\nContext around line {i}:")
                            for j in range(start, end):
                                print(f"  {j}: {lines[j][:100]}")
        
        if result.error:
            print(f"\nError message: {result.error.message}")
            print(f"Error context: {result.error.context}")

    def test_diagnostic_compare_methods(self, client):
        """
        Test 4: Compare different execution methods to see which captures errors best.
        """
        print("\n" + "="*80)
        print("DIAGNOSTIC TEST 4: Compare Execution Methods")
        print("="*80)
        
        code = "sysuse auto, clear\nregress price fake"
        
        # Method 1: _exec_with_capture
        print("\n--- Method 1: _exec_with_capture ---")
        result1 = client._exec_with_capture(code, echo=True)
        print(f"Success: {result1.success}, RC: {result1.rc}")
        print(f"Stdout has {{err}}: {'{err}' in result1.stdout if result1.stdout else False}")
        print(f"Stderr has {{err}}: {'{err}' in result1.stderr if result1.stderr else False}")
        if result1.error:
            print(f"Error.message has {{err}}: {'{err}' in result1.error.message}")
        
        # Method 2: run_command_structured
        print("\n--- Method 2: run_command_structured ---")
        result2 = client.run_command_structured(code, echo=True)
        print(f"Success: {result2.success}, RC: {result2.rc}")
        print(f"Stdout has {{err}}: {'{err}' in result2.stdout if result2.stdout else False}")
        print(f"Stderr has {{err}}: {'{err}' in result2.stderr if result2.stderr else False}")
        if result2.error:
            print(f"Error.message has {{err}}: {'{err}' in result2.error.message}")
        
        # Method 3: _exec_no_capture
        print("\n--- Method 3: _exec_no_capture ---")
        result3 = client._exec_no_capture(code, echo=True)
        print(f"Success: {result3.success}, RC: {result3.rc}")
        if result3.error:
            print(f"Error object exists: True")
            print(f"Error.message: {result3.error.message[:200] if result3.error.message else 'None'}")

    def test_diagnostic_backward_search_algorithm(self, client):
        """
        Test 5: Verify the backward search algorithm itself works.
        """
        print("\n" + "="*80)
        print("DIAGNOSTIC TEST 5: Backward Search Algorithm")
        print("="*80)
        
        # Create a test file with known error position
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log', encoding='utf-8') as f:
            test_log = f.name
            
            # Write content similar to real Stata output
            f.write(". sysuse auto, clear\n")
            f.write("(1978 automobile data)\n\n")
            f.write(". regress price fake_var\n")
            f.write("{err}variable fake_var not found\n")
            f.write("r(111);\n")
            f.write("\n")
            
            # Add lots of content after
            for i in range(5000):
                f.write(f"cleanup line {i}\n")
        
        try:
            # Test backward search
            result = client._read_log_backwards_until_error(test_log)
            
            print(f"\nTest log size: {Path(test_log).stat().st_size} bytes")
            print(f"Backward search result size: {len(result)} bytes")
            print(f"Found {{err}}: {'{err}' in result}")
            
            if '{err}' in result:
                print("✓ Backward search works correctly")
                # Show the error line
                for line in result.splitlines():
                    if '{err}' in line:
                        print(f"Error line: {line}")
                        break
            else:
                print("✗ Backward search FAILED to find {err} tag")
                print("This indicates a problem with the search algorithm itself")
                
        finally:
            os.unlink(test_log)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])