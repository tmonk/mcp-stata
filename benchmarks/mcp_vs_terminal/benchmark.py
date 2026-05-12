#!/usr/bin/env python3
"""
benchmark.py – Legacy entry point; use run_baseline.py or run_benchmark.py instead.

For a one-time terminal baseline:
    python run_baseline.py

For repeating MCP benchmarks:
    python run_benchmark.py --local   # local dev version
    python run_benchmark.py            # installed release

For baseline management:
    python baseline.py                 # show current baseline
    python baseline.py --set <id>     # set specific run as baseline
    python baseline.py --latest       # set latest terminal as baseline

For the dashboard:
    python dashboard.py               # http://localhost:5050
"""

import sys
import os

print("This script is deprecated. Use one of:")
print("  python run_baseline.py          # run terminal baseline")
print("  python run_benchmark.py --local  # run MCP benchmark (local)")
print("  python run_benchmark.py          # run MCP benchmark (release)")
print("  python baseline.py              # manage baseline")
print("  python dashboard.py             # launch dashboard")
sys.exit(1)