"""Unit tests for token efficiency optimizations."""
import json
import pytest
from pathlib import Path
import anyio

try:
    from mcp_stata.stata_client import StataClient
    from mcp_stata.server import (
        run_command,
        export_graphs_all,
        load_data,
        codebook,
        run_do_file,
    )
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
    from mcp_stata.stata_client import StataClient
    from mcp_stata.server import (
        run_command,
        export_graphs_all,
        load_data,
        codebook,
        run_do_file,
    )

# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata


def _run_command_sync(*args, **kwargs) -> str:
    async def _main() -> str:
        return await run_command(*args, **kwargs)

    return anyio.run(_main)


def _run_do_file_sync(*args, **kwargs) -> str:
    async def _main() -> str:
        return await run_do_file(*args, **kwargs)

    return anyio.run(_main)


@pytest.fixture
def client():
    """Fixture to provide an initialized StataClient."""
    client = StataClient()
    client.init()
    return client


class TestMutuallyExclusiveOutput:
    """Mutually exclusive stdout/stderr in success vs error cases."""

    def test_success_output_in_command_response(self, client):
        """When success=True, stdout is in CommandResponse, error is None."""
        result = client.run_command_structured("display 2+2")

        assert result.success is True
        assert result.stdout != ""
        assert "4" in result.stdout
        assert result.error is None

    def test_error_output_in_error_envelope(self, client):
        """When success=False, stdout is empty in CommandResponse, full output in ErrorEnvelope."""
        result = client.run_command_structured("invalid_stata_command_xyz")

        assert result.success is False
        assert result.stdout == ""  # Empty in CommandResponse
        assert result.stderr is None

        # Full output is in error envelope (either in stdout or captured in snippet)
        assert result.error is not None
        assert result.error.snippet is not None
        assert len(result.error.snippet) > 0
        assert "invalid" in result.error.snippet.lower() or "unrecognized" in result.error.snippet.lower()
        assert result.error.rc is not None

    def test_error_with_missing_variable(self, client):
        """Test error case with missing variable - output only in ErrorEnvelope."""
        s = client.run_command_structured("sysuse auto, clear")
        assert s.success is True
        result = client.codebook("nonexistent_variable_xyz")

        assert result.success is False
        assert result.stdout == ""  # Empty in CommandResponse

        # Full output in error envelope (captured in snippet or stdout)
        assert result.error is not None
        error_output = (result.error.stdout or "") + (result.error.snippet or "")
        assert "nonexistent_variable_xyz" in error_output

    def test_snippet_always_present_in_errors(self, client):
        """Test that snippet (last 800 chars) is always present in error envelope."""
        result = client.run_command_structured("bogus_command_that_will_fail")

        assert result.success is False
        assert result.error is not None
        assert result.error.snippet is not None
        assert len(result.error.snippet) <= 800


class TestGraphExportTokenEfficiency:
    """Test graph export with file paths (default) vs base64 (optional)."""

    def test_export_graphs_default_returns_file_paths(self, client):
        """Default export_graphs_all() returns file paths, not base64."""
        s = client.run_command_structured("sysuse auto, clear")
        assert s.success is True
        g = client.run_command_structured("scatter price mpg, name(TestGraph, replace)")
        assert g.success is True

        result = client.export_graphs_all()

        assert len(result.graphs) >= 1
        graph = result.graphs[0]

        # Default: file_path is set, image_base64 is None
        assert graph.file_path is not None
        assert Path(graph.file_path).exists()
        assert graph.file_path.endswith(".png")
        assert graph.image_base64 is None

    def test_export_graphs_with_base64_flag(self, client):
        """With use_base64=True, returns base64 data."""
        s = client.run_command_structured("sysuse auto, clear")
        assert s.success is True
        g = client.run_command_structured("scatter price mpg, name(TestGraph2, replace)")
        assert g.success is True

        result = client.export_graphs_all(use_base64=True)

        assert len(result.graphs) >= 1
        graph = result.graphs[0]

        # With base64: image_base64 is set, file_path is None
        assert graph.image_base64 is not None
        assert len(graph.image_base64) > 1000  # Base64 should be large
        assert graph.file_path is None

    def test_file_path_much_smaller_than_base64(self, client):
        """File path should be orders of magnitude smaller than base64."""
        s = client.run_command_structured("sysuse auto, clear")
        assert s.success is True
        g = client.run_command_structured("scatter price mpg, name(TestGraph3, replace)")
        assert g.success is True

        # Get file path version
        result_path = client.export_graphs_all(use_base64=False)
        path_size = len(result_path.graphs[0].file_path)

        # Get base64 version
        result_b64 = client.export_graphs_all(use_base64=True)
        b64_size = len(result_b64.graphs[0].image_base64)

        # File path should be at least 100x smaller
        assert b64_size > path_size * 100


class TestOutputTruncation:
    """Test max_output_lines parameter for truncating verbose output."""

    def test_truncation_with_max_output_lines(self, client):
        """Test that max_output_lines truncates output correctly."""
        s = client.run_command_structured("sysuse auto, clear")
        assert s.success is True

        # Get full output
        result_full = client.run_command_structured("describe")
        full_lines = result_full.stdout.splitlines()

        # Get truncated output (5 lines)
        result_truncated = client.run_command_structured("describe", max_output_lines=5)
        truncated_lines = result_truncated.stdout.splitlines()

        # Should have 5 original lines + truncation notice (which adds a newline before it)
        assert len(truncated_lines) <= 7  # 5 lines + blank line + truncation message
        assert "output truncated" in result_truncated.stdout
        assert f"showing 5 of {len(full_lines)} lines" in result_truncated.stdout

    def test_truncation_with_codebook(self, client):
        """Test truncation with codebook command."""
        s = client.run_command_structured("sysuse auto, clear")
        assert s.success is True

        result = client.codebook("price", max_output_lines=3)
        lines = result.stdout.splitlines()

        # 3 lines + blank line + truncation notice
        assert len(lines) <= 5
        assert "output truncated" in result.stdout

    def test_no_truncation_when_output_smaller_than_limit(self, client):
        """When output is smaller than limit, no truncation should occur."""
        result = client.run_command_structured("display 2+2", max_output_lines=100)

        assert "output truncated" not in result.stdout
        assert result.success is True

    def test_truncation_doesnt_affect_errors(self, client):
        """Truncation parameter should not affect error cases."""
        result = client.run_command_structured("invalid_command", max_output_lines=5)

        assert result.success is False
        assert result.stdout == ""  # Empty in CommandResponse
        assert result.error is not None
        # Error output should be in error envelope (snippet always present)
        assert result.error.snippet is not None
        assert len(result.error.snippet) > 0


class TestJSONCompactness:
    """Test that JSON responses are compact (no indentation)."""

    def test_run_command_returns_compact_json(self):
        """Server tools should return compact JSON without indentation."""
        result_str = _run_command_sync("display 1+1")

        # Parse to ensure it's valid JSON
        result = json.loads(result_str)
        assert result["rc"] == 0

        # Check that it's compact - no newlines except in actual content
        # Remove the stdout content first, then check
        result_copy = result.copy()
        result_copy["stdout"] = ""
        compact_str = json.dumps(result_copy)

        # The JSON structure itself should not have newlines from indentation
        # (it will have the keys/values in one line)
        lines = result_str.split("\n")
        # If indented, would have many lines; compact should have few
        # Note: stdout itself may have newlines, so we check structure
        assert result_str.find('  "') == -1  # No double-space indent

    def test_graph_export_returns_compact_json(self):
        """Graph export should return compact JSON."""
        # Initialize with a graph
        _run_command_sync("sysuse auto, clear")
        _run_command_sync("scatter price mpg, name(CompactTest, replace)")

        result_str = export_graphs_all()
        result = json.loads(result_str)

        # Should be valid JSON
        assert "graphs" in result

        # Should not have indentation markers
        assert result_str.find('  "') == -1  # No double-space indent
        assert result_str.find('\n  ') == -1  # No newline + indent


class TestTokenSavingsIntegration:
    """Integration tests showing combined token savings."""

    def test_error_response_size_vs_old_approach(self, client):
        """Compare error response size vs hypothetical duplicate."""
        result = client.run_command_structured("invalid_command")

        # stdout is empty in CommandResponse
        command_stdout_size = len(result.stdout)
        assert command_stdout_size == 0

        # Error has the output in snippet (always present)
        error_output_size = len(result.error.snippet) if result.error and result.error.snippet else 0
        assert error_output_size > 0  # Should have error info

        # Old approach would have duplicated this in both CommandResponse and ErrorEnvelope
        old_size = error_output_size * 2  # Duplicate in both places
        new_size = error_output_size  # Only in ErrorEnvelope

        # Should be 50% smaller (no duplication)
        savings = (old_size - new_size) / old_size
        assert savings >= 0.49  # At least 49% savings (accounting for rounding)

    def test_full_workflow_token_efficiency(self, client):
        """Test a full workflow demonstrating all token efficiency features."""
        # Load data (with truncation)
        load_result = client.load_data("auto", max_output_lines=2)
        assert "output truncated" in load_result.stdout or len(load_result.stdout.splitlines()) <= 4

        # Create graph and export with file path
        g = client.run_command_structured("scatter price mpg, name(WorkflowGraph, replace)")
        assert g.success
        graph_result = client.export_graphs_all(use_base64=False)

        # File path should be tiny
        assert len(graph_result.graphs[0].file_path) < 200

        # Error case - output only in ErrorEnvelope
        error_result = client.run_command_structured("bad_command")
        assert error_result.stdout == ""
        assert error_result.error.snippet is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
