#!/usr/bin/env bash
# Bootstrap installer for mcp-stata.
# Ensures uv is available, then delegates all setup logic to the Python installer.
set -euo pipefail

# ── Formatting ────────────────────────────────────────────────────────────────
BOLD=''; RED=''; GREEN=''; YELLOW=''; CYAN=''; RESET=''
if [ -t 1 ]; then
  BOLD='\033[1m'; RED='\033[31m'
  GREEN='\033[32m'; YELLOW='\033[33m'; CYAN='\033[36m'; RESET='\033[0m'
fi

say()  { printf "${CYAN}${BOLD}[INFO]${RESET}  %s\n"  "$1"; }
ok()   { printf "${GREEN}${BOLD}[OK]${RESET}    %s\n"  "$1"; }
warn() { printf "${YELLOW}${BOLD}[WARN]${RESET}  %s\n" "$1" >&2; }
err()  { printf "${RED}${BOLD}[ERROR]${RESET} %s\n"   "$1" >&2; exit 1; }

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
UV_BIN_DIR="${HOME}/.local/bin"

# ── Bootstrap uv ──────────────────────────────────────────────────────────────
ensure_uv() {
  if command -v uv &>/dev/null; then
    ok "uv found: $(command -v uv)"
    return
  fi

  say "uv not found — installing..."

  # Prefer curl; fall back to wget
  if command -v curl &>/dev/null; then
    curl -fsSL https://astral.sh/uv/install.sh | sh
  elif command -v wget &>/dev/null; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    err "Neither 'curl' nor 'wget' found. Install one and re-run."
  fi

  # Make uv available in this session (uv installer targets ~/.local/bin)
  export PATH="${UV_BIN_DIR}:${PATH}"

  if ! command -v uv &>/dev/null; then
    err "uv installed but not on PATH. Add '${UV_BIN_DIR}' to your PATH and re-run."
  fi

  ok "uv installed: $(command -v uv)"
}

# ── Entry point ───────────────────────────────────────────────────────────────
main() {
  ensure_uv
  say "Launching mcp-stata installer..."
  exec uv run --python 3.11 "${REPO_ROOT}/scripts/setup_toolkit.py" "$@"
}

main "$@"
