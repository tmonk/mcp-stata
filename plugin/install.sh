#!/usr/bin/env bash
# Bootstrap installer for mcp-stata.
# Ensures uv is available, then delegates all setup logic to the Python installer.
set -euo pipefail

# ── Formatting ────────────────────────────────────────────────────────────────
BOLD=''; RED=''; GREEN=''; YELLOW=''; CYAN=''; RESET=''
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD='\033[1m'; RED='\033[31m'
  GREEN='\033[32m'; YELLOW='\033[33m'; CYAN='\033[36m'; RESET='\033[0m'
fi

say()  { printf "${CYAN}${BOLD}[INFO]${RESET}  %s\n"  "$1"; }
ok()   { printf "${GREEN}${BOLD}[OK]${RESET}    %s\n"  "$1"; }
warn() { printf "${YELLOW}${BOLD}[WARN]${RESET}  %s\n" "$1" >&2; }
err()  { printf "${RED}${BOLD}[ERROR]${RESET} %s\n"   "$1" >&2; exit 1; }

# ── Paths ─────────────────────────────────────────────────────────────────────
# Handle local file execution vs piped/remote execution
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
    # Piped or source-less execution
    REPO_ROOT="$PWD"
fi

REPO_URL="${MCP_STATA_REPO_URL:-https://github.com/tmonk/mcp-stata}"
TARBALL_URL="${REPO_URL}/archive/refs/heads/main.tar.gz"

INSTALL_REPO_ROOT="${REPO_ROOT}"
TEMP_DIR=""

cleanup() {
  if [ -n "${TEMP_DIR}" ] && [ -d "${TEMP_DIR}" ]; then
    rm -rf "${TEMP_DIR}" || true
  fi
}

# ── Dependency Management ─────────────────────────────────────────────────────
ensure_dependencies() {
  local missing=()
  local targets=("$@")
  
  for cmd in "${targets[@]}"; do
    if ! command -v "$cmd" &>/dev/null; then
      missing+=("$cmd")
    fi
  done

  if [ ${#missing[@]} -eq 0 ]; then
    return
  fi

  say "Missing system dependencies: ${missing[*]} — attempting to install..."

  SUDO=$(command -v sudo || true)

  if command -v brew &>/dev/null; then
    brew install "${missing[@]}"
  elif command -v apt-get &>/dev/null; then
    $SUDO apt-get update && $SUDO apt-get install -y "${missing[@]}"
  elif command -v dnf &>/dev/null; then
    $SUDO dnf install -y "${missing[@]}"
  elif command -v yum &>/dev/null; then
    $SUDO yum install -y "${missing[@]}"
  elif command -v zypper &>/dev/null; then
    $SUDO zypper --non-interactive install "${missing[@]}"
  elif command -v pacman &>/dev/null; then
    $SUDO pacman -Sy --needed --noconfirm "${missing[@]}"
  elif command -v apk &>/dev/null; then
    $SUDO apk add --no-cache "${missing[@]}"
  else
    err "The following dependencies are required but no supported package manager was detected: ${missing[*]}. Please install them and re-run."
  fi

  for cmd in "${missing[@]}"; do
    if ! command -v "$cmd" &>/dev/null; then
      err "Installation of $cmd did not succeed. Please install it manually and re-run."
    fi
  done
}

ensure_repo_root() {
  # If we're already in a checkout, use it.
  if [ -f "${REPO_ROOT}/scripts/setup_toolkit.py" ]; then
    return
  fi

  # Otherwise, fetch a shallow tarball to avoid git dependency
  ensure_dependencies "curl" "tar" "gzip"
  
  TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcp-stata-install.XXXXXX")"
  say "Fetching mcp-stata source..."
  
  curl -LsSf "${TARBALL_URL}" | tar xz -C "${TEMP_DIR}" --strip-components=1
  
  INSTALL_REPO_ROOT="${TEMP_DIR}"
  ok "Source extracted to ${INSTALL_REPO_ROOT}"
}

# ── Bootstrap uv ──────────────────────────────────────────────────────────────
ensure_uv() {
  # Always ensure extraction tools and downloader are present
  ensure_dependencies "curl" "tar" "gzip"

  # We invoke the official installer. It's idempotent.
  say "Ensuring uv is installed..."
  curl -fsSL https://astral.sh/uv/install.sh | sh

  # Search for uv in common locations to refresh the current PATH
  CANDIDATE_PATHS=("${HOME}/.local/bin" "${XDG_BIN_HOME:-}" "${HOME}/.cargo/bin")
  for path in "${CANDIDATE_PATHS[@]}"; do
    if [ -n "$path" ] && [ -d "$path" ]; then
      export PATH="${path}:${PATH}"
      if command -v uv &>/dev/null; then
        return
      fi
    fi
  done

  if ! command -v uv &>/dev/null; then
    err "uv is not on PATH. Please add it manually and re-run."
  fi
}

# ── Entry point ───────────────────────────────────────────────────────────────
main() {
  # Root check
  if [ "$(id -u)" -eq 0 ]; then
    warn "Running as root. Installation will be local to the root user."
  fi

  trap cleanup EXIT
  ensure_repo_root
  ensure_uv
  
  say "Launching mcp-stata installer..."
  uv run --python 3.11 "${INSTALL_REPO_ROOT}/scripts/setup_toolkit.py" "$@"
}

main "$@"
