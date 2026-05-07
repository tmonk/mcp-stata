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

ensure_git() {
  if command -v git &>/dev/null; then
    ok "git found: $(command -v git)"
    return
  fi

  say "git not found — attempting to install..."

  if command -v brew &>/dev/null; then
    brew install git
  elif command -v apt-get &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo apt-get update && sudo apt-get install -y git
    else
      apt-get update && apt-get install -y git
    fi
  elif command -v dnf &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo dnf install -y git
    else
      dnf install -y git
    fi
  elif command -v yum &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo yum install -y git
    else
      yum install -y git
    fi
  elif command -v zypper &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo zypper --non-interactive install git
    else
      zypper --non-interactive install git
    fi
  elif command -v pacman &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo pacman -Sy --noconfirm git
    else
      pacman -Sy --noconfirm git
    fi
  elif command -v apk &>/dev/null; then
    if command -v sudo &>/dev/null; then
      sudo apk add --no-cache git
    else
      apk add --no-cache git
    fi
  else
    err "git is required but no supported package manager was detected. Install git and re-run."
  fi

  if ! command -v git &>/dev/null; then
    err "git installation did not succeed. Install git and re-run."
  fi

  ok "git installed: $(command -v git)"
}

ensure_repo_root() {
  if [ -f "${REPO_ROOT}/scripts/setup_toolkit.py" ]; then
    return
  fi

  ensure_git
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

  # Make uv available in this session (uv installer targets ~/.local/bin)
  export PATH="${UV_BIN_DIR}:${PATH}"

  if ! command -v uv &>/dev/null; then
    err "uv installed but not on PATH. Add '${UV_BIN_DIR}' to your PATH and re-run."
  fi

  ok "uv installed: $(command -v uv)"
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
