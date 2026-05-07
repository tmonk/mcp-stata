#!/usr/bin/env bash
# Thin wrapper around the shared Python installer so all agent setup logic lives
# in one place.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

exec python3 "${REPO_ROOT}/scripts/setup_toolkit.py" "$@"
