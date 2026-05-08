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
REPO_URL="https://github.com/tmonk/mcp-stata.git"

INSTALL_REPO_ROOT="${REPO_ROOT}"
TEMP_CLONE_DIR=""

cleanup() {
  if [ -n "${TEMP_CLONE_DIR}" ] && [ -d "${TEMP_CLONE_DIR}" ]; then
    rm -rf "${TEMP_CLONE_DIR}" || true
  fi
}

ensure_dependencies() {
  local missing=()
  for cmd in git tar gzip; do
    if ! command -v "$cmd" &>/dev/null; then
      missing+=("$cmd")
    fi
  done

  if [ ${#missing[@]} -eq 0 ]; then
    return
  fi

  say "Missing dependencies: ${missing[*]} — attempting to install..."

  if command -v brew &>/dev/null; then
    brew install "${missing[@]}"
  elif command -v apt-get &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo apt-get update && sudo apt-get install -y "${missing[@]}"
    else
      apt-get update && apt-get install -y "${missing[@]}"
    fi
  elif command -v dnf &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo dnf install -y "${missing[@]}"
    else
      dnf install -y "${missing[@]}"
    fi
  elif command -v yum &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo yum install -y "${missing[@]}"
    else
      yum install -y "${missing[@]}"
    fi
  elif command -v zypper &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo zypper --non-interactive install "${missing[@]}"
    else
      zypper --non-interactive install "${missing[@]}"
    fi
  elif command -v pacman &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo pacman -Sy --noconfirm "${missing[@]}"
    else
      pacman -Sy --noconfirm "${missing[@]}"
    fi
  elif command -v apk &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo apk add --no-cache "${missing[@]}"
    else
      apk add --no-cache "${missing[@]}"
    fi
  else
    err "The following dependencies are required but no supported package manager was detected: ${missing[*]}. Please install them and re-run."
  fi

  for cmd in "${missing[@]}"; do
    if ! command -v "$cmd" &>/dev/null; then
      err "Installation of $cmd did not succeed. Please install it manually and re-run."
    fi
  done

  ok "Dependencies satisfied: git, tar, gzip"
}

ensure_repo_root() {
  if [ -f "${REPO_ROOT}/scripts/setup_toolkit.py" ]; then
    return
  fi

  ensure_dependencies
  TEMP_CLONE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcp-stata-install.XXXXXX")"
  say "Cloning mcp-stata into temporary directory..."
  git clone --depth 1 "${REPO_URL}" "${TEMP_CLONE_DIR}"
  INSTALL_REPO_ROOT="${TEMP_CLONE_DIR}"
  ok "Repository cloned"
}

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

  # Make uv available in this session. uv installer defaults to ~/.local/bin or $XDG_BIN_HOME
  CANDIDATE_PATHS=("${HOME}/.local/bin" "${XDG_BIN_HOME:-}" "${HOME}/.cargo/bin")
  for path in "${CANDIDATE_PATHS[@]}"; do
    if [ -n "$path" ] && [ -d "$path" ]; then
      export PATH="${path}:${PATH}"
      if command -v uv &>/dev/null; then
        ok "uv installed and found in ${path}"
        return
      fi
    fi
  done

  err "uv installed but not found on PATH. Please add it manually and re-run."
}

# ── Entry point ───────────────────────────────────────────────────────────────
main() {
  trap cleanup EXIT
  ensure_repo_root
  ensure_uv
  say "Launching mcp-stata installer..."
  uv run --python 3.11 "${INSTALL_REPO_ROOT}/scripts/setup_toolkit.py" "$@"
}

main "$@"
