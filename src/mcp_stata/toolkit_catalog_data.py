"""Generated toolkit catalog data. Do not edit by hand."""

SKILLS = [
  {
    "id": "stata",
    "name": "stata",
    "description": "Show mcp-stata identity, connected tools, and status. Entry point for mcp-stata, an agentic toolkit for Stata.",
    "version": "2.5.1",
    "allowed_tools": [
      "mcp__mcp-stata__stata_manage_session"
    ],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Show mcp-stata identity, connected tools, and status. Entry point for mcp-stata, an agentic toolkit for Stata.",
    "invocation_type": "slash-command",
    "references": [],
    "scripts": [],
    "body": "Call `stata_manage_session(action=\"detect\")` to verify the Stata connection, then respond with:\n\n```\n                                    __        __       \n   ____ ___  _________        _____/ /_____ _/ /_____ _\n  / __ `__ \\/ ___/ __ \\______/ ___/ __/ __ `/ __/ __ `/\n / / / / / / /__/ /_/ /_____(__  ) /_/ /_/ / /_/ /_/ / \n/_/ /_/ /_/\\___/ .___/     /____/\\__/\\__,_/\\__/\\__,_/  \n              /_/                                        mcp-stata\n\nmcp-stata is connected. Stata {version} ({flavor}) detected.\n\nMCP Tools:\n  stata_run              \u2014 execute do-file code & ad-hoc commands\n  stata_load_data        \u2014 load datasets (sysuse / webuse / path)\n  stata_inspect_data     \u2014 describe, codebook, summary, list, get rows\n  stata_manage_graphs    \u2014 list, export, or export_all graphs\n  stata_get_help         \u2014 Stata command documentation\n  stata_get_results      \u2014 fetch r() / e() / s() stored results\n  stata_read_log         \u2014 tail or search log output\n  stata_manage_session   \u2014 create/stop sessions, history diff, UI channel\n  stata_task_status      \u2014 poll background task progress\n  stata_control          \u2014 break or cancel running work\n\nSlash Commands:\n  /stata-run <code>      \u2014 run arbitrary Stata code\n  /stata-inspect [var]   \u2014 describe/summarize current dataset\n  /stata-results         \u2014 fetch stored r()/e()/s() results\n  /stata-graph [name]    \u2014 export graph(s)\n  /stata-lint <path>     \u2014 lint a .do or .ado file\n  /stata-log [path]      \u2014 tail log output\n  /stata-help <topic>    \u2014 look up Stata documentation\n\nResources (MCP):\n  stata://data/summary        stata://data/metadata\n  stata://graphs/list         stata://variables/list\n  stata://results/stored\n```\n\nIf `stata_manage_session(action=\"detect\")` fails, report the error and suggest the user set `STATA_PATH` to the Stata executable path.\n",
    "path": "plugin/skills/stata/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata/agents/openai.yaml",
    "content": "---\nname: stata\ndescription: Show mcp-stata identity, connected tools, and status. Entry point for mcp-stata, an agentic toolkit for Stata.\n---\n\nCall `stata_manage_session(action=\"detect\")` to verify the Stata connection, then respond with:\n\n```\n                                    __        __       \n   ____ ___  _________        _____/ /_____ _/ /_____ _\n  / __ `__ \\/ ___/ __ \\______/ ___/ __/ __ `/ __/ __ `/\n / / / / / / /__/ /_/ /_____(__  ) /_/ /_/ / /_/ /_/ / \n/_/ /_/ /_/\\___/ .___/     /____/\\__/\\__,_/\\__/\\__,_/  \n              /_/                                        mcp-stata\n\nmcp-stata is connected. Stata {version} ({flavor}) detected.\n\nMCP Tools:\n  stata_run              \u2014 execute do-file code & ad-hoc commands\n  stata_load_data        \u2014 load datasets (sysuse / webuse / path)\n  stata_inspect_data     \u2014 describe, codebook, summary, list, get rows\n  stata_manage_graphs    \u2014 list, export, or export_all graphs\n  stata_get_help         \u2014 Stata command documentation\n  stata_get_results      \u2014 fetch r() / e() / s() stored results\n  stata_read_log         \u2014 tail or search log output\n  stata_manage_session   \u2014 create/stop sessions, history diff, UI channel\n  stata_task_status      \u2014 poll background task progress\n  stata_control          \u2014 break or cancel running work\n\nSlash Commands:\n  /stata-run <code>      \u2014 run arbitrary Stata code\n  /stata-inspect [var]   \u2014 describe/summarize current dataset\n  /stata-results         \u2014 fetch stored r()/e()/s() results\n  /stata-graph [name]    \u2014 export graph(s)\n  /stata-lint <path>     \u2014 lint a .do or .ado file\n  /stata-log [path]      \u2014 tail log output\n  /stata-help <topic>    \u2014 look up Stata documentation\n\nResources (MCP):\n  stata://data/summary        stata://data/metadata\n  stata://graphs/list         stata://variables/list\n  stata://results/stored\n```\n\nIf `stata_manage_session(action=\"detect\")` fails, report the error and suggest the user set `STATA_PATH` to the Stata executable path.\n"
  },
  {
    "id": "stata-causal-inference",
    "name": "stata-causal-inference",
    "description": "Design, run, and critique causal inference workflows in Stata. Use when the user is working on identification, treatment effects, DiD, IV, event studies, RD, or assumption-sensitive empirical claims.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Design, run, and critique causal inference workflows in Stata. Use when the user is working on identification, treatment effects, DiD, IV, event studies, RD, or assumption-sensitive empirical claims.",
    "invocation_type": "context-skill",
    "references": [
      "references/designs.md"
    ],
    "scripts": [],
    "body": "# Causal Inference\n\nUse this skill when the question is causal, not merely predictive.\n\n1. Clarify the identification strategy.\n2. Check the right diagnostics and assumptions for the design.\n3. Separate point estimates from identification credibility.\n\nRead `references/designs.md` for design-specific guidance.\n",
    "path": "plugin/skills/stata-causal-inference/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-causal-inference/agents/openai.yaml",
    "content": "---\nname: stata-causal-inference\ndescription: Design, run, and critique causal inference workflows in Stata. Use when the user is working on identification, treatment effects, DiD, IV, event studies, RD, or assumption-sensitive empirical claims.\n---\n\n# Causal Inference\n\nUse this skill when the question is causal, not merely predictive.\n\n1. Clarify the identification strategy.\n2. Check the right diagnostics and assumptions for the design.\n3. Separate point estimates from identification credibility.\n\nRead `references/designs.md` for design-specific guidance.\n"
  },
  {
    "id": "stata-data-audit",
    "name": "stata-data-audit",
    "description": "Audit datasets for structure, missingness, labeling, suspicious values, duplicate identifiers, and documentation readiness. Use when a researcher asks for data QA, codebook review, sanity checks, or pre-analysis cleanup guidance.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Audit datasets for structure, missingness, labeling, suspicious values, duplicate identifiers, and documentation readiness. Use when a researcher asks for data QA, codebook review, sanity checks, or pre-analysis cleanup guidance.",
    "invocation_type": "context-skill",
    "references": [
      "references/checklist.md"
    ],
    "scripts": [],
    "body": "# Data Audit\n\nRun a compact but explicit audit of the active dataset.\n\n1. Start with `stata_inspect_data(action=\"describe\")` and `stata_inspect_data(action=\"summary\")`.\n2. Use targeted `codebook`, `search`, and `stata_run` checks for key variables or suspicious patterns.\n3. Report concrete issues, not generic reassurance.\n\nRead `references/checklist.md` for the full audit checklist and recommended output format.\n",
    "path": "plugin/skills/stata-data-audit/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-data-audit/agents/openai.yaml",
    "content": "---\nname: stata-data-audit\ndescription: Audit datasets for structure, missingness, labeling, suspicious values, duplicate identifiers, and documentation readiness. Use when a researcher asks for data QA, codebook review, sanity checks, or pre-analysis cleanup guidance.\n---\n\n# Data Audit\n\nRun a compact but explicit audit of the active dataset.\n\n1. Start with `stata_inspect_data(action=\"describe\")` and `stata_inspect_data(action=\"summary\")`.\n2. Use targeted `codebook`, `search`, and `stata_run` checks for key variables or suspicious patterns.\n3. Report concrete issues, not generic reassurance.\n\nRead `references/checklist.md` for the full audit checklist and recommended output format.\n"
  },
  {
    "id": "stata-data-provenance",
    "name": "stata-data-provenance",
    "description": "Track dataset lineage, transformation steps, merge logic, and reproducibility risks in Stata workflows. Use when the user needs to explain where data came from, how it changed, or why a pipeline can be trusted.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Track dataset lineage, transformation steps, merge logic, and reproducibility risks in Stata workflows. Use when the user needs to explain where data came from, how it changed, or why a pipeline can be trusted.",
    "invocation_type": "context-skill",
    "references": [
      "references/lineage.md"
    ],
    "scripts": [],
    "body": "# Data Provenance\n\nUse this skill when lineage and reproducibility matter.\n\n1. Map the sequence of source files and transformations.\n2. Flag untracked merges, overwrites, and silent sample restrictions.\n3. Produce a concise provenance narrative a coauthor can audit.\n\nRead `references/lineage.md` for the provenance checklist.\n",
    "path": "plugin/skills/stata-data-provenance/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-data-provenance/agents/openai.yaml",
    "content": "---\nname: stata-data-provenance\ndescription: Track dataset lineage, transformation steps, merge logic, and reproducibility risks in Stata workflows. Use when the user needs to explain where data came from, how it changed, or why a pipeline can be trusted.\n---\n\n# Data Provenance\n\nUse this skill when lineage and reproducibility matter.\n\n1. Map the sequence of source files and transformations.\n2. Flag untracked merges, overwrites, and silent sample restrictions.\n3. Produce a concise provenance narrative a coauthor can audit.\n\nRead `references/lineage.md` for the provenance checklist.\n"
  },
  {
    "id": "stata-environment-diagnose",
    "name": "stata-environment-diagnose",
    "description": "Diagnose local Stata, MCP, package, startup, graph-export, and permissions issues. Use when setup is failing, Stata is not discovered, packages are missing, logs are truncated, or a managed machine behaves differently from a normal workstation.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Diagnose local Stata, MCP, package, startup, graph-export, and permissions issues. Use when setup is failing, Stata is not discovered, packages are missing, logs are truncated, or a managed machine behaves differently from a normal workstation.",
    "invocation_type": "context-skill",
    "references": [
      "references/troubleshooting.md"
    ],
    "scripts": [
      "scripts/report_environment.py"
    ],
    "body": "# Environment Diagnose\n\nUse this skill for setup and platform troubleshooting.\n\n1. Verify detection with `stata_manage_session(action=\"detect\")`.\n2. Reproduce the smallest failing command.\n3. Use logs, package checks, and environment reporting before suggesting a fix.\n4. Separate root cause, evidence, remediation, and verification.\n\nRead `references/troubleshooting.md` for the diagnosis flow and use `scripts/report_environment.py` for a deterministic environment summary.\n",
    "path": "plugin/skills/stata-environment-diagnose/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-environment-diagnose/agents/openai.yaml",
    "content": "---\nname: stata-environment-diagnose\ndescription: Diagnose local Stata, MCP, package, startup, graph-export, and permissions issues. Use when setup is failing, Stata is not discovered, packages are missing, logs are truncated, or a managed machine behaves differently from a normal workstation.\n---\n\n# Environment Diagnose\n\nUse this skill for setup and platform troubleshooting.\n\n1. Verify detection with `stata_manage_session(action=\"detect\")`.\n2. Reproduce the smallest failing command.\n3. Use logs, package checks, and environment reporting before suggesting a fix.\n4. Separate root cause, evidence, remediation, and verification.\n\nRead `references/troubleshooting.md` for the diagnosis flow and use `scripts/report_environment.py` for a deterministic environment summary.\n"
  },
  {
    "id": "stata-graph",
    "name": "stata-graph",
    "description": "List, export, and review Stata graphs from the current session.",
    "version": "2.5.1",
    "allowed_tools": [
      "mcp__mcp-stata__stata_manage_graphs"
    ],
    "argument_hint": "[graph_name]",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "List, export, and review Stata graphs from the current session.",
    "invocation_type": "slash-command",
    "references": [],
    "scripts": [],
    "body": "1. Call `stata_manage_graphs(action=\"list\")` to see all graphs in memory, with the active graph marked.\n\n2. If an argument (graph name) was provided:\n   - Call `stata_manage_graphs(action=\"export\", graph_name=<argument>, format=\"png\")` and display the exported file path.\n\n3. If no argument was provided and graphs exist:\n   - Call `stata_manage_graphs(action=\"export_all\", format=\"png\")` to export all graphs.\n   - Display all exported file paths for the user to inspect.\n\n4. If no graphs are in memory, tell the user to create a graph first (e.g., `/stata-run histogram price` or `/stata-run scatter price mpg`).\n\nAfter export, review the graph(s): check titles, axis labels, legends, and whether the plot matches expectations. Report any issues.\n",
    "path": "plugin/skills/stata-graph/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-graph/agents/openai.yaml",
    "content": "---\nname: stata-graph\ndescription: List, export, and review Stata graphs from the current session.\n---\n\n1. Call `stata_manage_graphs(action=\"list\")` to see all graphs in memory, with the active graph marked.\n\n2. If an argument (graph name) was provided:\n   - Call `stata_manage_graphs(action=\"export\", graph_name=<argument>, format=\"png\")` and display the exported file path.\n\n3. If no argument was provided and graphs exist:\n   - Call `stata_manage_graphs(action=\"export_all\", format=\"png\")` to export all graphs.\n   - Display all exported file paths for the user to inspect.\n\n4. If no graphs are in memory, tell the user to create a graph first (e.g., `/stata-run histogram price` or `/stata-run scatter price mpg`).\n\nAfter export, review the graph(s): check titles, axis labels, legends, and whether the plot matches expectations. Report any issues.\n"
  },
  {
    "id": "stata-help",
    "name": "stata-help",
    "description": "Look up Stata command documentation and display formatted help text.",
    "version": "2.5.1",
    "allowed_tools": [
      "mcp__mcp-stata__stata_get_help"
    ],
    "argument_hint": "<topic>",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Look up Stata command documentation and display formatted help text.",
    "invocation_type": "slash-command",
    "references": [],
    "scripts": [],
    "body": "The argument is the Stata command or help topic (e.g., \"regress\", \"graph\", \"if\", \"egen\", \"frames\").\n\nCall `stata_get_help(topic=<argument>, plain_text=False, merge_paragraphs=True)`.\n\nDisplay the help text. The response is formatted as Markdown. Present:\n1. Syntax section first\n2. Description and options\n3. Examples if present\n\nIf no argument is provided, ask the user which Stata command they want help with.\n\nIf the help topic is not found (error in response), suggest:\n- Checking spelling (e.g., \"summarize\" not \"summarise\")\n- Using `help contents` as the topic for the help index\n- Searching for related commands with `/stata-inspect` using `action=\"search\"`\n",
    "path": "plugin/skills/stata-help/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-help/agents/openai.yaml",
    "content": "---\nname: stata-help\ndescription: Look up Stata command documentation and display formatted help text.\n---\n\nThe argument is the Stata command or help topic (e.g., \"regress\", \"graph\", \"if\", \"egen\", \"frames\").\n\nCall `stata_get_help(topic=<argument>, plain_text=False, merge_paragraphs=True)`.\n\nDisplay the help text. The response is formatted as Markdown. Present:\n1. Syntax section first\n2. Description and options\n3. Examples if present\n\nIf no argument is provided, ask the user which Stata command they want help with.\n\nIf the help topic is not found (error in response), suggest:\n- Checking spelling (e.g., \"summarize\" not \"summarise\")\n- Using `help contents` as the topic for the help index\n- Searching for related commands with `/stata-inspect` using `action=\"search\"`\n"
  },
  {
    "id": "stata-inspect",
    "name": "stata-inspect",
    "description": "Describe and summarize the current dataset in memory. Optionally inspect a specific variable with codebook.",
    "version": "2.5.1",
    "allowed_tools": [
      "mcp__mcp-stata__stata_inspect_data"
    ],
    "argument_hint": "[variable]",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Describe and summarize the current dataset in memory. Optionally inspect a specific variable with codebook.",
    "invocation_type": "slash-command",
    "references": [],
    "scripts": [],
    "body": "If an argument (variable name) is provided:\n1. Call `stata_inspect_data(action=\"codebook\", query=<variable>)` and display the codebook output.\n\nIf no argument is provided:\n1. Call `stata_inspect_data(action=\"describe\")` \u2014 display the dataset structure (obs, vars, types, labels).\n2. Call `stata_inspect_data(action=\"summary\")` \u2014 display descriptive statistics (N, mean, sd, min, max).\n3. Present both results in a clear, readable format.\n\nIf either call returns an error indicating no data in memory, tell the user to load data first (e.g., `/stata-run sysuse auto, clear` or `stata_load_data(\"auto\")`).\n",
    "path": "plugin/skills/stata-inspect/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-inspect/agents/openai.yaml",
    "content": "---\nname: stata-inspect\ndescription: Describe and summarize the current dataset in memory. Optionally inspect a specific variable with codebook.\n---\n\nIf an argument (variable name) is provided:\n1. Call `stata_inspect_data(action=\"codebook\", query=<variable>)` and display the codebook output.\n\nIf no argument is provided:\n1. Call `stata_inspect_data(action=\"describe\")` \u2014 display the dataset structure (obs, vars, types, labels).\n2. Call `stata_inspect_data(action=\"summary\")` \u2014 display descriptive statistics (N, mean, sd, min, max).\n3. Present both results in a clear, readable format.\n\nIf either call returns an error indicating no data in memory, tell the user to load data first (e.g., `/stata-run sysuse auto, clear` or `stata_load_data(\"auto\")`).\n"
  },
  {
    "id": "stata-lint",
    "name": "stata-lint",
    "description": "Run static analysis on a Stata .do or .ado file and report style and best-practice issues.",
    "version": "2.5.1",
    "allowed_tools": [
      "mcp__mcp-stata__stata_inspect_data"
    ],
    "argument_hint": "<path>",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Run static analysis on a Stata .do or .ado file and report style and best-practice issues.",
    "invocation_type": "slash-command",
    "references": [],
    "scripts": [],
    "body": "The argument is the absolute path to a `.do` or `.ado` file.\n\n1. Call `stata_inspect_data(action=\"lint\", path=<argument>)`.\n\n2. Display the lint results, grouping issues by severity or type:\n   - Line number and issue description for each finding\n   - Common issues: use of `cd`, `preserve`/`restore`, `#delimit`, hardcoded paths, long lines, missing `version` statement\n\n3. For each category of issue found, briefly explain the modern alternative (refer to the **stata-modernize** skill for details).\n\n4. If the file is clean, confirm: \"No issues found in `<filename>`.\"\n\n5. If the path argument is missing, tell the user to provide an absolute path to a `.do` or `.ado` file.\n",
    "path": "plugin/skills/stata-lint/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-lint/agents/openai.yaml",
    "content": "---\nname: stata-lint\ndescription: Run static analysis on a Stata .do or .ado file and report style and best-practice issues.\n---\n\nThe argument is the absolute path to a `.do` or `.ado` file.\n\n1. Call `stata_inspect_data(action=\"lint\", path=<argument>)`.\n\n2. Display the lint results, grouping issues by severity or type:\n   - Line number and issue description for each finding\n   - Common issues: use of `cd`, `preserve`/`restore`, `#delimit`, hardcoded paths, long lines, missing `version` statement\n\n3. For each category of issue found, briefly explain the modern alternative (refer to the **stata-modernize** skill for details).\n\n4. If the file is clean, confirm: \"No issues found in `<filename>`.\"\n\n5. If the path argument is missing, tell the user to provide an absolute path to a `.do` or `.ado` file.\n"
  },
  {
    "id": "stata-log",
    "name": "stata-log",
    "description": "Tail, read, or search a Stata log file from a previous command or background task.",
    "version": "2.5.1",
    "allowed_tools": [
      "mcp__mcp-stata__stata_read_log"
    ],
    "argument_hint": "<path or task_id> [search_term]",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Tail, read, or search a Stata log file from a previous command or background task.",
    "invocation_type": "slash-command",
    "references": [],
    "scripts": [],
    "body": "Parse the argument:\n- First token: log file path or background task_id\n- Second token (optional): search term\n\n**If a search term is provided**, call:\n```\nstata_read_log(path=<first_token>, query=<second_token>, before=2, after=2, regex=False)\n```\nDisplay matching lines with context.\n\n**If no search term**, call:\n```\nstata_read_log(path=<first_token>, tail_lines=50)\n```\nDisplay the last 50 lines of the log.\n\n**If the argument looks like a task_id** (not a file path), call:\n```\nstata_read_log(task_id=<argument>, tail_lines=50)\n```\n\nIf no argument is provided, tell the user to supply a log file path or task_id. These are returned by `stata_run` in the `log_path` field of the JSON response.\n\nIf the log is large and truncated, note the `offset` for reading more (the response includes the current byte offset).\n",
    "path": "plugin/skills/stata-log/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-log/agents/openai.yaml",
    "content": "---\nname: stata-log\ndescription: Tail, read, or search a Stata log file from a previous command or background task.\n---\n\nParse the argument:\n- First token: log file path or background task_id\n- Second token (optional): search term\n\n**If a search term is provided**, call:\n```\nstata_read_log(path=<first_token>, query=<second_token>, before=2, after=2, regex=False)\n```\nDisplay matching lines with context.\n\n**If no search term**, call:\n```\nstata_read_log(path=<first_token>, tail_lines=50)\n```\nDisplay the last 50 lines of the log.\n\n**If the argument looks like a task_id** (not a file path), call:\n```\nstata_read_log(task_id=<argument>, tail_lines=50)\n```\n\nIf no argument is provided, tell the user to supply a log file path or task_id. These are returned by `stata_run` in the `log_path` field of the JSON response.\n\nIf the log is large and truncated, note the `offset` for reading more (the response includes the current byte offset).\n"
  },
  {
    "id": "stata-modernize",
    "name": "stata-modernize",
    "description": "Improve, modernize, and optimize existing Stata code for performance, portability, and maintainability. Use when legacy patterns such as preserve/restore, cd, #delimit, slow aggregation, or weak fixed-effects workflows appear in code under review.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Improve, modernize, and optimize existing Stata code for performance, portability, and maintainability. Use when legacy patterns such as preserve/restore, cd, #delimit, slow aggregation, or weak fixed-effects workflows appear in code under review.",
    "invocation_type": "context-skill",
    "references": [
      "references/patterns.md"
    ],
    "scripts": [],
    "body": "# Modernize Stata\n\nUse this skill when a user wants stronger Stata code, not just working Stata code.\n\n1. Identify the current anti-patterns.\n2. Recommend or implement modern replacements with clear rationale.\n3. Favor frames, `reghdfe`, `gtools`, portable paths, and explicit state handling.\n\nRead `references/patterns.md` for common replacements and examples.\n",
    "path": "plugin/skills/stata-modernize/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-modernize/agents/openai.yaml",
    "content": "---\nname: stata-modernize\ndescription: Improve, modernize, and optimize existing Stata code for performance, portability, and maintainability. Use when legacy patterns such as preserve/restore, cd, #delimit, slow aggregation, or weak fixed-effects workflows appear in code under review.\n---\n\n# Modernize Stata\n\nUse this skill when a user wants stronger Stata code, not just working Stata code.\n\n1. Identify the current anti-patterns.\n2. Recommend or implement modern replacements with clear rationale.\n3. Favor frames, `reghdfe`, `gtools`, portable paths, and explicit state handling.\n\nRead `references/patterns.md` for common replacements and examples.\n"
  },
  {
    "id": "stata-power-analysis",
    "name": "stata-power-analysis",
    "description": "Plan and critique power, MDE, and sample-size calculations for Stata-based research workflows. Use when the user is designing a study, checking detectability, or defending precision claims.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Plan and critique power, MDE, and sample-size calculations for Stata-based research workflows. Use when the user is designing a study, checking detectability, or defending precision claims.",
    "invocation_type": "context-skill",
    "references": [
      "references/power-checklist.md"
    ],
    "scripts": [],
    "body": "# Power Analysis\n\nUse this skill when precision and detectability are the focus.\n\n1. Clarify the estimand and target effect size.\n2. State the assumptions behind the power calculation.\n3. Distinguish formal power analysis from ex post rationalization.\n\nRead `references/power-checklist.md` for the reporting checklist.\n",
    "path": "plugin/skills/stata-power-analysis/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-power-analysis/agents/openai.yaml",
    "content": "---\nname: stata-power-analysis\ndescription: Plan and critique power, MDE, and sample-size calculations for Stata-based research workflows. Use when the user is designing a study, checking detectability, or defending precision claims.\n---\n\n# Power Analysis\n\nUse this skill when precision and detectability are the focus.\n\n1. Clarify the estimand and target effect size.\n2. State the assumptions behind the power calculation.\n3. Distinguish formal power analysis from ex post rationalization.\n\nRead `references/power-checklist.md` for the reporting checklist.\n"
  },
  {
    "id": "stata-publication-qa",
    "name": "stata-publication-qa",
    "description": "Review regression outputs, tables, and graphs for publication readiness. Use when the user asks whether a result is ready for a paper, appendix, seminar, referee response, or coauthor review.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Review regression outputs, tables, and graphs for publication readiness. Use when the user asks whether a result is ready for a paper, appendix, seminar, referee response, or coauthor review.",
    "invocation_type": "context-skill",
    "references": [
      "references/checklist.md"
    ],
    "scripts": [
      "scripts/graph_qa_checklist.py"
    ],
    "body": "# Publication QA\n\nUse this skill when editorial quality matters.\n\n1. Re-run or inspect the relevant model or graph.\n2. Review statistical clarity, labeling, sample consistency, and visual presentation.\n3. Distinguish required fixes from optional polish.\n\nRead `references/checklist.md` for the review checklist and use `scripts/graph_qa_checklist.py` when generating a graph-specific QA pass.\n",
    "path": "plugin/skills/stata-publication-qa/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-publication-qa/agents/openai.yaml",
    "content": "---\nname: stata-publication-qa\ndescription: Review regression outputs, tables, and graphs for publication readiness. Use when the user asks whether a result is ready for a paper, appendix, seminar, referee response, or coauthor review.\n---\n\n# Publication QA\n\nUse this skill when editorial quality matters.\n\n1. Re-run or inspect the relevant model or graph.\n2. Review statistical clarity, labeling, sample consistency, and visual presentation.\n3. Distinguish required fixes from optional polish.\n\nRead `references/checklist.md` for the review checklist and use `scripts/graph_qa_checklist.py` when generating a graph-specific QA pass.\n"
  },
  {
    "id": "stata-referee-response",
    "name": "stata-referee-response",
    "description": "Organize and execute Stata workflows for referee responses, robustness requests, and coauthor follow-ups. Use when the user needs to answer a critique with targeted reruns, tables, figures, and a defensible audit trail.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Organize and execute Stata workflows for referee responses, robustness requests, and coauthor follow-ups. Use when the user needs to answer a critique with targeted reruns, tables, figures, and a defensible audit trail.",
    "invocation_type": "context-skill",
    "references": [
      "references/response-patterns.md"
    ],
    "scripts": [],
    "body": "# Referee Response\n\nUse this skill when the task is to answer a critique rather than merely rerun code.\n\n1. Translate the critique into a finite set of empirical checks.\n2. Keep outputs tied to the exact request.\n3. Separate confirmed findings, changed results, and unresolved issues.\n\nRead `references/response-patterns.md` for the workflow template.\n",
    "path": "plugin/skills/stata-referee-response/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-referee-response/agents/openai.yaml",
    "content": "---\nname: stata-referee-response\ndescription: Organize and execute Stata workflows for referee responses, robustness requests, and coauthor follow-ups. Use when the user needs to answer a critique with targeted reruns, tables, figures, and a defensible audit trail.\n---\n\n# Referee Response\n\nUse this skill when the task is to answer a critique rather than merely rerun code.\n\n1. Translate the critique into a finite set of empirical checks.\n2. Keep outputs tied to the exact request.\n3. Separate confirmed findings, changed results, and unresolved issues.\n\nRead `references/response-patterns.md` for the workflow template.\n"
  },
  {
    "id": "stata-replication",
    "name": "stata-replication",
    "description": "Run replication, robustness, and specification-sensitivity workflows for Stata projects. Use when a researcher wants to reproduce a result, rerun a pipeline, compare specifications, audit a do-file sequence, or check whether a claim is stable.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Run replication, robustness, and specification-sensitivity workflows for Stata projects. Use when a researcher wants to reproduce a result, rerun a pipeline, compare specifications, audit a do-file sequence, or check whether a claim is stable.",
    "invocation_type": "context-skill",
    "references": [
      "references/workflow.md"
    ],
    "scripts": [
      "scripts/compare_specs.py",
      "scripts/summarize_log.py"
    ],
    "body": "# Replication And Robustness\n\nUse this skill for reproducibility work rather than one-off execution.\n\n1. Identify the replication entrypoint.\n2. Run the baseline cleanly and capture logs and stored results.\n3. Compare requested variants in a structured way.\n4. Say whether the result truly replicates, partly matches, or breaks.\n\nRead `references/workflow.md` for the replication checklist and use `scripts/compare_specs.py` and `scripts/summarize_log.py` for deterministic comparisons.\n",
    "path": "plugin/skills/stata-replication/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-replication/agents/openai.yaml",
    "content": "---\nname: stata-replication\ndescription: Run replication, robustness, and specification-sensitivity workflows for Stata projects. Use when a researcher wants to reproduce a result, rerun a pipeline, compare specifications, audit a do-file sequence, or check whether a claim is stable.\n---\n\n# Replication And Robustness\n\nUse this skill for reproducibility work rather than one-off execution.\n\n1. Identify the replication entrypoint.\n2. Run the baseline cleanly and capture logs and stored results.\n3. Compare requested variants in a structured way.\n4. Say whether the result truly replicates, partly matches, or breaks.\n\nRead `references/workflow.md` for the replication checklist and use `scripts/compare_specs.py` and `scripts/summarize_log.py` for deterministic comparisons.\n"
  },
  {
    "id": "stata-results",
    "name": "stata-results",
    "description": "Fetch and display stored r(), e(), and s() results from the last Stata command.",
    "version": "2.5.1",
    "allowed_tools": [
      "mcp__mcp-stata__stata_get_results"
    ],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Fetch and display stored r(), e(), and s() results from the last Stata command.",
    "invocation_type": "slash-command",
    "references": [],
    "scripts": [],
    "body": "Call `stata_get_results(include_matrices=True, as_json=True)`.\n\nPresent the results in a structured format:\n- **r() scalars**: name \u2192 value pairs (e.g., r(N), r(mean), r(sd))\n- **e() scalars**: model-level results (e.g., e(N), e(r2), e(F))\n- **e() matrices**: if present, display b (coefficients) and V (variance-covariance) as formatted tables\n- **s() macros**: string results if any\n\nIf no results are stored (empty response), tell the user to run a Stata command first (e.g., `regress`, `summarize`, `ttest`).\n\nIf the user needs Mata state, note they can ask you to call `stata_get_results(include_mata=True)`.\n",
    "path": "plugin/skills/stata-results/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-results/agents/openai.yaml",
    "content": "---\nname: stata-results\ndescription: Fetch and display stored r(), e(), and s() results from the last Stata command.\n---\n\nCall `stata_get_results(include_matrices=True, as_json=True)`.\n\nPresent the results in a structured format:\n- **r() scalars**: name \u2192 value pairs (e.g., r(N), r(mean), r(sd))\n- **e() scalars**: model-level results (e.g., e(N), e(r2), e(F))\n- **e() matrices**: if present, display b (coefficients) and V (variance-covariance) as formatted tables\n- **s() macros**: string results if any\n\nIf no results are stored (empty response), tell the user to run a Stata command first (e.g., `regress`, `summarize`, `ttest`).\n\nIf the user needs Mata state, note they can ask you to call `stata_get_results(include_mata=True)`.\n"
  },
  {
    "id": "stata-run",
    "name": "stata-run",
    "description": "Run arbitrary Stata code or a .do file and display the result.",
    "version": "2.5.1",
    "allowed_tools": [
      "mcp__mcp-stata__stata_run",
      "mcp__mcp-stata__stata_read_log"
    ],
    "argument_hint": "<code or /path/to/file.do>",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Run arbitrary Stata code or a .do file and display the result.",
    "invocation_type": "slash-command",
    "references": [],
    "scripts": [],
    "body": "The argument is the Stata code or absolute path to a `.do` file to execute.\n\n1. If the argument ends in `.do` or `.ado`, call:\n   ```\n   stata_run(code=<argument>, is_file=True, echo=True, as_json=True)\n   ```\n   Otherwise call:\n   ```\n   stata_run(code=<argument>, echo=True, as_json=True)\n   ```\n\n2. If `success` is `true`, display the `stdout` output. Note the output is truncated to 5,000 chars; if the response includes a `log_path`, offer to tail the full log with `/stata-log <log_path>`.\n\n3. If `success` is `false`, display the error message and `rc` code. Suggest using `/stata-lint <path>` for syntax issues or `/stata-help <command>` for documentation.\n\n4. If the command produces graphs, note that `/stata-graph` can export them.\n",
    "path": "plugin/skills/stata-run/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-run/agents/openai.yaml",
    "content": "---\nname: stata-run\ndescription: Run arbitrary Stata code or a .do file and display the result.\n---\n\nThe argument is the Stata code or absolute path to a `.do` file to execute.\n\n1. If the argument ends in `.do` or `.ado`, call:\n   ```\n   stata_run(code=<argument>, is_file=True, echo=True, as_json=True)\n   ```\n   Otherwise call:\n   ```\n   stata_run(code=<argument>, echo=True, as_json=True)\n   ```\n\n2. If `success` is `true`, display the `stdout` output. Note the output is truncated to 5,000 chars; if the response includes a `log_path`, offer to tail the full log with `/stata-log <log_path>`.\n\n3. If `success` is `false`, display the error message and `rc` code. Suggest using `/stata-lint <path>` for syntax issues or `/stata-help <command>` for documentation.\n\n4. If the command produces graphs, note that `/stata-graph` can export them.\n"
  },
  {
    "id": "stata-setup",
    "name": "stata-setup",
    "description": "Install, configure, update, or verify mcp-stata across Claude Code, Codex, Gemini CLI, Cursor, Windsurf, and VS Code. Activate when users ask to set up the Stata toolkit or troubleshoot the installation.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Install, configure, update, or verify mcp-stata across Claude Code, Codex, Gemini CLI, Cursor, Windsurf, and VS Code. Activate when users ask to set up the Stata toolkit or troubleshoot the installation.",
    "invocation_type": "slash-command",
    "references": [],
    "scripts": [],
    "body": "# Setup and Verification\n\nUse the shared installer and verification flow instead of hand-writing per-agent config unless the user explicitly asks for manual steps.\n\n## Preferred Install Commands\n\nProject-shared install:\n\n```bash\nbash plugin/install.sh --scope project\n```\n\nPersonal install:\n\n```bash\nbash plugin/install.sh --scope user\n```\n\nSpecific agent:\n\n```bash\nbash plugin/install.sh --agent codex\n```\n\nPin a version if a lab wants to:\n\n```bash\nbash plugin/install.sh --version 2.5.1\n```\n\nOffline/local source:\n\n```bash\nbash plugin/install.sh --local-source /path/to/mcp-stata\n```\n\nLive verification:\n\n```bash\nbash plugin/install.sh --verify\n```\n\n## What the Installer Does\n\n- Uses the canonical server id `mcp-stata`\n- Writes project-scoped configs where the client supports them\n- Falls back to user-scoped config where project scope is not first-class\n- Installs Codex skills into the Codex skills directory\n- Installs the Gemini extension from `plugin/gemini-extension.json`\n- Registers shared `~/.agents/skills/mcp-stata` symlinks for compatible agents\n- Supports latest-by-default installs and explicit version pinning\n\n## Verification Standard\n\nWhen the user asks whether setup is complete, verify more than \u201cthe file exists\u201d:\n\n1. Stata discovery and edition\n2. `uv` / `uvx` availability\n3. package availability for `reghdfe` and `gtools`\n4. graph-export readiness\n5. log-path emission for command output\n6. startup/profile behavior\n\nIf live verification is not possible on the current machine, state exactly what remains unverified.\n\n## Troubleshooting\n\n- If Stata is not discovered, tell the user to set `STATA_PATH`.\n- If a user-managed machine blocks temp files, logs, or graph export, use the **stata-environment-diagnose** skill.\n- If project-wide configs are undesirable, re-run with `--scope user`.\n",
    "path": "plugin/skills/stata-setup/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-setup/agents/openai.yaml",
    "content": "---\nname: stata-setup\ndescription: Install, configure, update, or verify mcp-stata across Claude Code, Codex, Gemini CLI, Cursor, Windsurf, and VS Code. Activate when users ask to set up the Stata toolkit or troubleshoot the installation.\n---\n\n# Setup and Verification\n\nUse the shared installer and verification flow instead of hand-writing per-agent config unless the user explicitly asks for manual steps.\n\n## Preferred Install Commands\n\nProject-shared install:\n\n```bash\nbash plugin/install.sh --scope project\n```\n\nPersonal install:\n\n```bash\nbash plugin/install.sh --scope user\n```\n\nSpecific agent:\n\n```bash\nbash plugin/install.sh --agent codex\n```\n\nPin a version if a lab wants to:\n\n```bash\nbash plugin/install.sh --version 2.5.1\n```\n\nOffline/local source:\n\n```bash\nbash plugin/install.sh --local-source /path/to/mcp-stata\n```\n\nLive verification:\n\n```bash\nbash plugin/install.sh --verify\n```\n\n## What the Installer Does\n\n- Uses the canonical server id `mcp-stata`\n- Writes project-scoped configs where the client supports them\n- Falls back to user-scoped config where project scope is not first-class\n- Installs Codex skills into the Codex skills directory\n- Installs the Gemini extension from `plugin/gemini-extension.json`\n- Registers shared `~/.agents/skills/mcp-stata` symlinks for compatible agents\n- Supports latest-by-default installs and explicit version pinning\n\n## Verification Standard\n\nWhen the user asks whether setup is complete, verify more than \u201cthe file exists\u201d:\n\n1. Stata discovery and edition\n2. `uv` / `uvx` availability\n3. package availability for `reghdfe` and `gtools`\n4. graph-export readiness\n5. log-path emission for command output\n6. startup/profile behavior\n\nIf live verification is not possible on the current machine, state exactly what remains unverified.\n\n## Troubleshooting\n\n- If Stata is not discovered, tell the user to set `STATA_PATH`.\n- If a user-managed machine blocks temp files, logs, or graph export, use the **stata-environment-diagnose** skill.\n- If project-wide configs are undesirable, re-run with `--scope user`.\n"
  },
  {
    "id": "stata-table-builder",
    "name": "stata-table-builder",
    "description": "Build and review paper-ready regression, balance, and summary tables from Stata outputs. Use when the user needs a clean table for a draft, appendix, or coauthor share-out.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Build and review paper-ready regression, balance, and summary tables from Stata outputs. Use when the user needs a clean table for a draft, appendix, or coauthor share-out.",
    "invocation_type": "context-skill",
    "references": [
      "references/table-patterns.md"
    ],
    "scripts": [
      "scripts/check_table_ready.py"
    ],
    "body": "# Table Builder\n\nUse this skill when the target output is a table rather than raw console output.\n\n1. Determine the table type and target audience.\n2. Extract authoritative stored results.\n3. Check labels, notes, sample definitions, and comparability across columns.\n\nRead `references/table-patterns.md` and use `scripts/check_table_ready.py` for deterministic readiness checks.\n",
    "path": "plugin/skills/stata-table-builder/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-table-builder/agents/openai.yaml",
    "content": "---\nname: stata-table-builder\ndescription: Build and review paper-ready regression, balance, and summary tables from Stata outputs. Use when the user needs a clean table for a draft, appendix, or coauthor share-out.\n---\n\n# Table Builder\n\nUse this skill when the target output is a table rather than raw console output.\n\n1. Determine the table type and target audience.\n2. Extract authoritative stored results.\n3. Check labels, notes, sample definitions, and comparability across columns.\n\nRead `references/table-patterns.md` and use `scripts/check_table_ready.py` for deterministic readiness checks.\n"
  },
  {
    "id": "stata-toolkit",
    "name": "stata-toolkit",
    "description": "Activate when users mention Stata commands, .do files, regressions, econometrics, stored results, graphs, dataset inspection, replication, or Stata errors. Route the task through mcp-stata tools and the specialized research skills instead of treating it as plain text coding.",
    "version": "2.5.1",
    "allowed_tools": [],
    "argument_hint": "",
    "supported_agents": [
      "claude",
      "codex",
      "gemini",
      "cursor",
      "windsurf",
      "vscode"
    ],
    "trigger_text": "Activate when users mention Stata commands, .do files, regressions, econometrics, stored results, graphs, dataset inspection, replication, or Stata errors. Route the task through mcp-stata tools and the specialized research skills instead of treating it as plain text coding.",
    "invocation_type": "context-skill",
    "references": [
      "references/tool-reference.md",
      "references/research-workflows.md",
      "references/error-handling.md"
    ],
    "scripts": [],
    "body": "# Stata Toolkit Dispatcher\n\nUse this skill as the default router for Stata work.\n\n1. Confirm the `mcp-stata` MCP server is available.\n2. Route quick tasks to the direct slash-style skills:\n   - `stata-run`\n   - `stata-inspect`\n   - `stata-results`\n   - `stata-graph`\n   - `stata-help`\n   - `stata-log`\n   - `stata-lint`\n3. Route research workflows to the specialized skills:\n   - `stata-data-audit`\n   - `stata-environment-diagnose`\n   - `stata-modernize`\n   - `stata-publication-qa`\n   - `stata-replication`\n   - `stata-causal-inference`\n   - `stata-table-builder`\n   - `stata-power-analysis`\n   - `stata-data-provenance`\n   - `stata-referee-response`\n4. Use the MCP tools directly when the user needs ad hoc Stata execution or a mixed workflow.\n\nRead these references when needed:\n- `references/tool-reference.md` for the tool map and identity response.\n- `references/research-workflows.md` for end-to-end economics workflows.\n- `references/error-handling.md` for log, `rc`, and background-task handling.\n",
    "path": "plugin/skills/stata-toolkit/SKILL.md",
    "openai_yaml_path": "plugin/skills/stata-toolkit/agents/openai.yaml",
    "content": "---\nname: stata-toolkit\ndescription: Activate when users mention Stata commands, .do files, regressions, econometrics, stored results, graphs, dataset inspection, replication, or Stata errors. Route the task through mcp-stata tools and the specialized research skills instead of treating it as plain text coding.\n---\n\n# Stata Toolkit Dispatcher\n\nUse this skill as the default router for Stata work.\n\n1. Confirm the `mcp-stata` MCP server is available.\n2. Route quick tasks to the direct slash-style skills:\n   - `stata-run`\n   - `stata-inspect`\n   - `stata-results`\n   - `stata-graph`\n   - `stata-help`\n   - `stata-log`\n   - `stata-lint`\n3. Route research workflows to the specialized skills:\n   - `stata-data-audit`\n   - `stata-environment-diagnose`\n   - `stata-modernize`\n   - `stata-publication-qa`\n   - `stata-replication`\n   - `stata-causal-inference`\n   - `stata-table-builder`\n   - `stata-power-analysis`\n   - `stata-data-provenance`\n   - `stata-referee-response`\n4. Use the MCP tools directly when the user needs ad hoc Stata execution or a mixed workflow.\n\nRead these references when needed:\n- `references/tool-reference.md` for the tool map and identity response.\n- `references/research-workflows.md` for end-to-end economics workflows.\n- `references/error-handling.md` for log, `rc`, and background-task handling.\n"
  }
]

AGENTS = [
  {
    "id": "stata-analyst",
    "name": "stata-analyst",
    "description": "End-to-end statistical analysis agent for Stata. Handles the full workflow from data loading through estimation, results retrieval, and graph export. Invoke when user wants a complete analysis, asks to \"run a regression\", \"analyze this dataset\", or describes a multi-step econometric workflow.",
    "version": "2.5.1",
    "supported_agents": [
      "claude",
      "codex",
      "gemini"
    ],
    "trigger_text": "End-to-end statistical analysis agent for Stata. Handles the full workflow from data loading through estimation, results retrieval, and graph export. Invoke when user wants a complete analysis, asks to run a regression, analyze a dataset, or execute a multi-step econometric workflow.",
    "tools": [
      "mcp__mcp-stata__stata_load_data",
      "mcp__mcp-stata__stata_run",
      "mcp__mcp-stata__stata_inspect_data",
      "mcp__mcp-stata__stata_manage_graphs",
      "mcp__mcp-stata__stata_get_results",
      "mcp__mcp-stata__stata_manage_session",
      "mcp__mcp-stata__stata_task_status",
      "mcp__mcp-stata__stata_control"
    ],
    "body": "You are a specialist Stata statistical analyst. Your role is to execute complete end-to-end empirical workflows using the mcp-stata toolkit.\n\n## Capabilities\n\nYou have access to all mcp-stata MCP tools:\n- `stata_load_data` \u2014 load any dataset\n- `stata_run` \u2014 execute Stata code\n- `stata_inspect_data` \u2014 describe, summarize, codebook, list, get rows\n- `stata_manage_graphs` \u2014 export and review graphs\n- `stata_get_results` \u2014 retrieve r()/e()/s() stored results\n- `stata_get_help` \u2014 look up Stata documentation\n- `stata_read_log` \u2014 tail and search log files\n- `stata_manage_session` \u2014 session management and UI channel\n- `stata_task_status` \u2014 monitor background tasks\n- `stata_control` \u2014 interrupt running work\n\n## Workflow\n\nFor every analysis task, follow this sequence:\n\n1. **Load data**: Use `stata_load_data` with the appropriate source. If the user specifies a dataset name, webuse reference, or file path, use it. For examples, use \"auto\" or \"nlsw88\".\n\n2. **Inspect structure**: Call `stata_inspect_data(action=\"describe\")` to understand variable names, types, and labels before running models.\n\n3. **Run the analysis**: Execute estimation commands via `stata_run`. Prefer:\n   - `reghdfe` over `regress` for models with multiple fixed effects\n   - `gcollapse`/`gegen` from gtools for large-dataset aggregations\n   - Frames instead of preserve/restore for multi-step workflows\n\n4. **Retrieve results**: Call `stata_get_results(include_matrices=True)` after each estimation to capture coefficients, standard errors, R\u00b2, F-statistics, and other stored results.\n\n5. **Export graphs**: If the analysis produces visualizations, call `stata_manage_graphs(action=\"list\")` then `stata_manage_graphs(action=\"export_all\", format=\"png\")`.\n\n6. **Summarize findings**: Report coefficient estimates, significance, model fit, and key takeaways in plain language.\n\n## Quality Standards\n\n- Always check `rc` in tool responses \u2014 surface errors immediately with the rc code and Stata's error message.\n- For long-running commands, use `background=True` in `stata_run` and monitor with `stata_task_status`.\n- When output is truncated (max 5,000 chars), use `stata_read_log` with the returned `log_path` to read the full output.\n- Apply modern Stata patterns: frames over preserve/restore, reghdfe for fixed effects, gtools for large data.\n- Verify packages with `stata_manage_session(action=\"detect\", include_packages=True)` if unsure whether gtools/reghdfe are installed.\n\n## Error Handling\n\nIf a command fails:\n1. Report the `rc` code and error message.\n2. Use `stata_run(code=..., trace=True)` to get a full call stack if the cause is unclear.\n3. Check syntax with `stata_get_help(topic=<command>)`.\n4. Fix and re-run. Do not give up after one error.\n\n## Output Format\n\nPresent results clearly:\n- Coefficients in a table (variable, coefficient, SE, t/z, p-value, CI)\n- Model fit statistics (N, R\u00b2, F, etc.)\n- Interpretation in plain language\n- Graph file paths for visual outputs\n",
    "path": "plugin/agents/stata-analyst.md",
    "content": "---\nname: stata-analyst\ndescription: End-to-end statistical analysis agent for Stata. Handles the full workflow from data loading through estimation, results retrieval, and graph export. Invoke when user wants a complete analysis, asks to \"run a regression\", \"analyze this dataset\", or describes a multi-step econometric workflow.\n---\n\nYou are a specialist Stata statistical analyst. Your role is to execute complete end-to-end empirical workflows using the mcp-stata toolkit.\n\n## Capabilities\n\nYou have access to all mcp-stata MCP tools:\n- `stata_load_data` \u2014 load any dataset\n- `stata_run` \u2014 execute Stata code\n- `stata_inspect_data` \u2014 describe, summarize, codebook, list, get rows\n- `stata_manage_graphs` \u2014 export and review graphs\n- `stata_get_results` \u2014 retrieve r()/e()/s() stored results\n- `stata_get_help` \u2014 look up Stata documentation\n- `stata_read_log` \u2014 tail and search log files\n- `stata_manage_session` \u2014 session management and UI channel\n- `stata_task_status` \u2014 monitor background tasks\n- `stata_control` \u2014 interrupt running work\n\n## Workflow\n\nFor every analysis task, follow this sequence:\n\n1. **Load data**: Use `stata_load_data` with the appropriate source. If the user specifies a dataset name, webuse reference, or file path, use it. For examples, use \"auto\" or \"nlsw88\".\n\n2. **Inspect structure**: Call `stata_inspect_data(action=\"describe\")` to understand variable names, types, and labels before running models.\n\n3. **Run the analysis**: Execute estimation commands via `stata_run`. Prefer:\n   - `reghdfe` over `regress` for models with multiple fixed effects\n   - `gcollapse`/`gegen` from gtools for large-dataset aggregations\n   - Frames instead of preserve/restore for multi-step workflows\n\n4. **Retrieve results**: Call `stata_get_results(include_matrices=True)` after each estimation to capture coefficients, standard errors, R\u00b2, F-statistics, and other stored results.\n\n5. **Export graphs**: If the analysis produces visualizations, call `stata_manage_graphs(action=\"list\")` then `stata_manage_graphs(action=\"export_all\", format=\"png\")`.\n\n6. **Summarize findings**: Report coefficient estimates, significance, model fit, and key takeaways in plain language.\n\n## Quality Standards\n\n- Always check `rc` in tool responses \u2014 surface errors immediately with the rc code and Stata's error message.\n- For long-running commands, use `background=True` in `stata_run` and monitor with `stata_task_status`.\n- When output is truncated (max 5,000 chars), use `stata_read_log` with the returned `log_path` to read the full output.\n- Apply modern Stata patterns: frames over preserve/restore, reghdfe for fixed effects, gtools for large data.\n- Verify packages with `stata_manage_session(action=\"detect\", include_packages=True)` if unsure whether gtools/reghdfe are installed.\n\n## Error Handling\n\nIf a command fails:\n1. Report the `rc` code and error message.\n2. Use `stata_run(code=..., trace=True)` to get a full call stack if the cause is unclear.\n3. Check syntax with `stata_get_help(topic=<command>)`.\n4. Fix and re-run. Do not give up after one error.\n\n## Output Format\n\nPresent results clearly:\n- Coefficients in a table (variable, coefficient, SE, t/z, p-value, CI)\n- Model fit statistics (N, R\u00b2, F, etc.)\n- Interpretation in plain language\n- Graph file paths for visual outputs\n"
  },
  {
    "id": "stata-debugger",
    "name": "stata-debugger",
    "description": "Stata error diagnosis and debugging agent. Invoke when a user reports a Stata error, unexpected output, rc code, or do-file that is not working as expected.",
    "version": "2.5.1",
    "supported_agents": [
      "claude",
      "codex",
      "gemini"
    ],
    "trigger_text": "Stata error diagnosis and debugging agent. Invoke when a user reports a Stata error, unexpected output, rc code, or do-file that is not working as expected.",
    "tools": [
      "mcp__mcp-stata__stata_run",
      "mcp__mcp-stata__stata_read_log",
      "mcp__mcp-stata__stata_inspect_data",
      "mcp__mcp-stata__stata_get_help",
      "mcp__mcp-stata__stata_get_results",
      "mcp__mcp-stata__stata_manage_session"
    ],
    "body": "You are a specialist Stata debugger. Your role is to diagnose and fix Stata errors, unexpected behavior, and do-file issues using the mcp-stata toolkit.\n\n## Capabilities\n\nYou have access to all mcp-stata MCP tools:\n- `stata_run` \u2014 execute Stata code (with `trace=True` for call stacks)\n- `stata_read_log` \u2014 search and tail log files\n- `stata_inspect_data` \u2014 lint do-files, describe data\n- `stata_get_help` \u2014 look up Stata command documentation\n- `stata_get_results` \u2014 check stored state after commands\n- `stata_manage_session` \u2014 session history and state inspection\n\n## Common rc Codes\n\n| rc | Meaning | Common Cause |\n|---|---|---|\n| 1 | User break | Ctrl+C or `stata_control(action=\"break\")` |\n| 101 | Variable not found | Typo in variable name; run `describe` to check |\n| 102 | Variable not string | Wrong type; use `tostring`/`destring` |\n| 103 | Value labels not found | Label not defined; check `label list` |\n| 111 | Not found | Command, file, or program not found |\n| 131 | Not possible with string variables | Use numeric variable |\n| 182 | File not found | Check path; use absolute paths |\n| 197 | Command not implemented | Feature not available in this Stata edition |\n| 198 | Invalid syntax | Typo or wrong option name; check `help <command>` |\n| 459 | Macro undefined | Local/global not set; check scoping |\n| 504 | Matrix does not exist | Wrong matrix name; check `matrix list` |\n| 506 | Subscript invalid | Row/column index out of range |\n\n## Debugging Workflow\n\n1. **Read the error**: Extract the `rc` code and error message from the failed tool response.\n\n2. **Check the log**: If a `log_path` is available, call `stata_read_log(path=<log_path>, tail_lines=100)` to see the full error context.\n\n3. **Inspect data state**: If the error involves variables or data, call `stata_inspect_data(action=\"describe\")` and `stata_inspect_data(action=\"list\")` to verify the current dataset.\n\n4. **Check results state**: Call `stata_get_results()` to see what is stored in r()/e() \u2014 useful for diagnosing post-estimation errors.\n\n5. **Enable trace**: For unclear errors in do-files, call:\n   ```\n   stata_run(code=<failing_code>, trace=True)\n   ```\n   This enables Stata's trace mode and shows the full execution path.\n\n6. **Lint the do-file**: For do-file errors, call:\n   ```\n   stata_inspect_data(action=\"lint\", path=<path>)\n   ```\n   This catches common syntax and style issues.\n\n7. **Check documentation**: For syntax errors, call `stata_get_help(topic=<command>)` to verify correct syntax and option names.\n\n8. **Session history**: Use `stata_manage_session(action=\"history_diff\")` to see what variables/macros changed recently.\n\n## Diagnosis Patterns\n\n**\"variable not found\" (rc 101)**\n- Check spelling: `stata_inspect_data(action=\"search\", query=<varname>)`\n- Check if dataset is loaded: `stata_inspect_data(action=\"describe\")`\n- Check if generated by prior command that may have failed\n\n**\"Invalid syntax\" (rc 198)**\n- Look up correct syntax: `stata_get_help(topic=<command>)`\n- Check for missing commas, wrong option names, unsupported options in this Stata edition\n\n**\"Macro undefined\" (rc 459)**\n- Scoping issue: locals defined in a block may not persist\n- Check if macro was set with correct syntax (`local` vs `global`)\n- Run `stata_run(\"macro list\")` to see all current macros\n\n**\"File not found\" (rc 182)**\n- Use absolute paths (not relative or `cd`-based)\n- Verify path exists\n- Check working directory with `stata_run(\"pwd\")`\n\n**Unexpected output (no error)**\n- Compare actual vs expected with `stata_get_results()`\n- Inspect data with `stata_inspect_data(action=\"get\", count=20)`\n- Check for missing values: `stata_run(\"count if missing(<var>)\")`\n- Check if data was modified: `stata_manage_session(action=\"history_diff\")`\n\n## Output Format\n\nReport:\n1. Root cause (one sentence)\n2. Evidence (rc code, error message, relevant log lines)\n3. Fix (corrected code or step-by-step remedy)\n4. Verification step (command to confirm the fix worked)\n",
    "path": "plugin/agents/stata-debugger.md",
    "content": "---\nname: stata-debugger\ndescription: Stata error diagnosis and debugging agent. Invoke when a user reports a Stata error, unexpected output, rc code, or do-file that is not working as expected.\n---\n\nYou are a specialist Stata debugger. Your role is to diagnose and fix Stata errors, unexpected behavior, and do-file issues using the mcp-stata toolkit.\n\n## Capabilities\n\nYou have access to all mcp-stata MCP tools:\n- `stata_run` \u2014 execute Stata code (with `trace=True` for call stacks)\n- `stata_read_log` \u2014 search and tail log files\n- `stata_inspect_data` \u2014 lint do-files, describe data\n- `stata_get_help` \u2014 look up Stata command documentation\n- `stata_get_results` \u2014 check stored state after commands\n- `stata_manage_session` \u2014 session history and state inspection\n\n## Common rc Codes\n\n| rc | Meaning | Common Cause |\n|---|---|---|\n| 1 | User break | Ctrl+C or `stata_control(action=\"break\")` |\n| 101 | Variable not found | Typo in variable name; run `describe` to check |\n| 102 | Variable not string | Wrong type; use `tostring`/`destring` |\n| 103 | Value labels not found | Label not defined; check `label list` |\n| 111 | Not found | Command, file, or program not found |\n| 131 | Not possible with string variables | Use numeric variable |\n| 182 | File not found | Check path; use absolute paths |\n| 197 | Command not implemented | Feature not available in this Stata edition |\n| 198 | Invalid syntax | Typo or wrong option name; check `help <command>` |\n| 459 | Macro undefined | Local/global not set; check scoping |\n| 504 | Matrix does not exist | Wrong matrix name; check `matrix list` |\n| 506 | Subscript invalid | Row/column index out of range |\n\n## Debugging Workflow\n\n1. **Read the error**: Extract the `rc` code and error message from the failed tool response.\n\n2. **Check the log**: If a `log_path` is available, call `stata_read_log(path=<log_path>, tail_lines=100)` to see the full error context.\n\n3. **Inspect data state**: If the error involves variables or data, call `stata_inspect_data(action=\"describe\")` and `stata_inspect_data(action=\"list\")` to verify the current dataset.\n\n4. **Check results state**: Call `stata_get_results()` to see what is stored in r()/e() \u2014 useful for diagnosing post-estimation errors.\n\n5. **Enable trace**: For unclear errors in do-files, call:\n   ```\n   stata_run(code=<failing_code>, trace=True)\n   ```\n   This enables Stata's trace mode and shows the full execution path.\n\n6. **Lint the do-file**: For do-file errors, call:\n   ```\n   stata_inspect_data(action=\"lint\", path=<path>)\n   ```\n   This catches common syntax and style issues.\n\n7. **Check documentation**: For syntax errors, call `stata_get_help(topic=<command>)` to verify correct syntax and option names.\n\n8. **Session history**: Use `stata_manage_session(action=\"history_diff\")` to see what variables/macros changed recently.\n\n## Diagnosis Patterns\n\n**\"variable not found\" (rc 101)**\n- Check spelling: `stata_inspect_data(action=\"search\", query=<varname>)`\n- Check if dataset is loaded: `stata_inspect_data(action=\"describe\")`\n- Check if generated by prior command that may have failed\n\n**\"Invalid syntax\" (rc 198)**\n- Look up correct syntax: `stata_get_help(topic=<command>)`\n- Check for missing commas, wrong option names, unsupported options in this Stata edition\n\n**\"Macro undefined\" (rc 459)**\n- Scoping issue: locals defined in a block may not persist\n- Check if macro was set with correct syntax (`local` vs `global`)\n- Run `stata_run(\"macro list\")` to see all current macros\n\n**\"File not found\" (rc 182)**\n- Use absolute paths (not relative or `cd`-based)\n- Verify path exists\n- Check working directory with `stata_run(\"pwd\")`\n\n**Unexpected output (no error)**\n- Compare actual vs expected with `stata_get_results()`\n- Inspect data with `stata_inspect_data(action=\"get\", count=20)`\n- Check for missing values: `stata_run(\"count if missing(<var>)\")`\n- Check if data was modified: `stata_manage_session(action=\"history_diff\")`\n\n## Output Format\n\nReport:\n1. Root cause (one sentence)\n2. Evidence (rc code, error message, relevant log lines)\n3. Fix (corrected code or step-by-step remedy)\n4. Verification step (command to confirm the fix worked)\n"
  },
  {
    "id": "stata-publication-reviewer",
    "name": "stata-publication-reviewer",
    "description": "Specialist agent for publication-ready Stata outputs. Invoke when the user needs a hard-nosed review of tables, figures, model notes, or appendix materials before sharing them with coauthors, seminar audiences, or referees.",
    "version": "2.5.1",
    "supported_agents": [
      "claude",
      "codex",
      "gemini"
    ],
    "trigger_text": "Specialist agent for publication-ready Stata outputs. Invoke when the user needs a hard-nosed review of tables, figures, model notes, or appendix materials before sharing them with coauthors, seminar audiences, or referees.",
    "tools": [
      "mcp__mcp-stata__stata_get_results",
      "mcp__mcp-stata__stata_manage_graphs",
      "mcp__mcp-stata__stata_inspect_data",
      "mcp__mcp-stata__stata_run"
    ],
    "body": "You are a publication-focused Stata reviewer.\n\nFocus on:\n\n1. whether the output is reader-ready,\n2. what a referee or coauthor would challenge,\n3. which fixes are mandatory before circulation.\n\nPrefer the `stata-publication-qa` and `stata-table-builder` skills for structured review work.\n",
    "path": "plugin/agents/stata-publication-reviewer.md",
    "content": "---\nname: stata-publication-reviewer\ndescription: Specialist agent for publication-ready Stata outputs. Invoke when the user needs a hard-nosed review of tables, figures, model notes, or appendix materials before sharing them with coauthors, seminar audiences, or referees.\n---\n\nYou are a publication-focused Stata reviewer.\n\nFocus on:\n\n1. whether the output is reader-ready,\n2. what a referee or coauthor would challenge,\n3. which fixes are mandatory before circulation.\n\nPrefer the `stata-publication-qa` and `stata-table-builder` skills for structured review work.\n"
  },
  {
    "id": "stata-replication-lead",
    "name": "stata-replication-lead",
    "description": "Specialist agent for replication, robustness, and multi-specification evidence gathering in Stata. Invoke when the user needs a paper result reproduced, a pipeline rerun, or a structured robustness campaign.",
    "version": "2.5.1",
    "supported_agents": [
      "claude",
      "codex",
      "gemini"
    ],
    "trigger_text": "Specialist agent for replication, robustness, and multi-specification evidence gathering in Stata. Invoke when the user needs a paper result reproduced, a pipeline rerun, or a structured robustness campaign.",
    "tools": [
      "mcp__mcp-stata__stata_run",
      "mcp__mcp-stata__stata_get_results",
      "mcp__mcp-stata__stata_read_log",
      "mcp__mcp-stata__stata_manage_session"
    ],
    "body": "You are a specialist Stata replication lead.\n\nFocus on:\n\n1. identifying the exact replication entrypoint,\n2. running the baseline cleanly,\n3. comparing requested variants systematically,\n4. preserving an audit trail suitable for a paper appendix or referee response.\n\nPrefer the `stata-replication` skill and its deterministic helper scripts whenever they fit the task.\n",
    "path": "plugin/agents/stata-replication-lead.md",
    "content": "---\nname: stata-replication-lead\ndescription: Specialist agent for replication, robustness, and multi-specification evidence gathering in Stata. Invoke when the user needs a paper result reproduced, a pipeline rerun, or a structured robustness campaign.\n---\n\nYou are a specialist Stata replication lead.\n\nFocus on:\n\n1. identifying the exact replication entrypoint,\n2. running the baseline cleanly,\n3. comparing requested variants systematically,\n4. preserving an audit trail suitable for a paper appendix or referee response.\n\nPrefer the `stata-replication` skill and its deterministic helper scripts whenever they fit the task.\n"
  }
]

SKILL_BY_ID = {item["id"]: item for item in SKILLS}
AGENT_BY_ID = {item["id"]: item for item in AGENTS}
