"""
Stata Linter Logic
Adapted from World Bank DIME Analytics repkit (MIT Licensed)
https://github.com/worldbank/repkit

Logic adapted for Stata Workbench.
"""

import re
import os
from typing import List, Dict, Any, Tuple

class StataLinter:
    def __init__(self, indent: int = 4, linemax: int = 80, tab_space: int = 4):
        self.indent = indent
        self.linemax = linemax
        self.tab_space = tab_space

    def lint_file(self, file_path: str) -> List[Dict[str, Any]]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        results = []
        comment_delimiter = 0

        for line_index, line in enumerate(lines):
            # Update comment delimiter state (/* ... */)
            comment_delimiter = self._update_comment_delimiter(comment_delimiter, line)

            # Skip comments and empty lines
            stripped = line.lstrip()
            if stripped.startswith(("*", "//")) or comment_delimiter > 0 or not stripped:
                continue

            # Run checks
            self._check_abstract_index(line_index, line, results)
            self._check_bad_indent(line_index, line, lines, results)
            self._check_whitespace_symbol(line_index, line, results)
            self._check_condition_missing(line_index, line, results)
            self._check_explicit_if(line_index, line, results)
            self._check_dont_use_delimit(line_index, line, results)
            self._check_dont_use_cd(line_index, line, results)
            self._check_too_long_line(line_index, line, results)
            self._check_global_macro_parentheses(line_index, line, results)
            self._check_backslash_path(line_index, line, results)
            self._check_tilde_negation(line_index, line, results)

        return results

    def _update_comment_delimiter(self, comment_delimiter: int, line: str) -> int:
        if re.search(r"\/\*.*\*\/", line):
            pass
        elif re.search(r"\/\*", line):
            comment_delimiter += 1
        elif re.search(r"\*\/", line) and comment_delimiter > 0:
            comment_delimiter -= 1
        return comment_delimiter

    def _check_abstract_index(self, line_index: int, line: str, results: List[Dict[str, Any]]):
        if re.search(r"^(qui[a-z]*\s+)?(foreach|forv)", line.lstrip()):
            words = line.split()
            index_name = None
            for i, word in enumerate(words):
                if re.search(r"^(foreach)", word) and i + 1 < len(words):
                    index_name = words[i+1]
                    break
                elif re.search(r"^(forv)", word) and i + 1 < len(words):
                    index_name = words[i+1].split("=")[0]
                    break
            
            if index_name and len(set(index_name)) == 1:
                results.append({
                    "line": line_index + 1,
                    "type": "style",
                    "message": f"In for loops, index names should describe what the code is looping over. Do not use an abstract index such as '{index_name}'."
                })

    def _check_bad_indent(self, line_index: int, line: str, lines: List[str], results: List[Dict[str, Any]]):
        # Simplified version of indent check
        if self._loop_open(line):
            line_ws = line.expandtabs(self.tab_space)
            base_indent = len(line_ws) - len(line_ws.lstrip())
            
            j = 1
            embedded = 0
            while line_index + j < len(lines):
                next_line = lines[line_index + j]
                if self._loop_open(next_line):
                    embedded += 1
                elif self._loop_close(next_line):
                    if embedded > 0:
                        embedded -= 1
                    else:
                        break
                
                if embedded == 0:
                    stripped_next = next_line.lstrip()
                    if stripped_next and not stripped_next.startswith(("*", "//")):
                        next_ws = next_line.expandtabs(self.tab_space)
                        next_indent = len(next_ws) - len(next_ws.lstrip())
                        if next_indent - base_indent < self.indent:
                            results.append({
                                "line": line_index + j + 1,
                                "type": "style",
                                "message": f"After declaring a loop or if-else statement, add indentation ({self.indent} spaces)."
                            })
                            # Only warn once per loop to avoid noise
                            break
                j += 1

    def _loop_open(self, line: str) -> bool:
        rstrip = re.sub(r"((\/\/)|(\/\*)).*", "", line).rstrip()
        if rstrip and rstrip.endswith("{"):
            if re.search(r"^(qui[a-z]*\s+)?(foreach |forv|if |else )", line.lstrip()):
                return True
        return False

    def _loop_close(self, line: str) -> bool:
        rstrip = re.sub(r"((\/\/)|(\/\*)).*", "", line).rstrip()
        return rstrip.endswith("}") if rstrip else False

    def _check_whitespace_symbol(self, line_index: int, line: str, results: List[Dict[str, Any]]):
        line_clean = line.split("///")[0]
        # Skip strings
        parts = line_clean.split('"')
        pattern_before = r"(?:[a-zA-Z0-9_)'\]])(?:<|>|=|\+|-|\*|\^)"
        pattern_after = r"(?:(?:<|>|=|\+|-|\*|\^)(?:[a-zA-Z0-9_(`.]|$))"

        for i, part in enumerate(parts):
            if i % 2 == 0: # Outside quotes
                if re.search(pattern_before, part) or re.search(pattern_after, part):
                    results.append({
                        "line": line_index + 1,
                        "type": "style",
                        "message": "It is recommended to use whitespaces before and after math symbols (>, <, =, +, etc.)."
                    })
                    break

    def _check_condition_missing(self, line_index: int, line: str, results: List[Dict[str, Any]]):
        if re.search(r"(<|<=|!=|~=)( )*(\.(?![0-9]))", line):
            results.append({
                "line": line_index + 1,
                "type": "style",
                "message": "Use '!missing(var)' instead of comparisons to '.' (e.g., 'var < .')."
            })

    def _check_explicit_if(self, line_index: int, line: str, results: List[Dict[str, Any]]):
        match = re.search(r"(?:^|\s)(?:if|else if)\s", line.lstrip())
        if match:
            condition = line[match.end():].split("{")[0].strip()
            if condition and not re.search(r"(=|<|>|missing\(|inrange\(|inlist\()", condition):
                results.append({
                    "line": line_index + 1,
                    "type": "style",
                    "message": f"Always explicitly specify the condition in 'if' statements (e.g., 'if {condition} == 1' instead of 'if {condition}')."
                })

    def _check_dont_use_delimit(self, line_index: int, line: str, results: List[Dict[str, Any]]):
        if re.search(r"#delimit(?! cr)", line):
            results.append({
                "line": line_index + 1,
                "type": "style",
                "message": "Avoid using '#delimit'. Use '///' for line breaks instead."
            })

    def _check_dont_use_cd(self, line_index: int, line: str, results: List[Dict[str, Any]]):
        if re.search(r"^cd\s", line.lstrip()):
            results.append({
                "line": line_index + 1,
                "type": "style",
                "message": "Avoid using 'cd'. Use absolute or dynamic file paths instead."
            })

    def _check_too_long_line(self, line_index: int, line: str, results: List[Dict[str, Any]]):
        clean_line = line.rstrip("\n")
        if len(clean_line) > self.linemax:
            results.append({
                "line": line_index + 1,
                "type": "style",
                "message": f"Line is too long ({len(clean_line)} chars). Use '///' to break lines at {self.linemax} characters."
            })

    def _check_global_macro_parentheses(self, line_index: int, line: str, results: List[Dict[str, Any]]):
        if re.search(r"\$[a-zA-Z][a-zA-Z0-9_]*", line) and not re.search(r"\$\{[a-zA-Z0-9_]+\}", line):
            # Check if there are any $ without { immediately following
            matches = re.finditer(r"\$([a-zA-Z][a-zA-Z0-9_]*)", line)
            for m in matches:
                # If it's not preceded by something that escaped it (though Stata doesn't really escape $ like that)
                # and not followed by {, it's a violation
                start = m.start()
                if start + 1 < len(line) and line[start+1] != '{':
                    results.append({
                        "line": line_index + 1,
                        "type": "style",
                        "message": "Always use '${}' for global macros to avoid ambiguity."
                    })
                    break

    def _check_backslash_path(self, line_index: int, line: str, results: List[Dict[str, Any]]):
        if re.search(r"^(global|local|cd)\s", line.lstrip()) and "\\" in line:
            results.append({
                "line": line_index + 1,
                "type": "check",
                "message": "Are you using backslashes ('\\') for a file path? If so, use forward slashes ('/') instead for cross-platform compatibility."
            })

    def _check_tilde_negation(self, line_index: int, line: str, results: List[Dict[str, Any]]):
        if re.search(r"~=\s*([^\s.]|\.[0-9]+)", line):
            results.append({
                "line": line_index + 1,
                "type": "check",
                "message": "Are you using tilde (~) for negation? If so, use bang (!) instead (e.g., '!=')."
            })
