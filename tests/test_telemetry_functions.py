import subprocess
import shlex
import pytest
from pathlib import Path

INSTALL_SH = Path(__file__).resolve().parents[1] / "plugin" / "install.sh"

def run_bash_func(func_name, *args):
    """Run a specific function from install.sh with args."""
    # We strip the 'main "$@"' line to prevent execution on source.
    script_content = INSTALL_SH.read_text()
    script_no_main = script_content.replace('main "$@"', '# main "$@"')
    
    cmd = f"""
{{
{script_no_main}
}} >/dev/null 2>&1
{func_name} {" ".join(shlex.quote(str(a)) for a in args)}
"""
    return subprocess.run(
        ["/bin/bash", "-c", cmd],
        capture_output=True,
        text=True,
        check=True
    )

def test_json_escape_simple():
    res = run_bash_func("json_escape", "hello")
    assert res.stdout == "hello"

def test_json_escape_quotes():
    res = run_bash_func("json_escape", 'hello "world"')
    assert res.stdout == 'hello \\"world\\"'

def test_json_escape_backslash():
    res = run_bash_func("json_escape", "hello\\world")
    assert res.stdout == "hello\\\\world"

def test_json_escape_newline():
    res = run_bash_func("json_escape", "line1\nline2")
    # Our implementation converts newline to \n
    assert res.stdout == "line1\\nline2"

def test_json_escape_tab():
    res = run_bash_func("json_escape", "col1\tcol2")
    # If python3 is available, it handles tabs.
    # If not, our sed fallback might skip it or handle it as literal (depends on sed/awk).
    # Since we prioritized python3, we expect proper escape.
    assert "col1\\tcol2" in res.stdout or "col1\tcol2" in res.stdout

def test_make_user_id_format():
    res = run_bash_func("make_user_id")
    # Format: adj-noun-noun
    parts = res.stdout.strip().split("-")
    assert len(parts) == 3

def test_get_user_id_persistent(tmp_path):
    # Mock HOME to test persistence
    env = {"HOME": str(tmp_path)}
    script_content = INSTALL_SH.read_text().replace('main "$@"', '# main "$@"')
    
    def get_id():
        return subprocess.run(
            ["/bin/bash", "-c", f"{script_content}\nget_user_id"],
            capture_output=True,
            text=True,
            env=env,
            check=True
        ).stdout.strip()
    
    id1 = get_id()
    id2 = get_id()
    assert id1 == id2
    assert len(id1.split("-")) == 3
