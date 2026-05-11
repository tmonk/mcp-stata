#!/bin/bash
set -e

BENCH_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$BENCH_DIR"

echo "Setting up dedicated uv environment for benchmark..."

if [ ! -d ".venv" ]; then
    uv venv
fi

source .venv/bin/activate
uv sync
uv pip install -e ../../

echo "Setup complete."
echo ""

if [ "$1" = "--release" ]; then
    echo "Running benchmark against INSTALLED release..."
    python benchmark.py
else
    echo "Running benchmark against LOCAL development mcp-stata..."
    python benchmark.py --local
fi