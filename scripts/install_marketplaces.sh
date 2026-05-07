#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
marketplace_name="mcp-stata-marketplace"

if command -v claude >/dev/null 2>&1; then
  claude plugin marketplace add "$repo_root" --scope project
  claude plugin install "mcp-stata@${marketplace_name}" --scope project
else
  echo "Claude CLI not found; skipped Claude marketplace install." >&2
fi

if command -v codex >/dev/null 2>&1; then
  codex plugin marketplace add "$repo_root/.agents/plugins"
else
  echo "Codex CLI not found; skipped Codex marketplace install." >&2
fi

echo "Done. If Codex is already open, restart it to pick up the marketplace."