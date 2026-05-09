import pytest
import os
import tempfile
from mcp_stata.linter import StataLinter

def test_linter_cd_violation():
    linter = StataLinter()
    with tempfile.NamedTemporaryFile(mode='w', suffix='.do', delete=False) as f:
        f.write("sysuse auto\ncd /tmp\n")
        temp_path = f.name
    
    try:
        results = linter.lint_file(temp_path)
        violations = [r for r in results if "cd" in r["message"]]
        assert len(violations) == 1
        assert violations[0]["line"] == 2
    finally:
        os.unlink(temp_path)

def test_linter_long_line_violation():
    linter = StataLinter(linemax=20)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.do', delete=False) as f:
        f.write("display \"This is a very long line\"\n")
        temp_path = f.name
    
    try:
        results = linter.lint_file(temp_path)
        violations = [r for r in results if "too long" in r["message"]]
        assert len(violations) == 1
    finally:
        os.unlink(temp_path)

def test_linter_global_macro_violation():
    linter = StataLinter()
    with tempfile.NamedTemporaryFile(mode='w', suffix='.do', delete=False) as f:
        f.write("global myvar = 1\ndisplay $myvar\n")
        temp_path = f.name
    
    try:
        results = linter.lint_file(temp_path)
        violations = [r for r in results if "global macros" in r["message"]]
        assert len(violations) == 1
    finally:
        os.unlink(temp_path)

def test_linter_indentation_violation():
    linter = StataLinter(indent=4)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.do', delete=False) as f:
        f.write("if 1 {\ndisplay \"no indent\"\n}\n")
        temp_path = f.name
    
    try:
        results = linter.lint_file(temp_path)
        violations = [r for r in results if "indentation" in r["message"]]
        assert len(violations) >= 1
    finally:
        os.unlink(temp_path)

def test_linter_missing_comparison_violation():
    linter = StataLinter()
    with tempfile.NamedTemporaryFile(mode='w', suffix='.do', delete=False) as f:
        f.write("count if x < .\n")
        temp_path = f.name
    
    try:
        results = linter.lint_file(temp_path)
        violations = [r for r in results if "missing" in r["message"]]
        assert len(violations) == 1
    finally:
        os.unlink(temp_path)
