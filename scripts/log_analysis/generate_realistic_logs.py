#!/usr/bin/env python3
"""Generate realistic Stata SMCL logs mimicking common econometric workflows."""

import argparse
import os
import random


def smcl_header():
    return """{smcl}
{txt}{sf}{ul off}{.-}
      name:  {res}Untitled{txt}
       log:  {res}/Users/tom/project/analysis.smcl{txt}
  log type:  {res}smcl{txt}
 opened on:  {res}12 May 2026, 14:32:01{txt}

"""


def cmd_block(cmd, outputs, error_rc=None):
    block = f"{{com}}. {cmd}{{txt}}\n"
    for out in outputs:
        block += f"{{txt}}{out}\n"
    if error_rc:
        block += f"{{err}}r({error_rc});{{txt}}\n"
    return block + "\n"


def gen_use_data():
    return cmd_block("use \"~/data/census.dta\", clear", [
        "(1978 Automobile Data)"
    ])


def gen_describe(n_vars=30):
    lines = [
        "Contains data from ~/data/census.dta",
        " Observations:        74                  1978 Automobile Data",
        "    Variables:        {:>3}                  12 May 2026 14:32".format(n_vars),
        "{hline 74}",
        "Variable      Storage   Display    Value",
        "    name         type    format    label      Variable label",
        "{hline 74}",
    ]
    types = ["byte", "int", "long", "float", "double", "str10", "str20", "str32"]
    for i in range(n_vars):
        vname = f"var_{i+1:02d}"
        vtype = random.choice(types)
        fmt = "%9.0g" if vtype != "str10" else "%10s"
        label = f"Variable number {i+1}"
        lines.append(f"{vname:<14} {vtype:<8} {fmt:<9}            {label}")
    lines.append("{hline 74}")
    lines.append("Sorted by:  make")
    return cmd_block("describe", lines)


def gen_regression():
    lines = [
        "      Source {c |}       SS           df       MS      Number of obs   =      74",
        "{c TLC}{hline 11}{c +}{hline 30}{c TRC}   F(3, 70)        =   46.73",
        "   Model {c |}  186321.293         3   62107.0977   Prob > F        =   0.0000",
        "Residual {c |}   93010.1414        70   1328.71631   R-squared       =   0.6669",
        "{c BLC}{hline 11}{c BT}{hline 30}{c BRC}   Root MSE        =   36.451",
        "",
        "{c TLC}{hline 13}{c TT}{hline 11}{c TT}{hline 8}{c TT}{hline 8}{c TT}{hline 9}{c TT}{hline 9}{c TRC}",
        "       price {c |}      Coef.   Std. Err.      t    P>|t|     [95% Conf. Interval]",
        "{c LT}{hline 13}{c +}{hline 11}{c +}{hline 8}{c +}{hline 8}{c +}{hline 9}{c +}{hline 9}{c RT}",
        "         mpg {c |}  -238.8943   53.07669    -4.50   0.000    -344.6568   -133.1318",
        "       rep78 {c |}   433.0016   157.5474     2.75   0.008     118.6713    747.3319",
        "     foreign {c |}   740.4621   303.8597     2.44   0.017     134.3734   1346.551",
        "       _cons {c |}   11253.06   2758.922     4.08   0.000     5750.878   16755.25",
        "{c BLC}{hline 13}{c BT}{hline 11}{c BT}{hline 8}{c BT}{hline 8}{c BT}{hline 9}{c BT}{hline 9}{c BRC}",
    ]
    return cmd_block("reg price mpg rep78 foreign", lines)


def gen_bootstrap_iter(iter_num, n_reps=1000):
    """Generate output for one bootstrap iteration (very verbose)."""
    if iter_num == 1:
        lines = [
            "(running regress on estimation sample)",
            "",
            "Bootstrap replications ({})".format(n_reps),
            "----+--- 1 ---+--- 2 ---+--- 3 ---+--- 4 ---+--- 5",
        ]
    else:
        lines = []

    # Every 50 iterations, Stata prints a dot line
    if iter_num % 50 == 0:
        dots = "." * 50
        lines.append(dots + "{:>5}".format(iter_num))

    if iter_num == n_reps:
        lines.append("")
        lines.append("Bootstrap results                               Number of obs     =         74")
        lines.append("                                                Replications      =      {:>5}".format(n_reps))
        lines.append("{hline 74}")
        lines.append("             {c |}   Observed   Bootstrap                         Normal-based")
        lines.append("             {c |}     Coef.   Std. Err.      z    P>|z|     [95% Conf. Interval]")
        lines.append("{hline 74}")
        lines.append("         mpg {c |}  -238.8943   55.12345    -4.33   0.000    -346.9342   -130.8544")
        lines.append("       rep78 {c |}   433.0016   162.3456     2.67   0.008     114.8101    751.1931")
        lines.append("     foreign {c |}   740.4621   310.1234     2.39   0.017     132.6312   1348.293")
        lines.append("       _cons {c |}   11253.06   2800.123     4.02   0.000     5764.893   16741.23")
        lines.append("{hline 74}")
    return cmd_block(f"bootstrap, reps({n_reps}): reg price mpg rep78 foreign" if iter_num == 1 else "", lines)


def gen_simulation(n_sims=5000):
    """Generate a simulation loop log (very large)."""
    blocks = []
    blocks.append(cmd_block("set seed 12345", [""]))
    blocks.append(cmd_block("set obs 1000", [""]))
    blocks.append(cmd_block("gen x = rnormal()", [""]))
    blocks.append(cmd_block("gen y = 2 + 3*x + rnormal()", [""]))
    blocks.append(cmd_block("simulate _b[_cons] _b[x] _se[x], reps({}): reg y x".format(n_sims), [
        "command: regress y x",
        "        _sim_1: _b[_cons]",
        "        _sim_2: _b[x]",
        "        _sim_3: _se[x]",
        "",
        "Simulations ({})".format(n_sims),
        "----+--- 1 ---+--- 2 ---+--- 3 ---+--- 4 ---+--- 5",
    ]))

    # Every 50 iterations a dot line
    for i in range(50, n_sims + 1, 50):
        blocks.append(cmd_block("", ["." * 50 + "{:>6}".format(i)]))

    blocks.append(cmd_block("", [
        "",
        "      Variable {c |}        Obs        Mean    Std. dev.       Min        Max",
        "{c TLC}{hline 12}{c +}{hline 55}{c TRC}",
        f"     _sim_1 {{c |}}   {n_sims:>8}  {1.998:>10.4f}  {0.063:>10.4f} {1.789:>10.4f} {2.215:>10.4f}",
        f"     _sim_2 {{c |}}   {n_sims:>8}  {2.999:>10.4f}  {0.032:>10.4f} {2.912:>10.4f} {3.089:>10.4f}",
        f"     _sim_3 {{c |}}   {n_sims:>8}  {0.031:>10.4f}  {0.001:>10.4f} {0.028:>10.4f} {0.035:>10.4f}",
        "{c BLC}{hline 12}{c BT}{hline 55}{c BRC}",
    ]))
    return "".join(blocks)


def gen_data_prep(n_vars=50, n_obs=10000):
    """Generate a long data preparation log."""
    blocks = []
    blocks.append(cmd_block("import delimited \"~/raw_data/survey.csv\", clear", [
        "(10 vars, 10,000 obs)",
    ]))

    for i in range(1, n_vars + 1):
        blocks.append(cmd_block("gen income_{} = runiform() * 50000".format(i), [""]))

    blocks.append(cmd_block("egen total_income = rowtotal(income_1-income_{})".format(n_vars), [""]))
    blocks.append(cmd_block("summarize total_income, detail", [
        "                             total_income",
        "{hline 52}",
        "      Percentile      Value            Percentile      Value",
        "             1%     2341.23                    50%    24512.34",
        "             5%     5678.90                    75%    31234.56",
        "            10%     8901.23                    90%    38901.23",
        "            25%    12345.67                    95%    42345.67",
        "{hline 52}",
    ]))
    return "".join(blocks)


def gen_error_at_end(rc=198):
    """Generate a log where the error is at the very end."""
    blocks = []
    for i in range(50):
        blocks.append(cmd_block("gen x{} = rnormal()".format(i), [""]))
    blocks.append(cmd_block("regress y x1-x50 z_nonexistent", [
        "{err}variable z_nonexistent not found",
        "{err}r(" + str(rc) + ");",
    ]))
    return "".join(blocks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["bootstrap", "simulation", "dataprep", "error_end", "mixed"], default="mixed")
    parser.add_argument("--scale", type=int, default=1, help="Multiplier for log size")
    parser.add_argument("--output", default="/tmp/realistic_stata.smcl")
    args = parser.parse_args()

    out = smcl_header()

    if args.scenario == "bootstrap":
        n_reps = 1000 * args.scale
        out += cmd_block("sysuse auto, clear", ["(1978 Automobile Data)"])
        out += gen_bootstrap_iter(1, n_reps)
        for i in range(2, n_reps + 1):
            out += gen_bootstrap_iter(i, n_reps)

    elif args.scenario == "simulation":
        out += gen_simulation(5000 * args.scale)

    elif args.scenario == "dataprep":
        out += gen_data_prep(50 * args.scale, 10000)

    elif args.scenario == "error_end":
        out += gen_error_at_end()

    elif args.scenario == "mixed":
        out += gen_use_data()
        out += gen_describe(30)
        for _ in range(10 * args.scale):
            out += gen_regression()
            out += cmd_block("predict yhat", ["(option xb assumed; fitted values)"])
            out += cmd_block("summarize yhat", [
                "    Variable {c |}        Obs        Mean    Std. dev.       Min        Max",
                "{c TLC}{hline 12}{c +}{hline 55}{c TRC}",
                "        yhat {c |}        74    6165.257    2949.496   1724.123   13459.23",
                "{c BLC}{hline 12}{c BT}{hline 55}{c BRC}",
            ])
        out += gen_error_at_end()

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(out)

    size_kb = len(out.encode("utf-8")) / 1024
    print(f"Wrote {args.output}: {size_kb:.1f} KB, {out.count(chr(10))} lines")


if __name__ == "__main__":
    main()
