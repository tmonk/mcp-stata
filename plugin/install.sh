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
# Note: VERSION is derived dynamically in main() after bootstrap
VERBOSE_MODE=0
SCRIPT_VERSION='3.2.9'

# ── Configuration ─────────────────────────────────────────────────────────────
# Primary installer domain and telemetry endpoint.
INSTALL_HOST="mcp-stata-install.tdmonk.com"
INSTALL_URL_SH="https://${INSTALL_HOST}/install.sh"
TELEMETRY_URL="https://${INSTALL_HOST}/telemetry"

# GitHub fallback (used if the primary domain is unreachable).
GITHUB_REPO_URL="https://github.com/tmonk/mcp-stata"
GITHUB_RAW_URL="https://raw.githubusercontent.com/tmonk/mcp-stata/main/plugin"
INSTALL_FALLBACK_SH="${GITHUB_RAW_URL}/install.sh"

# Pull dynamic config from GitHub (optional, best-effort)
# This allows us to change the primary URL in the future without breaking old scripts.
if command -v curl >/dev/null 2>&1; then
  DYNAMIC_CONFIG=$(curl -fsSL --max-time 2 "${GITHUB_RAW_URL}/installer.json" 2>/dev/null || true)
  if [ -n "$DYNAMIC_CONFIG" ]; then
    NEW_HOST=$(printf '%s' "$DYNAMIC_CONFIG" | grep -o '"base": "[^"]*"' | head -1 | cut -d'"' -f4 | sed 's|https://||')
    if [ -n "$NEW_HOST" ]; then
      INSTALL_HOST="$NEW_HOST"
      INSTALL_URL_SH="https://${INSTALL_HOST}/install.sh"
      TELEMETRY_URL="https://${INSTALL_HOST}/telemetry"
    fi
  fi
fi

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
  printf "%b%s%b %s\n" "${DIM}" "version" "${RESET}" "$(get_version)"
  if [ "$#" -gt 0 ]; then
    printf "%b%s%b %s\n" "${DIM}" "args   " "${RESET}" "$*"
  else
    printf "%b%s%b %s\n" "${DIM}" "args   " "${RESET}" "(none)"
  fi
}

show_success() {
  boxed_title "${GREEN}" "MCP-STATA IS LIVE"
  printf "%b%s%b %s complete\n" "${GREEN}${BOLD}" "✓" "${RESET}" "${ACTION_LABEL}"
  printf "%b%s%b %s\n" "${CYAN}${BOLD}" "::" "${RESET}" "Verify by asking your agent: Do you have access to mcp-stata, an agentic toolkit for Stata?"
  blank
  printf "%b%s%b\n" "${MAGENTA}${BOLD}" "FIRST COMMANDS TO TRY" "${RESET}"
  printf "   %b%s%b %s\n" "${YELLOW}${BOLD}" "1." "${RESET}" "/stata-run sysuse auto, clear"
  printf "   %b%s%b %s\n" "${YELLOW}${BOLD}" "2." "${RESET}" "/stata-inspect"
  printf "   %b%s%b %s\n" "${YELLOW}${BOLD}" "3." "${RESET}" "/stata-run regress price mpg"
  printf "   %b%s%b %s\n" "${YELLOW}${BOLD}" "4." "${RESET}" "/stata-results"
  blank
  printf "%b%s%b\n" "${CYAN}${BOLD}" "TO UPDATE" "${RESET}"
  printf "   %b%s%b\n" "${CYAN}" "curl -LsSf ${INSTALL_URL_SH} | bash" "${RESET}"
  detail "Fallback: curl -LsSf ${INSTALL_FALLBACK_SH} | bash"
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
    uv run --no-project --no-progress --python 3.11 "${INSTALL_REPO_ROOT}/scripts/install/setup_toolkit.py" "$@"
    status=$?
  else
    uv run --no-project --no-progress --python 3.11 "${INSTALL_REPO_ROOT}/scripts/install/setup_toolkit.py" "$@" 2>&1 | while IFS= read -r line || [ -n "$line" ]; do
      format_toolkit_line "$line"
    done
    status=${PIPESTATUS[0]}
  fi
  set -e
  return "$status"
}

get_machine_id() {
  if [ "$(uname -s)" = "Darwin" ]; then
    ioreg -rd1 -c IOPlatformExpertDevice | awk '/IOPlatformUUID/ { print $3 }' | tr -d '"' 2>/dev/null || echo unknown
  else
    cat /etc/machine-id 2>/dev/null || cat /var/lib/dbus/machine-id 2>/dev/null || echo unknown
  fi
}

get_version() {
    echo "${MCP_STATA_SCRIPT_VERSION:-$SCRIPT_VERSION}"
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

# ── Logging Setup ─────────────────────────────────────────────────────────────
setup_logging() {
  LOG_FILE="${TMPDIR:-/tmp}/mcp-stata-install-$(date +%Y%m%d-%H%M%S)-$$.log"
  export MCP_STATA_INSTALL_LOG_FILE="$LOG_FILE"
  # Note: we use a subshell for tee to avoid leaving it running if main exits early
  exec > >(tee -ai "$LOG_FILE") 2>&1
}

show_help() {
  cat <<EOF
mcp-stata installer

Usage:
  install.sh [--agent <name>] [--scope <user|project>] [--dry-run] [--uninstall] [--verbose] ...

Agents:
  claude, codex, gemini, cursor, windsurf, vscode

Notes:
  - This script delegates the heavy lifting to scripts/install/setup_toolkit.py
  - Telemetry is best-effort and never affects exit status.

Examples:
  curl -fsSL ${INSTALL_URL_SH} | bash
  # Fallback: curl -fsSL ${INSTALL_FALLBACK_SH} | bash
  bash install.sh --agent cursor --dry-run
EOF
}

# ── Telemetry ─────────────────────────────────────────────────────────────────
# What is sent: event type, OS/arch, MCP client name(s), install duration, a
# unique run ID, and — on failure — the trailing portion of the install log
# (sized so the JSON-escaped payload fits inside the worker's per-event blob
# limit). No file contents, credentials, or paths are included.
# Log: $TMPDIR/mcp-stata-install-<date>-<pid>.log  (also printed on failure)
INSTALL_ID="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || \
              uuidgen 2>/dev/null || echo "$(date +%s)-$$")"
INSTALL_STAGE="init"
INSTALL_START_TIME=$(date +%s)
INSTALL_SOURCE="${MCP_STATA_INSTALL_SOURCE:-direct}"  # e.g. workbench|direct
TELEMETRY_RETRIES="${MCP_STATA_TELEMETRY_RETRIES:-3}"
TELEMETRY_TIMEOUT_SECS="${MCP_STATA_TELEMETRY_TIMEOUT_SECS:-5}"
TELEMETRY_DEBUG="${MCP_STATA_TELEMETRY_DEBUG:-0}"
TELEMETRY_ENABLED="${MCP_STATA_TELEMETRY_ENABLED:-1}"
# Trailing-log capture size for failures. Sized so a worst-case JSON-escaped
# value (lots of newlines/tabs) still lands well under the worker's 4000-char
# log_tail cap and the 8 KB total payload cap.
TELEMETRY_LOG_TAIL_BYTES="${MCP_STATA_LOG_TAIL_BYTES:-3500}"
USER_ID=""

make_user_id() {
  # Bash 3.2-compatible anonymous id. We rely on words (not digits) for entropy.
  # Example: amber-otter-sprout
  local adjectives=(
    amber aqua brisk calm cedar coral dawn dapper dune ember fern frosty glowy
    hazel ivy jade jolly keen kind lemon lilac lucid lucky lunar maple mellow
    misty mossy nimble noble ocean olive opal peach pine plum polar quartz quick
    rosy sage sandy satin silver simple snowy solar spring sunny swift thyme
    velvet vivid warm windy wisteria zesty
  )
  local nouns=(
    otter panda fox koala penguin capybara gecko puffin kitten badger rabbit
    sparrow heron falcon dolphin whale turtle lizard yak bison alpaca
    comet river forest meadow canyon summit harbor pebble lantern compass
    sprout acorn fernleaf snowflake raindrop starlight moonbeam sunburst
    gadget widget pixel prisma orbit drift ripple
  )

  local a="${adjectives[$((RANDOM % ${#adjectives[@]}))]}"
  local n1="${nouns[$((RANDOM % ${#nouns[@]}))]}"
  local n2="${nouns[$((RANDOM % ${#nouns[@]}))]}"

  # Avoid awkward repeats like otter-otter.
  if [ "$n2" = "$n1" ]; then
    n2="${nouns[$(((RANDOM + 7) % ${#nouns[@]}))]}"
  fi

  printf '%s-%s-%s' "$a" "$n1" "$n2"
}

get_user_id() {
  # Persist across installs, but avoid any filesystem writes for --dry-run / tests.
  if [ "${MCP_STATA_DRY_RUN:-0}" = "1" ]; then
    printf 'dryrun'
    return 0
  fi

  local base="${XDG_STATE_HOME:-${HOME}/.local/state}"
  local dir="${base}/mcp-stata"
  local file="${dir}/telemetry_user_id"

  if [ -n "${MCP_STATA_USER_ID:-}" ]; then
    printf '%s' "${MCP_STATA_USER_ID}"
    return 0
  fi

  if [ -f "$file" ]; then
    local v
    v="$(head -n 1 "$file" 2>/dev/null || true)"
    if [ -n "$v" ]; then
      printf '%s' "$v"
      return 0
    fi
  fi

  mkdir -p "$dir" 2>/dev/null || true
  local new
  new="$(make_user_id)"
  printf '%s\n' "$new" >"$file" 2>/dev/null || true
  printf '%s' "$new"
}

json_escape_stream() {
  # Read stdin, write a JSON-string-safe version (no surrounding quotes) on
  # stdout. Prefer python3 (full RFC 8259 escaping incl. all control chars and
  # non-BMP); fall back to awk so we still emit *something* useful when python
  # is missing (which is rare on Linux/macOS but does occur on stripped-down
  # CI/managed images — and is the difference between a useful failure event
  # and an empty `log_tail` on the dashboard).
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json, sys; sys.stdout.write(json.dumps(sys.stdin.read())[1:-1])' 2>/dev/null
    return 0
  fi
  awk '
    BEGIN { ORS = ""; first = 1 }
    {
      gsub(/\\/, "\\\\")
      gsub(/"/, "\\\"")
      gsub(/\t/, "\\t")
      gsub(/\r/, "\\r")
      if (!first) printf "\\n"
      first = 0
      printf "%s", $0
    }
  '
}

json_escape() {
  printf '%s' "$1" | json_escape_stream
}

send_telemetry() {
  local event="$1" error_code="${2:-}"
  if [ "$TELEMETRY_ENABLED" -ne 1 ]; then
    return 0
  fi
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

  # Best-effort parse of passthrough args (Bash 3.2 compatible; avoid indirect expansion).
  # Accumulate all --agent values as comma-separated so one event captures the full run.
  shift 2 || true
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --agent)
        if [ -n "${2:-}" ]; then
          client="${client:+${client},}${2}"
        fi
        shift 2
        ;;
      --agent=*)
        local _ag="${1#--agent=}"
        client="${client:+${client},}${_ag}"
        shift
        ;;
      --scope)
        scope="${2:-}"
        shift 2
        ;;
      --scope=*)
        scope="${1#--scope=}"
        shift
        ;;
      *)
        shift
        ;;
    esac
  done

  # Capture trailing portion of the install log ONLY for failure diagnostics.
  # We grab as many bytes as the worker will accept (server caps log_tail at
  # ~4000 chars after JSON escaping) so the dashboard shows the actual error
  # output of `curl … | sh`, not just the banner.
  #
  # IMPORTANT: do NOT use `python3 - <<HERE` to escape — the heredoc binds
  # python's stdin and silently drops the piped log content. (That bug shipped
  # in 3.1.x and is why every install_failure event historically had an empty
  # log_tail.) Use `python3 -c …` so the pipe stays connected.
  local log_tail=""
  if [[ "$event" == *"failure"* ]] && [ -f "${LOG_FILE:-}" ]; then
    sync 2>/dev/null || true
    log_tail="$(tail -c "${TELEMETRY_LOG_TAIL_BYTES}" "$LOG_FILE" 2>/dev/null \
      | json_escape_stream || true)"
  fi

  local telemetry_user
  if [ -n "${MCP_STATA_TELEMETRY_USERNAME:-}" ]; then
    telemetry_user="${MCP_STATA_TELEMETRY_USERNAME}"
  elif [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    telemetry_user="runner-mcp"
  else
    telemetry_user="$(id -un 2>/dev/null || echo unknown)"
  fi

  local payload
  payload="$(printf '{"event":"%s","action":"%s","stage":"%s","client":"%s","install_source":"%s","scope":"%s","user_id":"%s","username":"%s","machine_id":"%s","install_repo":"%s","install_ref":"%s","script_version":"%s","error_code":"%s","os":"%s","distro":"%s","arch":"%s","duration_ms":%d,"install_id":"%s","file":"install.sh","log_tail":"%s"}' \
        "$event" "$(json_escape "$action")" "$INSTALL_STAGE" \
        "$(json_escape "$client")" "$(json_escape "$INSTALL_SOURCE")" "$(json_escape "$scope")" "$(json_escape "$USER_ID")" \
        "$(json_escape "$telemetry_user")" "$(json_escape "$(get_machine_id)")" \
        "$(json_escape "$install_repo")" "$(json_escape "$install_ref")" "$(json_escape "$(get_version)")" \
        "$(json_escape "$error_code")" "$(uname -s | tr A-Z a-z)" "$distro" "$(uname -m)" \
        "$((duration * 1000))" "$INSTALL_ID" "$log_tail")"

  local attempt=1
  while [ "$attempt" -le "$TELEMETRY_RETRIES" ]; do
    if [ "$TELEMETRY_DEBUG" -eq 1 ]; then
      local tmp_payload
      tmp_payload="$(mktemp "${TMPDIR:-/tmp}/mcp-stata-telemetry-payload.XXXXXX")"
      printf '%s' "$payload" >"$tmp_payload"
      if command -v python3 >/dev/null 2>&1; then
        python3 - <<'PY' "$tmp_payload" 2>/dev/null || true
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
try:
    json.loads(p)
    print("telemetry payload: valid json")
except Exception as e:
    print("telemetry payload: INVALID json:", str(e))
    print(p[:400])
PY
      fi
      local tmp_resp
      tmp_resp="$(mktemp "${TMPDIR:-/tmp}/mcp-stata-telemetry.XXXXXX")"
      local http
      http="$(curl -sS -m "$TELEMETRY_TIMEOUT_SECS" -X POST "$TELEMETRY_URL" \
        -H 'content-type: application/json' \
        -d "$payload" \
        -o "$tmp_resp" -w '%{http_code}' || echo "curl_error")"
      if [ "$http" = "200" ]; then
        rm -f "$tmp_payload" || true
        rm -f "$tmp_resp" || true
        return 0
      fi
      warn "Telemetry debug: http=${http} event=${event}"
      detail "$(head -c 200 "$tmp_resp" 2>/dev/null || true)"
      rm -f "$tmp_payload" || true
      rm -f "$tmp_resp" || true
    else
      if curl -fsS -m "$TELEMETRY_TIMEOUT_SECS" -X POST "$TELEMETRY_URL" \
        -H 'content-type: application/json' \
        -d "$payload" \
        >/dev/null 2>&1; then
        return 0
      fi
    fi
    attempt=$((attempt + 1))
    sleep 0.2
  done

  # Non-fatal: installer should never fail because telemetry couldn't be delivered.
  warn "Telemetry could not be delivered (event=${event}). Dashboard may not update."
  return 0
}

err() {
  # We want failures to be informative, not masked by nounset edge-cases
  # (notably: iterating over empty arrays in Bash 3.2).
  set +u

  local message="$1"
  shift || true

  local fail_event="install_failure"
  local args=("$@")
  if [ ${#args[@]} -eq 0 ]; then
    # Avoid nounset issues if INSTALL_ARGS is unexpectedly unset.
    if [ "${INSTALL_ARGS+set}" = "set" ] && [ "${#INSTALL_ARGS[@]}" -gt 0 ]; then
      args=("${INSTALL_ARGS[@]}")
    fi
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
    unset MCP_STATA_TRANSIENT_INSTALL_SOURCE 2>/dev/null || true
    return
  fi

  # Otherwise, fetch a shallow tarball to avoid git dependency
  ensure_dependencies "curl" "tar" "gzip"

  TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcp-stata-install.XXXXXX")"
  say "Fetching mcp-stata source"
  detail "${TARBALL_URL}"

  curl -fsSL --retry 5 --retry-delay 2 --retry-connrefused "${TARBALL_URL}" | tar xz -C "${TEMP_DIR}" --strip-components=1 || err "Could not download or extract mcp-stata source" "$@"

  INSTALL_REPO_ROOT="${TEMP_DIR}"
  export MCP_STATA_TRANSIENT_INSTALL_SOURCE=1
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
  curl -fsSL --retry 5 --retry-delay 2 --retry-connrefused https://astral.sh/uv/install.sh | sh || err "Could not install uv via astral.sh" "$@"

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
  # 1. Parse critical flags early for telemetry
  MCP_STATA_DRY_RUN=0
  local start_event="install_start"
  for arg in "$@"; do
    case "$arg" in
      --verbose) VERBOSE_MODE=1 ;;
      --dry-run) MCP_STATA_DRY_RUN=1 ;;
      --uninstall) start_event="uninstall_start" ;;
    esac
  done
  export MCP_STATA_DRY_RUN

  # 2. Initialize Identity & Metadata
  USER_ID="$(get_user_id)"
  
  # 3. Emit start event IMMEDIATELY.
  # This ensures that even if bootstrap fails, we have a record of the attempt with metadata.
  send_telemetry "$start_event" "" "$@" || true

  # 4. Standard startup sequence
  setup_logging
  show_header "$@"
  detect_action_label "$@"

  for arg in "$@"; do
    if [ "$arg" = "--help" ] || [ "$arg" = "-h" ]; then
      show_help
      return 0
    fi
  done

  if [ "$(id -u)" -eq 0 ]; then
    warn "Running as root. ${ACTION_LABEL} will be local to the root user."
  fi

  trap cleanup EXIT

  # Telemetry-only mode: exercise end-to-end telemetry without mutating the machine.
  # Usage:
  #   MCP_STATA_TELEMETRY_ONLY=1 bash install.sh
  if [ "${MCP_STATA_TELEMETRY_ONLY:-}" = "1" ]; then
    INSTALL_STAGE="telemetry_only"
    local end_event="install_success"
    [ "$start_event" = "uninstall_start" ] && end_event="uninstall_success"
    send_telemetry "$end_event" "" "$@" || true
    ok "Telemetry-only mode complete"
    detail "install_id=${INSTALL_ID}"
    return 0
  fi

  stage "BOOTSTRAP SOURCE"
  INSTALL_STAGE="ensure_repo_root"
  ensure_repo_root

  stage "BOOTSTRAP RUNTIME"
  INSTALL_STAGE="ensure_uv"
  ensure_uv

  # Bash 3.2 (macOS default) doesn't support `${var^^}`.
  local action_upper
  action_upper="$(printf '%s' "$ACTION_LABEL" | tr '[:lower:]' '[:upper:]')"
  stage "${action_upper} TOOLKIT"
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
