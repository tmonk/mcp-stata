#!/bin/bash
set -e

# Benchmark directory
BENCH_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$BENCH_DIR"

echo "Setting up dedicated uv environment for benchmark..."

# Create venv if not exists
if [ ! -d ".venv" ]; then
    uv venv
fi

# Source venv
source .venv/bin/activate

# Install dependencies from pyproject.toml
uv sync

# Install mcp-stata in editable mode from the parent directory
# This ensures it can find the mcp_stata package
uv pip install -e ../../

echo "Setup complete."
echo "To run the benchmark:"
echo "1. Source the environment: source .venv/bin/activate"
echo "2. Set your API key: export GEMINI_API_KEY='your_key'"
echo "3. Run the script: python benchmark.py"
