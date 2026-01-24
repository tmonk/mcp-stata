"""
Test token efficiency optimizations in MCP Stata responses.

This test verifies that the MCP server returns compact, token-efficient
responses by minimizing JSON verbosity, avoiding output duplication,
and using file paths instead of base64 for graph exports.
"""

import pytest
import json
from pathlib import Path

# Configure Stata before importing sfi-dependent modules
import stata_setup
from conftest import configure_stata_for_tests

try:
    stata_dir, stata_flavor = configure_stata_for_tests()
    stata_setup.config(stata_dir, stata_flavor)
except (FileNotFoundError, PermissionError) as e:
    pytest.skip(f"Stata not found or not executable: {e}", allow_module_level=True)


# Mark all tests in this module as requiring Stata
pytestmark = pytest.mark.requires_stata


class TestGraphExportTokenEfficiency:
    """Test graph export with file paths."""

    def test_export_graphs_default_returns_file_paths(self, client):
        """Default export_graphs_all() returns file paths, not base64."""
        s = client.run_command_structured("sysuse auto, clear")
        assert s.success is True
        g = client.run_command_structured("scatter price mpg, name(TestGraph, replace)")
        assert g.success is True

        result = client.export_graphs_all()

        assert len(result.graphs) >= 1
        graph = result.graphs[0]

        # Default: file_path is set
        assert graph.file_path is not None
        assert Path(graph.file_path).exists()
        assert graph.file_path.endswith(".svg")


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


@pytest.mark.asyncio
class TestJSONCompactness:
    """Test that JSON responses are compact (no indentation)."""
    async def _run_command_async(self, command: str) -> str:
        """Helper to run command and get JSON response."""
        from mcp_stata.server import run_command, session_manager
        await session_manager.start()
        return await run_command(command)

    async def test_run_command_returns_compact_json(self):
        """Server tools should return compact JSON without indentation."""
        result_str = await self._run_command_async("display 1+1")

        # Parse to ensure it's valid JSON
        parsed = json.loads(result_str)
        assert parsed["rc"] == 0

        # Check that it's compact - no newlines except in actual content
        # We check for common indentation patterns.
        assert result_str.find('  "') == -1  # No double-space indent
        assert result_str.find('\n  ') == -1  # No newline + indent

    async def test_graph_export_returns_compact_json(self):
        """Graph export should return compact JSON."""
        # Initialize with a graph
        await self._run_command_async("sysuse auto, clear")
        await self._run_command_async("scatter price mpg, name(CompactTest, replace)")

        from mcp_stata.server import export_graphs_all
        result_str = await export_graphs_all()  # Already returns JSON string
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

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
