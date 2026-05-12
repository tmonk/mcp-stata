#!/usr/bin/env python3
"""Generate synthetic Stata SMCL logs of varying sizes for token analysis."""

import argparse
import os
import random
import string


def generate_smcl_header():
    return """{smcl}
{txt}{sf}{ul off}{.-}
      name:  {res}Untitled{txt}
       log:  {res}/tmp/stata_session.smcl{txt}
  log type:  {res}smcl{txt}
 opened on:  {res}12 May 2026, 14:32:01{txt}

"""


def generate_command_block(cmd, output_lines, has_error=False, error_rc=0):
    """Generate a realistic SMCL block for one Stata command."""
    lines = [f"{{com}}. {cmd}{{txt}"]
    for out in output_lines:
        lines.append(f"{{txt}}{out}")
    if has_error:
        lines.append(f"{{err}}{error_message(error_rc)}{{txt}}")
        lines.append(f"{{err}}r({error_rc});{{txt}}")
    lines.append("")
    return "\n".join(lines)


def error_message(rc):
    errors = {
        111: "no variables defined",
        198: "invalid syntax",
        199: "unrecognized command",
        2001: "matrix has missing values",
        301: "last estimates not found",
        3221: "something that should be true of your data is not",
        601: "file not found",
        602: "file already exists",
    }
    return errors.get(rc, "unknown error")


def generate_regression_output(n_obs=74, n_vars=3, r2=0.6512):
    lines = []
    lines.append("      Source{c |}       SS           df       MS      Number of obs   =      {:>5}".format(n_obs))
    lines.append("{c TLC}{hline 11}{c +}{hline 30}{c TRC}   F({:>2},{:>3})        =   {:>8.2f}".format(n_vars-1, n_obs-n_vars, 42.31))
    lines.append("   Model {c |}  162024.742         {:>2}   81012.3710   Prob > F        =   0.0000".format(n_vars-1))
    lines.append("Residual {c |}   86767.3029        {:>3}   1239.53290   R-squared       =   {:.4f}".format(n_obs-n_vars, r2))
    lines.append("{c BLC}{hline 11}{c BT}{hline 30}{c BRC}   Root MSE        =   35.206")
    lines.append("")
    lines.append("{c TLC}{hline 13}{c TT}{hline 11}{c TT}{hline 8}{c TT}{hline 8}{c TT}{hline 9}{c TT}{hline 9}{c TRC}")
    lines.append("       price {c |}      Coef.   Std. Err.      t    P>|t|     [95% Con")
    lines.append("{c LT}{hline 13}{c +}{hline 11}{c +}{hline 8}{c +}{hline 8}{c +}{hline 9}{c +}{hline 9}{c RT}")
    lines.append("         mpg {c |}  -238.8943   53.07669    -4.50   0.000    -344.657")
    lines.append("       rep78 {c |}   433.0016   157.5474     2.75   0.008     118.671")
    lines.append("       _cons {c |}   11253.06   2758.922     4.08   0.000     5750.88")
    lines.append("{c BLC}{hline 13}{c BT}{hline 11}{c BT}{hline 8}{c BT}{hline 8}{c BT}{hline 9}{c BT}{hline 9}{c BRC}")
    return lines


def generate_tabulate_output(rows=10):
    lines = []
    lines.append("     Repair {c |}")
    lines.append("Record 1978 {c |}      Freq.     Percent        Cum.")
    lines.append("{c TLC}{hline 12}{c +}{hline 33}{c TRC}")
    cum = 0.0
    for i in range(rows):
        freq = random.randint(2, 30)
        pct = freq / 74.0 * 100
        cum += pct
        lines.append(f"         {i+1} {c |}     {freq:>6}      {pct:>6.2f}      {cum:>6.2f}")
    lines.append("{c BLC}{hline 12}{c BT}{hline 33}{c BRC}")
    return lines


def generate_summarize_output(vars_count=5):
    lines = []
    lines.append("    Variable {c |}        Obs        Mean    Std. dev.       Min        Max")
    lines.append("{c TLC}{hline 12}{c +}{hline 55}{c TRC}")
    for i in range(vars_count):
        varname = f"var{i+1}"
        obs = 74
        mean = random.uniform(10, 1000)
        sd = mean * 0.3
        minv = mean - sd * 2
        maxv = mean + sd * 2
        lines.append(f"{varname:>12} {c |}   {obs:>8}  {mean:>10.2f}  {sd:>10.2f} {minv:>10.2f} {maxv:>10.2f}")
    lines.append("{c BLC}{hline 12}{c BT}{hline 55}{c BRC}")
    return lines


def generate_log(total_commands=100, error_rate=0.05, error_rc=198):
    """Generate a synthetic SMCL log."""
    blocks = [generate_smcl_header()]
    for i in range(total_commands):
        cmd_type = random.choice(["reg", "sum", "tab", "gen", "drop", "use", "save"])
        has_error = random.random() < error_rate and i > 5  # Don't error too early
        if cmd_type == "reg":
            out = generate_regression_output()
        elif cmd_type == "sum":
            out = generate_summarize_output()
        elif cmd_type == "tab":
            out = generate_tabulate_output()
        else:
            out = [f"(note: {cmd_type} command executed successfully)"]
        cmd = f"{cmd_type} var{i % 10}"
        blocks.append(generate_command_block(cmd, out, has_error=has_error, error_rc=error_rc if has_error else 0))
    return "\n".join(blocks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commands", type=int, default=100)
    parser.add_argument("--error-rate", type=float, default=0.05)
    parser.add_argument("--output", default="/tmp/synthetic_smcl.smcl")
    args = parser.parse_args()

    log = generate_log(args.commands, args.error_rate)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(log)

    size_kb = len(log.encode("utf-8")) / 1024
    lines = log.count("\n")
    print(f"Wrote {args.output}: {size_kb:.1f} KB, {lines} lines, {args.commands} commands")


if __name__ == "__main__":
    main()
