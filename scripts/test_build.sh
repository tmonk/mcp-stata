#!/bin/bash
# Quick build integration test script
# Run this locally to verify the build works before publishing

set -e  # Exit on error

echo "=========================================="
echo "Build Integration Test"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo -e "${YELLOW}Step 1: Running build integration tests...${NC}"
python -m pytest tests/test_build_integration.py -v -m slow

echo ""
echo -e "${GREEN}✓ All build integration tests passed!${NC}"
echo ""
echo -e "${YELLOW}Step 2: Quick import test...${NC}"

# Create a temporary venv for import test
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

python -m venv "$TEMP_DIR/venv"

if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    PYTHON="$TEMP_DIR/venv/Scripts/python.exe"
    PIP="$TEMP_DIR/venv/Scripts/pip.exe"
else
    PYTHON="$TEMP_DIR/venv/bin/python"
    PIP="$TEMP_DIR/venv/bin/pip"
fi

echo "Building package..."
python -m build --wheel --outdir "$TEMP_DIR/dist"

echo "Installing built package..."
WHEEL=$(ls "$TEMP_DIR/dist"/*.whl)
"$PIP" install "$WHEEL" > /dev/null 2>&1

echo "Testing imports..."
"$PYTHON" -c "
from mcp_stata.server import main
print('All critical imports successful!')
"

echo ""
echo -e "${GREEN}=========================================="
echo "✓ All build tests passed!"
echo "==========================================${NC}"
