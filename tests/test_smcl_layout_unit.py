import importlib.util
from pathlib import Path


def _load_smcl_module():
    module_path = Path(__file__).resolve().parents[1] / "src" / "mcp_stata" / "smcl" / "smcl2html.py"
    spec = importlib.util.spec_from_file_location("mcp_stata_smcl2html", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


smcl2html = _load_smcl_module()


def test_strip_smcl_preserves_codebook_column_layout():
    text = (
        "{com}. codebook price\n\n"
        "{txt}{hline}\n"
        "{res}price{right:Price}\n"
        "{txt}{hline}\n\n"
        "{col 19}Type: Numeric ({res}int{txt})\n"
    )

    rendered = smcl2html.strip_smcl(text)
    lines = rendered.splitlines()

    assert lines[0] == ". codebook price"
    assert lines[2] == "------------------------------------------------------------"
    assert lines[3] == "price Price"
    assert lines[4] == "------------------------------------------------------------"
    assert lines[6].startswith("                  Type: Numeric (int)")


def test_strip_smcl_preserves_describe_alignment_and_newlines():
    text = (
        "{com}. describe\n\n"
        "{txt}Contains data from {res}/Applications/StataNow/ado/base/a/auto.dta\n"
        "{txt} Observations:{res}            74                  1978 automobile data\n"
        "{txt}    Variables:{res}            12                  13 Apr 2024 17:45\n"
    )

    rendered = smcl2html.strip_smcl(text)
    lines = rendered.splitlines()

    assert lines[0] == ". describe"
    assert lines[2] == "Contains data from /Applications/StataNow/ado/base/a/auto.dta"
    assert lines[3] == " Observations:            74                  1978 automobile data"
    assert lines[4] == "    Variables:            12                  13 Apr 2024 17:45"


def test_strip_smcl_handles_col_and_space_precisely():
    rendered = smcl2html.strip_smcl("abc{col 10}d\na{space 5}b\n")

    assert rendered.splitlines()[0] == "abc      d"
    assert rendered.splitlines()[1] == "a     b"


def test_strip_smcl_handles_p2col_rows():
    rendered = smcl2html.strip_smcl("{p2colset 4 20 22 2}{p2col :Left}Right side text{p_end}\n")

    assert rendered.splitlines()[0] == "    Left              Right side text"


def test_strip_smcl_retains_hline_width():
    assert smcl2html.strip_smcl("{hline 5}\n").splitlines()[0] == "-----"


def test_strip_smcl_keeps_command_and_result_text():
    text = '{com}. display "hello world"\n{txt}{res}hello world\n'

    rendered = smcl2html.strip_smcl(text)

    assert "hello world" in rendered
    assert ". display \"hello world\"" in rendered


def test_strip_smcl_keeps_error_messages():
    text = "{com}. regress price mpg\n{err}variable mpg not found\n{txt}\n"

    rendered = smcl2html.strip_smcl(text)

    assert "variable mpg not found" in rendered
    assert ". regress price mpg" in rendered


def test_strip_smcl_keeps_inline_formatted_content():
    text = "{bf:Bold label} {it:italic detail} {res:42}\n"

    rendered = smcl2html.strip_smcl(text)

    assert "Bold label" in rendered
    assert "italic detail" in rendered
    assert "42" in rendered
