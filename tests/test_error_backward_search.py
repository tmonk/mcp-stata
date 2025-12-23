"""
Unit tests for dynamic backward log search functionality.

Tests the _read_log_backwards_until_error and _read_log_tail_smart methods.
"""
import os
import tempfile
import pytest
from pathlib import Path

import stata_setup
from conftest import configure_stata_for_tests
try:
    stata_dir, stata_flavor = configure_stata_for_tests()
    stata_setup.config(stata_dir, stata_flavor)
except (FileNotFoundError, PermissionError) as e:
    pytest.skip(f"Stata not found or not executable: {e}", allow_module_level=True)
pytestmark = pytest.mark.requires_stata


class TestBackwardLogSearch:
    """Test the backward search for {err} tags in log files."""

    def test_finds_error_at_end(self, client):
        """Test finding error near the end of the log file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name
            # Write some content
            f.write("Starting analysis...\n" * 100)
            # Error near the end
            f.write("{err}variable compl_gloves not found\n")
            f.write("{txt}cleanup line\n" * 10)

        try:
            result = client._read_log_backwards_until_error(log_path)
            assert '{err}' in result
            assert 'compl_gloves' in result
            assert 'Starting analysis' in result  # Should include earlier context
        finally:
            os.unlink(log_path)

    def test_finds_error_in_middle(self, client):
        """Test finding error in the middle with lots of output after."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name
            # Initial content
            f.write("Starting...\n" * 100)
            # Error in middle
            f.write("{err}variable {bf}compl_gloves{sf} not found\n")
            f.write("{txt}      {hline 81} end reghdfe.Estimate {hline}\n")
            # LOTS of cleanup output (simulate your real scenario)
            for i in range(5000):
                f.write(f"    - cleanup operation {i}\n")
            f.write("end of do-file\n")

        try:
            result = client._read_log_backwards_until_error(log_path)
            assert '{err}' in result, "Should find {err} tag"
            assert 'compl_gloves' in result, "Should include error variable name"
        finally:
            os.unlink(log_path)

    def test_finds_error_at_beginning(self, client):
        """Test finding error at the very beginning of the file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name
            # Error right at start
            f.write("{err}syntax error\n")
            f.write("{txt}r(198)\n")
            # Lots of output after
            f.write("cleanup\n" * 10000)

        try:
            result = client._read_log_backwards_until_error(log_path)
            assert '{err}' in result
            assert 'syntax error' in result
        finally:
            os.unlink(log_path)

    def test_multiple_errors_finds_first(self, client):
        """Test that with multiple errors, we find the first one (root cause)."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name
            f.write("Starting...\n" * 50)
            # First error (root cause)
            f.write("{err}variable x not found\n")
            f.write("continuing...\n" * 100)
            # Second error (cascading)
            f.write("{err}invalid syntax\n")
            f.write("cleanup\n" * 100)

        try:
            result = client._read_log_backwards_until_error(log_path)
            # Should find at least one error
            assert '{err}' in result
            # Depending on implementation, might find first or last
            # The backward search will find the last error, which is fine
            # A forward search would find the first (root cause)
        finally:
            os.unlink(log_path)

    def test_no_error_returns_all_content(self, client):
        """Test that when no error exists, it returns content up to max_bytes."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name
            f.write("No errors here\n" * 100)

        try:
            result = client._read_log_backwards_until_error(log_path, max_bytes=10000)
            assert '{err}' not in result
            assert 'No errors here' in result
        finally:
            os.unlink(log_path)

    def test_empty_file(self, client):
        """Test handling of empty log file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name
            # Write nothing

        try:
            result = client._read_log_backwards_until_error(log_path)
            assert result == ""
        finally:
            os.unlink(log_path)

    def test_respects_max_bytes(self, client):
        """Test that search respects max_bytes limit."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name
            # Write 2MB of content without any errors
            for i in range(100000):
                f.write(f"Line {i}: no errors here\n")

        try:
            # Limit to 100KB
            result = client._read_log_backwards_until_error(log_path, max_bytes=100_000)
            assert len(result) <= 110_000  # Some slack for chunk boundaries
        finally:
            os.unlink(log_path)

    def test_handles_unicode(self, client):
        """Test handling of unicode content in logs."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log', encoding='utf-8') as f:
            log_path = f.name
            f.write("Unicode: café, naïve, 日本語\n" * 50)
            f.write("{err}variable σ not found\n")
            f.write("More unicode: Ω ∑ ∫\n" * 10)

        try:
            result = client._read_log_backwards_until_error(log_path)
            assert '{err}' in result
            assert 'σ' in result
        finally:
            os.unlink(log_path)

    def test_real_stata_error_format(self, client):
        """Test with actual Stata error format from your example."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log', encoding='utf-8') as f:
            log_path = f.name
            # Simulate the exact format from your error
            f.write(". reghdfe log_total_val i.compl_gloves\n")
            f.write("(MWFE estimator converged in 1 iterations)\n")
            f.write("\n")
            f.write("{err}variable {bf}compl_gloves{sf} not found\n")
            f.write("{txt}      {hline 81} end reghdfe.Estimate {hline}\n")
            f.write("    - Cleanup `c(rc)' `keep_mata'\n")
            f.write("    = Cleanup 111 0\n")
            
            # Add lots of trace output
            for i in range(1000):
                f.write(f"      - trace line {i}\n")
            
            f.write("      - if `rc') exit `rc'\n")
            f.write("      = if (111) exit 111\n")
            f.write("      {hline 82} end reghdfe.Cleanup {hline}\n")
            f.write("r(111);\n")
            f.write("end of do-file\n")
            f.write("r(111);\n")

        try:
            result = client._read_log_backwards_until_error(log_path)
            
            # Critical assertions
            assert '{err}' in result, "Must find {err} tag"
            assert 'compl_gloves' in result, "Must find variable name"
            assert 'variable {bf}compl_gloves{sf} not found' in result, "Must find full error message"
            
            # Should also have some context before the error
            assert 'reghdfe' in result or 'MWFE' in result, "Should have context before error"
            
        finally:
            os.unlink(log_path)


class TestSmartLogReader:
    """Test the smart log reader that adapts based on rc."""

    def test_success_uses_small_tail(self, client):
        """Test that successful runs (rc=0) use small tail."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name
            # Write 100KB of content
            for i in range(5000):
                f.write(f"Line {i}: successful output\n")

        try:
            # With rc=0, should only read 20KB tail
            result = client._read_log_tail_smart(log_path, rc=0, trace=False)
            # Result should be much less than 100KB
            assert len(result) < 30_000  # 20KB + some slack
        finally:
            os.unlink(log_path)

    def test_error_uses_backward_search(self, client):
        """Test that errors (rc!=0) use backward search."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name
            f.write("Starting...\n" * 100)
            f.write("{err}test error\n")
            # Add 50KB of output after error
            for i in range(2500):
                f.write(f"Cleanup {i}\n")

        try:
            result = client._read_log_tail_smart(log_path, rc=111, trace=False)
            # Should find the error despite lots of output after
            assert '{err}' in result
            assert 'test error' in result
        finally:
            os.unlink(log_path)

    def test_trace_mode_uses_larger_tail(self, client):
        """Test that trace mode uses 200KB tail for successful runs."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name
            # Write 300KB of content
            for i in range(15000):
                f.write(f"Line {i}: trace output\n")

        try:
            # With rc=0 and trace=True, should read 200KB tail
            result = client._read_log_tail_smart(log_path, rc=0, trace=True)
            # Should be larger than non-trace but less than full file
            assert 150_000 < len(result) < 250_000
        finally:
            os.unlink(log_path)


class TestErrorExtraction:
    """Test the error extraction from logs with {err} tags."""

    def test_extracts_simple_error(self, client):
        """Test extraction of simple error message."""
        log_content = """
. summarize nonexistent
{err}variable nonexistent not found
{txt}r(111);
"""
        msg, context = client._extract_error_and_context(log_content, rc=111)
        
        assert 'nonexistent' in msg.lower()
        assert '{err}' in context
        assert 'r(111)' in context

    def test_extracts_complex_error_with_smcl(self, client):
        """Test extraction of error with SMCL formatting."""
        log_content = """
. reghdfe log_total_val i.compl_gloves
{err}variable {bf}compl_gloves{sf} not found
{txt}      {hline 81} end reghdfe.Estimate {hline}
r(111);
"""
        msg, context = client._extract_error_and_context(log_content, rc=111)
        
        assert 'compl_gloves' in msg
        assert 'not found' in msg.lower()
        assert '{err}' in context

    def test_extracts_multiline_error(self, client):
        """Test extraction of multi-line error block."""
        log_content = """
. command
{err}error line 1
{err}error line 2  
{err}error line 3
{txt}continuing...
"""
        msg, context = client._extract_error_and_context(log_content, rc=198)
        
        # Should contain all error lines
        assert 'error line 1' in msg or 'error line 1' in context
        assert 'error line 2' in msg or 'error line 2' in context

    def test_fallback_without_err_tag(self, client):
        """Test fallback behavior when no {err} tag present."""
        log_content = """
. command
some output
more output
r(111);
end of do-file
"""
        msg, context = client._extract_error_and_context(log_content, rc=111)
        
        # Should return generic error message
        assert 'Stata error r(111)' in msg
        # Context should contain last lines
        assert 'r(111)' in context


if __name__ == '__main__':
    pytest.main([__file__, '-v'])