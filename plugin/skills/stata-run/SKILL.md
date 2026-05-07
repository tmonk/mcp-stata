---
name: stata-run
description: Run arbitrary Stata code or a .do file and display the result.
---

The argument is the Stata code or absolute path to a `.do` file to execute.

1. If the argument ends in `.do` or `.ado`, call:
   ```
   stata_run(code=<argument>, is_file=True, echo=True, as_json=True)
   ```
   Otherwise call:
   ```
   stata_run(code=<argument>, echo=True, as_json=True)
   ```

2. If `success` is `true`, display the `stdout` output. Note the output is truncated to 5,000 chars; if the response includes a `log_path`, offer to tail the full log with `/stata-log <log_path>`.

3. If `success` is `false`, display the error message and `rc` code. Suggest using `/stata-lint <path>` for syntax issues or `/stata-help <command>` for documentation.

4. If the command produces graphs, note that `/stata-graph` can export them.
