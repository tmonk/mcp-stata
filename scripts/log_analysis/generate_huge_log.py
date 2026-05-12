#!/usr/bin/env python3
"""Generate a very large SMCL log to test extreme token sizes."""

import sys

def main():
    target_bytes = 5 * 1024 * 1024  # 5 MB
    lines = []
    
    header = (
        "{smcl}\n{txt}{sf}{ul off}{.-}\n"
        "      name:  {res}Untitled{txt}\n"
        "       log:  {res}/tmp/huge.smcl{txt}\n"
        "  log type:  {res}smcl{txt}\n"
        " opened on:  {res}12 May 2026, 14:32:01{txt}\n\n"
    )
    lines.append(header)
    
    i = 0
    current = len(header.encode("utf-8"))
    
    while current < target_bytes:
        block = (
            "{com}. gen var_" + str(i) + " = rnormal(){txt}\n"
            "{txt}(variable created){txt}\n\n"
        )
        lines.append(block)
        current += len(block.encode("utf-8"))
        i += 1
        
        if i % 500 == 0:
            sum_block = (
                "{com}. summarize var_*{txt}\n"
                "{txt}    Variable {c |}        Obs        Mean    Std. dev.       Min        Max\n"
                "{c TLC}{hline 12}{c +}{hline 55}{c TRC}\n"
                "{txt}    var_0 {c |}     1000    50.00     5.00     0.00     100.00\n"
                "{c BLC}{hline 12}{c BT}{hline 55}{c BRC}\n\n"
            )
            lines.append(sum_block)
            current += len(sum_block.encode("utf-8"))
    
    # Error at the very end
    lines.append(
        "{com}. regress y z_nonexistent{txt}\n"
        "{err}variable z_nonexistent not found{txt}\n"
        "{err}r(111);{txt}\n"
    )
    
    text = "".join(lines)
    path = "/tmp/stata_huge_5mb.smcl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    
    print(f"Wrote {path}: {len(text.encode('utf-8'))/1024:.0f} KB, {text.count(chr(10))} lines")

if __name__ == "__main__":
    main()
