#!/usr/bin/env bash
# Bootstrap installer for mcp-stata.
# Ensures uv is available, then delegates all setup logic to the Python installer.
set -euo pipefail

# ── Formatting ────────────────────────────────────────────────────────────────
BOLD=''; DIM=''; RED=''; GREEN=''; YELLOW=''; BLUE=''; MAGENTA=''; CYAN=''; RESET=''
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD='\033[1m'
  DIM='\033[2m'
  RED='\033[31m'
  GREEN='\033[32m'
  YELLOW='\033[33m'
  BLUE='\033[34m'
  MAGENTA='\033[35m'
  CYAN='\033[36m'
  RESET='\033[0m'
fi

ACTION_LABEL=""
INSTALL_ARGS=("$@")
AUTHOR_NAME="Thomas Monk"
AUTHOR_AFFILIATION="London School of Economics"
AUTHOR_EMAIL="t.d.monk@lse.ac.uk"
VERBOSE_MODE=0

for arg in "$@"; do
  if [[ "$arg" == "--verbose" ]]; then
    VERBOSE_MODE=1
    break
  fi
done

paint() {
  local style="$1"
  shift
  printf '%b%s%b' "$style" "$*" "$RESET"
}

blank() {
  printf '\n'
}

say() {
  printf "%b%s%b %s\n" "${CYAN}${BOLD}" "›" "${RESET}" "$1"
}

ok() {
  printf "%b%s%b %s\n" "${GREEN}${BOLD}" "✓" "${RESET}" "$1"
}

warn() {
  printf "%b%s%b %s\n" "${YELLOW}${BOLD}" "!" "${RESET}" "$1" >&2
}

rule() {
  paint "$1" "======================================================================"
  printf '\n'
}

boxed_title() {
  local color="$1"
  local title="$2"
  blank
  rule "${color}${BOLD}"
  printf "%b%s%b\n" "${color}${BOLD}" "$title" "${RESET}"
  rule "${color}${BOLD}"
}

stage() {
  local title="$1"
  boxed_title "${BLUE}" "$title"
}

detail() {
  printf "    %b%s%b %s\n" "${DIM}" "•" "${RESET}" "$1"
}

show_header() {
  cat <<EOF
$(paint "${MAGENTA}${BOLD}" "======================================================================")
$(paint "${CYAN}${BOLD}" "                                    __        __")
$(paint "${CYAN}${BOLD}" "   ____ ___  _________        _____/ /_____ _/ /_____ _")
$(paint "${CYAN}${BOLD}" "  / __ \`__ \\/ ___/ __ \\______/ ___/ __/ __ \`/ __/ __ \`/")
$(paint "${CYAN}${BOLD}" " / / / / / / /__/ /_/ /_____(__  ) /_/ /_/ / /_/ /_/ /")
$(paint "${CYAN}${BOLD}" "/_/ /_/ /_/\\___/ .___/     /____/\\__/\\__,_/\\__/\\__,_/")
$(paint "${CYAN}${BOLD}" "              /_/                                        installer")
$(paint "${MAGENTA}${BOLD}" "======================================================================")
EOF

  printf "%b%s%b %s\n" "${YELLOW}${BOLD}" "AUTHOR " "${RESET}" "$AUTHOR_NAME"
  printf "%b%s%b %s\n" "${YELLOW}${BOLD}" "AT     " "${RESET}" "$AUTHOR_AFFILIATION"
  printf "%b%s%b %s\n" "${YELLOW}${BOLD}" "CONTACT" "${RESET}" "$AUTHOR_EMAIL"
  printf "%b%s%b %s\n" "${DIM}" "note   " "${RESET}" "Questions, bugs, or weird installs: please get in touch."
  blank
  printf "%b%s%b %s\n" "${DIM}" "log    " "${RESET}" "$LOG_FILE"
  printf "%b%s%b %s\n" "${DIM}" "host   " "${RESET}" "$(uname -srm 2>/dev/null || echo unknown)"
  printf "%b%s%b %s\n" "${DIM}" "shell  " "${RESET}" "bash ${BASH_VERSION:-?}"
  printf "%b%s%b %s\n" "${DIM}" "user   " "${RESET}" "$(id -un 2>/dev/null) (uid=$(id -u))"
  if [ "$#" -gt 0 ]; then
    printf "%b%s%b %s\n" "${DIM}" "args   " "${RESET}" "$*"
  else
    printf "%b%s%b %s\n" "${DIM}" "args   " "${RESET}" "(none)"
  fi
}

show_success() {
  printf "%b%s%b %s complete\n" "${GREEN}${BOLD}" "✓" "${RESET}" "${ACTION_LABEL}"
  printf "%b%s%b %s\n" "${CYAN}${BOLD}" "::" "${RESET}" "Verify by asking your agent: Do you have access to mcp-stata, an agentic toolkit for Stata?"
  blank
  printf "%b%s%b\n" "${MAGENTA}${BOLD}" "FIRST COMMANDS TO TRY" "${RESET}"
  printf "   %b%s%b %s\n" "${YELLOW}${BOLD}" "1." "${RESET}" "/stata-run sysuse auto, clear"
  printf "   %b%s%b %s\n" "${YELLOW}${BOLD}" "2." "${RESET}" "/stata-inspect"
  printf "   %b%s%b %s\n" "${YELLOW}${BOLD}" "3." "${RESET}" "/stata-run regress price mpg"
  printf "   %b%s%b %s\n" "${YELLOW}${BOLD}" "4." "${RESET}" "/stata-results"
  blank
  printf "%b%s%b %s\n" "${DIM}" "log    " "${RESET}" "$LOG_FILE"
  printf "%b%s%b %s\n" "${DIM}" "contact" "${RESET}" "$AUTHOR_EMAIL"
}

show_failure() {
  local message="$1"

  blank
  printf "%b%s%b %s\n" "${RED}${BOLD}" "✖" "${RESET}" "$message" >&2
  boxed_title "${RED}" "FAILED: ${ACTION_LABEL} COULD NOT BE COMPLETED" >&2
  printf >&2 "%b%s%b %s\n" "${DIM}" "log       " "${RESET}" "$LOG_FILE"
  printf >&2 "%b%s%b %s\n" "${DIM}" "report    " "${RESET}" "https://github.com/tmonk/mcp-stata/issues/new?template=install-failure.yml"
  printf >&2 "%b%s%b %s\n" "${DIM}" "contact   " "${RESET}" "$AUTHOR_EMAIL"
  printf >&2 "%b%s%b %s\n" "${DIM}" "clipboard " "${RESET}" "pbcopy < \"${LOG_FILE}\""
  printf >&2 "%b%s%b %s\n" "${DIM}" "" "${RESET}" "xclip -selection clipboard < \"${LOG_FILE}\""
  printf >&2 "%b%s%b %s\n" "${DIM}" "" "${RESET}" "wl-copy < \"${LOG_FILE}\""
  printf >&2 "%b%s%b %s\n" "${DIM}" "" "${RESET}" "clip.exe < \"${LOG_FILE}\""
}

format_toolkit_line() {
  local line="$1"

  if [[ "$line" == "Adding marketplace"* ]]; then
    if [[ "$line" == *"already on disk"* ]]; then
      printf "   %b%s%b %s\n" "${GREEN}${BOLD}" "+" "${RESET}" "Marketplace already configured"
    elif [[ "$line" == *"Successfully added marketplace:"* ]]; then
      printf "   %b%s%b %s\n" "${GREEN}${BOLD}" "+" "${RESET}" "${line#*✔ }"
    else
      printf "   %b%s%b %s\n" "${MAGENTA}${BOLD}" ">" "${RESET}" "Adding marketplace"
    fi
    return
  fi

  if [[ "$line" == "Installing plugin "* ]]; then
    if [[ "$line" == *"already installed"* ]]; then
      printf "   %b%s%b %s\n" "${GREEN}${BOLD}" "+" "${RESET}" "Plugin already installed"
    elif [[ "$line" == *"Successfully installed plugin:"* ]]; then
      printf "   %b%s%b %s\n" "${GREEN}${BOLD}" "+" "${RESET}" "${line#*✔ }"
    else
      printf "   %b%s%b %s\n" "${MAGENTA}${BOLD}" ">" "${RESET}" "Installing plugin"
    fi
    return
  fi

  case "$line" in
    "=== mcp-stata Toolkit Setup ===")
      :
      ;;
    "[STEP] "*)
      printf "%b%s%b %s\n" "${MAGENTA}${BOLD}" ">>" "${RESET}" "${line#"[STEP] "}"
      ;;
    "  [SUCCESS] "*)
      printf "   %b%s%b %s\n" "${GREEN}${BOLD}" "+" "${RESET}" "${line#"  [SUCCESS] "}"
      ;;
    "  [WARNING] "*)
      printf "   %b%s%b %s\n" "${YELLOW}${BOLD}" "!" "${RESET}" "${line#"  [WARNING] "}"
      ;;
    "  [ERROR] "*)
      printf "   %b%s%b %s\n" "${RED}${BOLD}" "x" "${RESET}" "${line#"  [ERROR] "}"
      ;;
    "=== Setup Complete ===")
      boxed_title "${GREEN}" "SETUP COMPLETE"
      ;;
    "Canonical server name: "*)
      :
      ;;
    "Verify by asking your agent: "*)
      :
      ;;
    "Quick start: "*)
      :
      ;;
    "")
      blank
      ;;
    *)
      printf "   %s\n" "$line"
      ;;
  esac
}

run_toolkit_installer() {
  local status=0
  set +e
  if [ "$VERBOSE_MODE" -eq 1 ]; then
    uv run --python 3.11 "${INSTALL_REPO_ROOT}/scripts/install/setup_toolkit.py" "$@"
    status=$?
  else
    uv run --python 3.11 "${INSTALL_REPO_ROOT}/scripts/install/setup_toolkit.py" "$@" 2>&1 | while IFS= read -r line || [ -n "$line" ]; do
      format_toolkit_line "$line"
    done
    status=${PIPESTATUS[0]}
  fi
  set -e
  return "$status"
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE="${TMPDIR:-/tmp}/mcp-stata-install-$(date +%Y%m%d-%H%M%S)-$$.log"
export MCP_STATA_INSTALL_LOG_FILE="$LOG_FILE"
exec > >(tee -ai "$LOG_FILE") 2>&1
show_header "$@"

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
        "$event" "$(json_escape "$action")" "$INSTALL_STAGE" \
        "$(json_escape "$client")" "$(json_escape "$INSTALL_SOURCE")" "$(json_escape "$scope")" \
        "$(json_escape "$install_repo")" "$(json_escape "$install_ref")" "$(json_escape "$script_version")" \
        "$(json_escape "$error_code")" "$(uname -s | tr A-Z a-z)" "$distro" "$(uname -m)" \
        "$((duration * 1000))" "$INSTALL_ID")" \
    >/dev/null 2>&1 || true
}

err() {
  local message="$1"
  shift || true

  local fail_event="install_failure"
  local args=("$@")
  if [ ${#args[@]} -eq 0 ]; then
    args=("${INSTALL_ARGS[@]}")
  fi

  for arg in "${args[@]}"; do
    if [ "$arg" = "--uninstall" ]; then
      fail_event="uninstall_failure"
      break
    fi
  done

  send_telemetry "$fail_event" "$message" "${args[@]}"
  show_failure "$message"
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

say "Missing system dependencies: ${missing[*]}"
  detail "Attempting package-manager install"

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
    err "Required dependencies are missing and no supported package manager was detected." "$@"
  fi

  for cmd in "${missing[@]}"; do
    if ! command -v "$cmd" &>/dev/null; then
      err "Installation of ${cmd} did not succeed. Please install it manually and re-run." "$@"
    fi
  done

  ok "System dependencies ready"
}

ensure_repo_root() {
  # If we're already in a checkout, use it.
  if [ -f "${REPO_ROOT}/scripts/install/setup_toolkit.py" ]; then
    detail "Using local checkout at ${REPO_ROOT}"
    return
  fi

  # Otherwise, fetch a shallow tarball to avoid git dependency
  ensure_dependencies "curl" "tar" "gzip"

  TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcp-stata-install.XXXXXX")"
  say "Fetching mcp-stata source"
  detail "${TARBALL_URL}"

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
    ok "uv already available ($(uv --version 2>/dev/null || echo unknown))"
    return
  fi

  say "Installing uv"
  detail "Bootstrap via https://astral.sh/uv/install.sh"
  curl -fsSL --retry 5 --retry-delay 2 --retry-connrefused https://astral.sh/uv/install.sh | sh

  # Search for uv in common locations to refresh the current PATH
  CANDIDATE_PATHS=("${HOME}/.local/bin" "${XDG_BIN_HOME:-}" "${HOME}/.cargo/bin")
  for path in "${CANDIDATE_PATHS[@]}"; do
    if [ -n "$path" ] && [ -d "$path" ]; then
      export PATH="${path}:${PATH}"
      if command -v uv &>/dev/null; then
        ok "uv installed ($(uv --version 2>/dev/null || echo unknown))"
        return
      fi
    fi
  done

  if ! command -v uv &>/dev/null; then
    err "uv is not on PATH. Please add it manually and re-run."
  fi
}

detect_action_label() {
  ACTION_LABEL="Installation"
  for arg in "$@"; do
    if [ "$arg" = "--uninstall" ]; then
      ACTION_LABEL="Uninstall"
      return
    fi
  done
}

# ── Entry point ───────────────────────────────────────────────────────────────
main() {
  detect_action_label "$@"

  if [ "$(id -u)" -eq 0 ]; then
    warn "Running as root. ${ACTION_LABEL} will be local to the root user."
  fi

  trap cleanup EXIT

  stage "BOOTSTRAP SOURCE"
  INSTALL_STAGE="ensure_repo_root"
  ensure_repo_root

  stage "BOOTSTRAP RUNTIME"
  INSTALL_STAGE="ensure_uv"
  ensure_uv

  stage "${ACTION_LABEL^^} TOOLKIT"
  detail "Delegating to setup_toolkit.py"
  INSTALL_STAGE="setup_toolkit"
  run_toolkit_installer "$@" || err "Python installer failed" "$@"

  local event="install_success"
  for arg in "$@"; do
    if [ "$arg" = "--uninstall" ]; then
      event="uninstall_success"
      break
    fi
  done

  send_telemetry "$event" "" "$@"
  show_success
}

main "$@"
