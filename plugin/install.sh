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

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE="${TMPDIR:-/tmp}/mcp-stata-install-$(date +%Y%m%d-%H%M%S)-$$.log"
exec > >(tee -ai "$LOG_FILE") 2>&1

cat <<EOF
── mcp-stata installer ──
Log:    $LOG_FILE
OS:     $(uname -srm 2>/dev/null || echo unknown)
Shell:  bash ${BASH_VERSION:-?}
User:   $(id -un 2>/dev/null) (uid=$(id -u))
Args:   $*
──
EOF

# ── Telemetry ─────────────────────────────────────────────────────────────────
TELEMETRY_URL="https://mcp-stata-install.tdmonk.com/telemetry"
INSTALL_ID="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || \
              uuidgen 2>/dev/null || echo "$(date +%s)-$$")"
INSTALL_STAGE="init"
INSTALL_START_TIME=$(date +%s)
INSTALL_SOURCE="${MCP_STATA_INSTALL_SOURCE:-direct}"  # e.g. workbench|direct

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

send_telemetry() {
  local event="$1" error_code="${2:-}"
  local duration=$(( $(date +%s) - INSTALL_START_TIME ))
  local distro=""
  [ -f /etc/os-release ] && distro="$(. /etc/os-release && echo "${ID:-unknown}-${VERSION_ID:-}")"
  [ "$(uname -s)" = "Darwin" ] && distro="macos-$(sw_vers -productVersion 2>/dev/null || echo unknown)"
  local action="install"
  case "$event" in
    uninstall_*) action="uninstall" ;;
  esac

  local client=""
  local scope=""
  local install_ref="${MCP_STATA_REF:-}"
  local install_repo="${MCP_STATA_REPO_URL:-}"
  local script_version="${MCP_STATA_SCRIPT_VERSION:-}"

  # Best-effort parse of passthrough args.
  for ((i=1; i<=$#; i++)); do
    local arg="${!i}"
    if [ "$arg" = "--agent" ] && [ $((i+1)) -le $# ]; then
      client="${!((i+1))}"
    fi
    if [[ "$arg" == --agent=* ]]; then
      client="${arg#--agent=}"
    fi
    if [ "$arg" = "--scope" ] && [ $((i+1)) -le $# ]; then
      scope="${!((i+1))}"
    fi
    if [[ "$arg" == --scope=* ]]; then
      scope="${arg#--scope=}"
    fi
  done

  curl -fsS -m 3 -X POST "$TELEMETRY_URL" \
    -H 'content-type: application/json' \
    -d "$(printf '{"event":"%s","action":"%s","stage":"%s","client":"%s","install_source":"%s","scope":"%s","install_repo":"%s","install_ref":"%s","script_version":"%s","error_code":"%s","os":"%s","distro":"%s","arch":"%s","duration_ms":%d,"install_id":"%s","file":"install.sh"}' \
        "$event" "$INSTALL_STAGE" "$(json_escape "$error_code")" \
        "$(json_escape "$action")" "$(json_escape "$client")" "$(json_escape "$INSTALL_SOURCE")" "$(json_escape "$scope")" \
        "$(json_escape "$install_repo")" "$(json_escape "$install_ref")" "$(json_escape "$script_version")" \
        "$(uname -s | tr A-Z a-z)" "$distro" "$(uname -m)" \
        "$((duration * 1000))" "$INSTALL_ID")" \
    >/dev/null 2>&1 || true
}

err() {
  local fail_event="install_failure"
  for arg in "$@"; do
    if [ "$arg" = "--uninstall" ]; then
      fail_event="uninstall_failure"
      break
    fi
  done
  send_telemetry "$fail_event" "$1" "$@"
  printf "${RED}${BOLD}[ERROR]${RESET} %s\n" "$1" >&2
  cat >&2 <<EOF

──────────────────────────────────────────────────────────────────
Installation failed. Full log saved to:
  ${LOG_FILE}

Please open a bug report and paste the log contents:
  https://github.com/tmonk/mcp-stata/issues/new?template=install-failure.yml

Copy log to clipboard:
  macOS:         pbcopy < "${LOG_FILE}"
  Linux (X11):   xclip -selection clipboard < "${LOG_FILE}"
  Linux (Wayl.): wl-copy < "${LOG_FILE}"
  WSL:           clip.exe < "${LOG_FILE}"
──────────────────────────────────────────────────────────────────
EOF
  exit 1
}

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
REF="${MCP_STATA_REF:-main}"
TARBALL_URL="${REPO_URL}/archive/${REF}.tar.gz"

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
  if [ -f "${REPO_ROOT}/scripts/install/setup_toolkit.py" ]; then
    return
  fi

  # Otherwise, fetch a shallow tarball to avoid git dependency
  ensure_dependencies "curl" "tar" "gzip"
  
  TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcp-stata-install.XXXXXX")"
  say "Fetching mcp-stata source..."
  
  curl -fsSL --retry 5 --retry-delay 2 --retry-connrefused "${TARBALL_URL}" | tar xz -C "${TEMP_DIR}" --strip-components=1
  
  INSTALL_REPO_ROOT="${TEMP_DIR}"
  ok "Source extracted to ${INSTALL_REPO_ROOT}"
}

# ── Bootstrap uv ──────────────────────────────────────────────────────────────
ensure_uv() {
  # Always ensure extraction tools and downloader are present
  ensure_dependencies "curl" "tar" "gzip"

  # Fast path: uv already on PATH — nothing to do.
  if command -v uv &>/dev/null; then
    ok "uv already installed ($(uv --version 2>/dev/null || echo unknown))"
    return
  fi

  say "Installing uv..."
  curl -fsSL --retry 5 --retry-delay 2 --retry-connrefused https://astral.sh/uv/install.sh | sh

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
  INSTALL_STAGE="ensure_repo_root"; ensure_repo_root
  INSTALL_STAGE="ensure_uv";        ensure_uv
  
  say "Launching mcp-stata installer..."
  INSTALL_STAGE="setup_toolkit"
  uv run --python 3.11 "${INSTALL_REPO_ROOT}/scripts/install/setup_toolkit.py" "$@" || err "Python installer failed"
  
  local event="install_success"
  # Check if --uninstall is in the arguments
  for arg in "$@"; do
    if [ "$arg" = "--uninstall" ]; then
      event="uninstall_success"
      break
    fi
  done
  send_telemetry "$event" "" "$@"
}

main "$@"