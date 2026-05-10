"""
mcp-stata: agentic toolkit for Stata.

Lazy imports to support discovery without full dependency chain
(e.g., discovery works with 'uv run --no-project').
"""

def __getattr__(name):
    """Lazy import of StataClient to support installation-time discovery."""
    if name == "StataClient":
        from .stata_client import StataClient
        return StataClient
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = ["StataClient"]
