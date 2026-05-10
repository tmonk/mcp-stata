#!/bin/bash

# ─────────────────────────────────────────────
#  Colors & symbols
# ─────────────────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
RESET='\033[0m'

PASS="✔"
FAIL="✘"
RUN="▶"
CLOCK="⏱"
FILE="📄"

# ─────────────────────────────────────────────
#  Setup
# ─────────────────────────────────────────────
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTDIR="benchmarks/test_suite"
OUTFILE="${OUTDIR}/bench_${TIMESTAMP}.txt"
mkdir -p "$OUTDIR"

print_header() {
  echo
  echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}${CYAN}║         BENCHMARK TEST RUNNER            ║${RESET}"
  echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${RESET}"
  echo -e "  ${DIM}Started : $(date '+%Y-%m-%d %H:%M:%S')${RESET}"
  echo -e "  ${DIM}Output  : ${OUTFILE}${RESET}"
  echo
}

print_divider() {
  echo -e "${DIM}  ──────────────────────────────────────────${RESET}"
}

# ─────────────────────────────────────────────
#  Live tail — filters & colorizes pytest output
# ─────────────────────────────────────────────
live_tail() {
  tail -f "$1" | while IFS= read -r line; do
    if   [[ "$line" =~ PASSED  ]]; then echo -e "  ${GREEN}${PASS} ${line}${RESET}"
    elif [[ "$line" =~ FAILED  ]]; then echo -e "  ${RED}${FAIL} ${line}${RESET}"
    elif [[ "$line" =~ ERROR   ]]; then echo -e "  ${RED}${FAIL} ${line}${RESET}"
    elif [[ "$line" =~ WARNING ]]; then echo -e "  ${YELLOW}⚠ ${line}${RESET}"
    elif [[ "$line" =~ ^ERRORS|^=.*=$ ]]; then echo -e "  ${BOLD}${line}${RESET}"
    elif [[ "$line" =~ slowest ]]; then echo -e "  ${MAGENTA}${line}${RESET}"
    elif [[ "$line" =~ ^[0-9]+\.[0-9]+s ]]; then echo -e "  ${BLUE}${CLOCK} ${line}${RESET}"
    else echo -e "  ${DIM}${line}${RESET}"
    fi
  done
}

# ─────────────────────────────────────────────
#  Run
# ─────────────────────────────────────────────
print_header
echo -e "  ${BOLD}${RUN} Running pytest...${RESET}"
print_divider
echo

# Start live tail in background, store PID
live_tail "$OUTFILE" &
TAIL_PID=$!

# Run tests; capture start time
START=$(date +%s)
uv run pytest --no-cov --durations=0 > "$OUTFILE" 2>&1
EXIT_CODE=$?
END=$(date +%s)
ELAPSED=$((END - START))

# Give tail a moment to flush, then stop it
sleep 0.3
kill "$TAIL_PID" 2>/dev/null
wait "$TAIL_PID" 2>/dev/null

# ─────────────────────────────────────────────
#  Summary
# ─────────────────────────────────────────────
echo
print_divider

# Parse counts from output
PASSED=$(grep -oP '\d+(?= passed)'  "$OUTFILE" | tail -1)
FAILED=$(grep -oP '\d+(?= failed)'  "$OUTFILE" | tail -1)
ERRORS=$(grep -oP '\d+(?= error)'   "$OUTFILE" | tail -1)
SKIPPED=$(grep -oP '\d+(?= skipped)' "$OUTFILE" | tail -1)

echo -e "\n  ${BOLD}Summary${RESET}"
[[ -n "$PASSED"  ]] && echo -e "  ${GREEN}${PASS}  Passed  : ${PASSED}${RESET}"
[[ -n "$FAILED"  ]] && echo -e "  ${RED}${FAIL}  Failed  : ${FAILED}${RESET}"
[[ -n "$ERRORS"  ]] && echo -e "  ${RED}${FAIL}  Errors  : ${ERRORS}${RESET}"
[[ -n "$SKIPPED" ]] && echo -e "  ${YELLOW}⊘  Skipped : ${SKIPPED}${RESET}"
echo -e "  ${BLUE}${CLOCK}  Elapsed : ${ELAPSED}s${RESET}"

echo
if [[ $EXIT_CODE -eq 0 ]]; then
  echo -e "  ${BOLD}${GREEN}${PASS} All tests passed.${RESET}"
else
  echo -e "  ${BOLD}${RED}${FAIL} Test run failed (exit ${EXIT_CODE}).${RESET}"
fi

print_divider
echo -e "\n  ${FILE} Full output: ${BOLD}${OUTFILE}${RESET}\n"

exit $EXIT_CODE