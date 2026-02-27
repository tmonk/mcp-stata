"""Tests for SMCL → Markdown conversion quality.

These tests ensure the output is well-structured and readable both for LLMs
and when rendered in the stata-workbench GUI help panel.
"""
import textwrap
import pytest
from mcp_stata.smcl.smcl2html import smcl_to_markdown, _inline_to_markdown


# ---------------------------------------------------------------------------
# Inline tag conversion
# ---------------------------------------------------------------------------

def test_inline_bold():
    assert _inline_to_markdown("{bf:regress}") == "**regress**"


def test_inline_italic():
    assert _inline_to_markdown("{it:depvar}") == "*depvar*"


def test_inline_code_cmd():
    assert _inline_to_markdown("{cmd:regress mpg weight}") == "`regress mpg weight`"


def test_inline_option():
    assert _inline_to_markdown("{opt:noconstant}") == "`noconstant`"


def test_inline_opth():
    assert _inline_to_markdown("{opth:vce(vcetype)}") == "`vce(vcetype)`"


def test_inline_helpb():
    assert _inline_to_markdown("{helpb bootstrap}") == "`bootstrap`"


def test_inline_help_with_label():
    assert _inline_to_markdown("{help tsvarlist}") == "tsvarlist"


def test_inline_help_colon_label():
    assert _inline_to_markdown("{help weight}") == "weight"


def test_inline_manhelp_with_label():
    result = _inline_to_markdown("{manhelp regress_postestimation R:regress postestimation}")
    assert result == "regress postestimation"


def test_inline_manhelp_without_label():
    result = _inline_to_markdown("{manhelp regress R}")
    assert result == "regress"


def test_inline_browse_with_label():
    result = _inline_to_markdown('{browse "https://example.com":Example}')
    assert result == "[Example](https://example.com)"


def test_inline_browse_url_only():
    result = _inline_to_markdown('{browse "https://example.com"}')
    assert result == "https://example.com"


def test_inline_unknown_tag_stripped():
    result = _inline_to_markdown("{marker syntax}{...}")
    assert result == ""


def test_inline_mixed():
    result = _inline_to_markdown("{cmd:regress} is {bf:fast} and uses {opt:noconstant}")
    assert result == "`regress` is **fast** and uses `noconstant`"


# ---------------------------------------------------------------------------
# Basic structure: H1 header
# ---------------------------------------------------------------------------

def test_h1_header():
    md = smcl_to_markdown("{smcl}\n{title:Demo}\n", current_file="demo")
    assert md.startswith("# Help for demo")


def test_h1_custom_command_name():
    md = smcl_to_markdown("{smcl}\n{title:Test}\n", current_file="mycommand")
    assert "# Help for mycommand" in md


# ---------------------------------------------------------------------------
# Multiple sections → ## headings
# ---------------------------------------------------------------------------

def test_multiple_title_sections_all_appear():
    smcl = (
        "{smcl}\n"
        "{title:Syntax}\n"
        "{pstd}syntax content{p_end}\n"
        "{title:Description}\n"
        "{pstd}description content{p_end}\n"
        "{title:Options}\n"
        "{pstd}options content{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "## Syntax" in md
    assert "## Description" in md
    assert "## Options" in md


def test_sections_appear_in_order():
    smcl = (
        "{smcl}\n"
        "{title:Syntax}\n"
        "{pstd}syntax here{p_end}\n"
        "{title:Description}\n"
        "{pstd}description here{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    syntax_pos = md.index("## Syntax")
    desc_pos = md.index("## Description")
    assert syntax_pos < desc_pos


def test_section_content_under_right_heading():
    smcl = (
        "{smcl}\n"
        "{title:Description}\n"
        "{pstd}This command does regression.{p_end}\n"
        "{title:Options}\n"
        "{pstd}Use noconstant to suppress the constant.{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    desc_pos = md.index("## Description")
    opts_pos = md.index("## Options")
    assert "regression" in md[desc_pos:opts_pos]
    assert "noconstant" in md[opts_pos:]


# ---------------------------------------------------------------------------
# Dialog/syntax tab subsections → ### headings
# ---------------------------------------------------------------------------

def test_dlgtab_becomes_h3():
    smcl = (
        "{smcl}\n"
        "{title:Options}\n"
        "{dlgtab:Model}\n"
        "{phang}{opt noconstant} suppress the constant{p_end}\n"
        "{dlgtab:Reporting}\n"
        "{phang}{opt level(#)} set level{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "### Model" in md
    assert "### Reporting" in md


def test_syntab_becomes_h3():
    smcl = (
        "{smcl}\n"
        "{title:Syntax}\n"
        "{synoptset 20 tabbed}\n"
        "{syntab:Model}\n"
        "{synopt:{opt nocons:tant}}suppress constant{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "### Model" in md


def test_multiple_dlgtabs_in_options():
    smcl = (
        "{smcl}\n"
        "{title:Options}\n"
        "{dlgtab:Model}\n"
        "{phang}{opt noconstant}; model stuff{p_end}\n"
        "{dlgtab:SE/Robust}\n"
        "{phang}{opt vce(vcetype)} robust errors{p_end}\n"
        "{dlgtab:Reporting}\n"
        "{phang}{opt level(#)} confidence level{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "### Model" in md
    assert "### SE/Robust" in md
    assert "### Reporting" in md


# ---------------------------------------------------------------------------
# Synopt option tables → Markdown tables
# ---------------------------------------------------------------------------

def test_synopt_produces_table():
    smcl = (
        "{smcl}\n"
        "{title:Syntax}\n"
        "{synoptset 20 tabbed}\n"
        "{synopthdr}\n"
        "{synoptline}\n"
        "{synopt:{opt nocons:tant}}suppress constant term{p_end}\n"
        "{synopt:{opt hascons}}has user-supplied constant{p_end}\n"
        "{synoptline}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "| Option | Description |" in md
    assert "|--------|-------------|" in md
    assert "`noconstant`" in md or "nocons" in md
    assert "suppress constant term" in md
    assert "has user-supplied constant" in md


def test_synopt_opt_tag_in_option_column():
    smcl = (
        "{smcl}\n"
        "{title:Syntax}\n"
        "{synopt:{opt level(#)}}set confidence level; default is {cmd:level(95)}{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "`level(#)`" in md
    assert "`level(95)`" in md


def test_synopt_opth_tag():
    smcl = (
        "{smcl}\n"
        "{title:Syntax}\n"
        "{synopt:{opth vce(regress##vcetype:vcetype)}}vcetype options{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "| Option | Description |" in md
    assert "vcetype options" in md


def test_synopt_table_flushed_at_new_section():
    smcl = (
        "{smcl}\n"
        "{title:Syntax}\n"
        "{synopt:{opt beta}}standardized coefficients{p_end}\n"
        "{title:Description}\n"
        "{pstd}Does regression.{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    # Table rows must appear before Description section
    table_pos = md.index("| Option | Description |")
    desc_pos = md.index("## Description")
    assert table_pos < desc_pos


def test_p2coldent_statanow_feature():
    smcl = (
        "{smcl}\n"
        "{title:Syntax}\n"
        "{p2coldent:+ {opth vce(regress##vcetype:vcetype)}}StataNow feature{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "| Option | Description |" in md
    assert "StataNow feature" in md


# ---------------------------------------------------------------------------
# Paragraph handling
# ---------------------------------------------------------------------------

def test_pstd_paragraph():
    smcl = "{smcl}\n{title:Desc}\n{pstd}Hello world.{p_end}\n"
    md = smcl_to_markdown(smcl, current_file="test")
    assert "Hello world." in md


def test_phang_paragraph():
    smcl = "{smcl}\n{title:Options}\n{phang}{opt noconstant} suppresses the constant.{p_end}\n"
    md = smcl_to_markdown(smcl, current_file="test")
    assert "`noconstant`" in md
    assert "suppresses the constant." in md


def test_multiline_paragraph_joined():
    smcl = (
        "{smcl}\n"
        "{title:Desc}\n"
        "{pstd}\n"
        "This is a long paragraph\n"
        "that spans multiple lines.{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "long paragraph" in md
    assert "multiple lines" in md


def test_p_tag_with_numbers():
    smcl = "{smcl}\n{title:D}\n{p 4 6 2}Indented paragraph.{p_end}\n"
    md = smcl_to_markdown(smcl, current_file="test")
    assert "Indented paragraph." in md


# ---------------------------------------------------------------------------
# Code examples → ```stata blocks
# ---------------------------------------------------------------------------

def test_phang2_code_example():
    smcl = (
        "{smcl}\n"
        "{title:Examples}\n"
        "{pstd}Setup{p_end}\n"
        "{phang2}{cmd:. sysuse auto}{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "```stata" in md
    assert "sysuse auto" in md


def test_phang2_regression_example():
    smcl = (
        "{smcl}\n"
        "{title:Examples}\n"
        "{phang2}{cmd:. regress mpg weight foreign}{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "```stata" in md
    assert "regress mpg weight foreign" in md


def test_multiple_code_examples():
    smcl = (
        "{smcl}\n"
        "{title:Examples}\n"
        "{phang2}{cmd:. sysuse auto}{p_end}\n"
        "{phang2}{cmd:. regress mpg weight}{p_end}\n"
        "{phang2}{cmd:. regress, beta}{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert md.count("```stata") == 3
    assert "sysuse auto" in md
    assert "regress mpg weight" in md
    assert "regress, beta" in md


# ---------------------------------------------------------------------------
# Line continuation ({...})
# ---------------------------------------------------------------------------

def test_line_continuation_joined():
    smcl = (
        "{smcl}\n"
        "{title:Desc}\n"
        "{pstd}This sentence continues{...}\n"
        " across two source lines.{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "continues" in md
    assert "across two source lines" in md
    assert "{...}" not in md


def test_continuation_in_viewerdialog_stripped():
    smcl = (
        "{smcl}\n"
        '{viewerdialog regress "dialog regress"}{...}\n'
        "{title:Syntax}\n"
        "{pstd}syntax here{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "viewerdialog" not in md
    assert "## Syntax" in md


# ---------------------------------------------------------------------------
# Boilerplate removal
# ---------------------------------------------------------------------------

def test_viewerdialog_stripped():
    smcl = (
        "{smcl}\n"
        '{viewerdialog regress "dialog regress"}\n'
        "{title:Syntax}\n"
        "{pstd}x{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "viewerdialog" not in md
    assert "dialog" not in md.lower().replace("## ", "").split("\n")[0]


def test_vieweralsosee_stripped():
    smcl = (
        "{smcl}\n"
        '{vieweralsosee "[R] regress" "mansection R regress"}\n'
        "{title:Desc}\n{pstd}x{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "vieweralsosee" not in md


def test_viewerjumpto_stripped():
    smcl = (
        "{smcl}\n"
        '{viewerjumpto "Syntax" "regress##syntax"}\n'
        "{title:Desc}\n{pstd}x{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "viewerjumpto" not in md


def test_marker_tags_stripped():
    smcl = (
        "{smcl}\n"
        "{title:Options}\n"
        "{marker vcetype}{...}\n"
        "{phang}{opt vce(vcetype)} specifies vcetype.{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "marker" not in md
    assert "vcetype" in md


def test_synoptset_synoptline_stripped():
    smcl = (
        "{smcl}\n"
        "{title:Syntax}\n"
        "{synoptset 20 tabbed}\n"
        "{synopthdr}\n"
        "{synoptline}\n"
        "{synopt:{opt beta}}standardized coefficients{p_end}\n"
        "{synoptline}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "synoptset" not in md
    assert "synopthdr" not in md
    assert "synoptline" not in md


def test_include_removed_without_adopath():
    smcl = (
        "{smcl}\n"
        "{title:Syntax}\n"
        "INCLUDE help sncmdnote\n"
        "{synopt:{opt beta}}standardized coefficients{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "INCLUDE" not in md
    assert "sncmdnote" not in md
    assert "standardized coefficients" in md


def test_comment_lines_stripped():
    smcl = (
        "{smcl}\n"
        "{* *! version 1.0 01jan2025}\n"
        "{title:Desc}\n"
        "{pstd}Hello.{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "version" not in md
    assert "Hello." in md


def test_horizontal_rule():
    smcl = (
        "{smcl}\n"
        "{title:Examples}\n"
        "        {hline}\n"
        "{phang2}{cmd:. sysuse auto}{p_end}\n"
        "        {hline}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "---" in md


# ---------------------------------------------------------------------------
# Stored results p2col tables
# ---------------------------------------------------------------------------

def test_p2col_section_header():
    smcl = (
        "{smcl}\n"
        "{title:Stored results}\n"
        "{pstd}{cmd:regress} stores the following in {cmd:e()}:{p_end}\n"
        "{synoptset 23 tabbed}\n"
        "{p2col 5 23 26 2: Scalars}{p_end}\n"
        "{synopt:{cmd:e(N)}}number of observations{p_end}\n"
        "{synopt:{cmd:e(r2)}}R-squared{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="test")
    assert "## Stored results" in md
    assert "**Scalars**" in md
    assert "`e(N)`" in md
    assert "number of observations" in md
    assert "`e(r2)`" in md
    assert "R-squared" in md


# ---------------------------------------------------------------------------
# Realistic regress-like test (integration style)
# ---------------------------------------------------------------------------

REGRESS_SAMPLE = textwrap.dedent("""\
    {smcl}
    {* *! version 1.0  01jan2025}
    {viewerdialog regress "dialog regress"}{...}
    {vieweralsosee "[R] regress" "mansection R regress"}{...}
    {viewerjumpto "Syntax" "regress##syntax"}{...}
    {p2colset 1 16 18 2}{...}
    {p2col:{bf:[R] regress} {hline 2}}Linear regression{p_end}
    {p2colreset}{...}

    INCLUDE help sncmdnote

    {marker syntax}{...}
    {title:Syntax}

    {p 8 16 2}
    {opt regress} {it:depvar} [{it:indepvars}] [{cmd:,} {it:options}]

    {synoptset 20 tabbed}{...}
    {synopthdr}
    {synoptline}
    {syntab:Model}
    {synopt :{opt nocons:tant}}suppress constant term{p_end}
    {synopt :{opt h:ascons}}has user-supplied constant{p_end}
    {syntab:Reporting}
    {synopt :{opt l:evel(#)}}set confidence level; default is {cmd:level(95)}{p_end}
    {synoptline}

    {marker description}{...}
    {title:Description}

    {pstd}
    {cmd:regress} performs ordinary least-squares linear regression.

    {marker options}{...}
    {title:Options}

    {dlgtab:Model}

    {phang}
    {opt noconstant}; see
    {helpb estimation options##noconstant:[R] Estimation options}.

    {dlgtab:Reporting}

    {phang}
    {opt level(#)}; see {help level}.

    {marker examples}{...}
    {title:Examples}

    {pstd}Setup{p_end}
    {phang2}{cmd:. sysuse auto}{p_end}

    {pstd}Fit a linear regression{p_end}
    {phang2}{cmd:. regress mpg weight foreign}{p_end}

    {marker results}{...}
    {title:Stored results}

    {pstd}
    {cmd:regress} stores the following in {cmd:e()}:

    {synoptset 23 tabbed}{...}
    {p2col 5 23 26 2: Scalars}{p_end}
    {synopt:{cmd:e(N)}}number of observations{p_end}
    {synopt:{cmd:e(r2)}}R-squared{p_end}
    {p2colreset}{...}

    {marker references}{...}
    {title:References}

    {phang}
    Davidson, R., and J. G. MacKinnon. 1993.
    {it:Estimation and Inference in Econometrics}.
    New York: Oxford University Press.
""")


def test_regress_sample_h1():
    md = smcl_to_markdown(REGRESS_SAMPLE, current_file="regress")
    assert "# Help for regress" in md


def test_regress_sample_all_sections():
    md = smcl_to_markdown(REGRESS_SAMPLE, current_file="regress")
    for section in ("Syntax", "Description", "Options", "Examples", "Stored results", "References"):
        assert f"## {section}" in md, f"Missing section: {section}"


def test_regress_sample_subsections():
    md = smcl_to_markdown(REGRESS_SAMPLE, current_file="regress")
    assert "### Model" in md
    assert "### Reporting" in md


def test_regress_sample_option_table():
    md = smcl_to_markdown(REGRESS_SAMPLE, current_file="regress")
    assert "| Option | Description |" in md
    # Options from Syntax section
    assert "suppress constant term" in md
    assert "has user-supplied constant" in md
    assert "`level(95)`" in md


def test_regress_sample_code_examples():
    md = smcl_to_markdown(REGRESS_SAMPLE, current_file="regress")
    assert "```stata" in md
    assert "sysuse auto" in md
    assert "regress mpg weight foreign" in md


def test_regress_sample_stored_results_table():
    md = smcl_to_markdown(REGRESS_SAMPLE, current_file="regress")
    assert "**Scalars**" in md
    assert "`e(N)`" in md
    assert "number of observations" in md


def test_regress_sample_no_boilerplate():
    md = smcl_to_markdown(REGRESS_SAMPLE, current_file="regress")
    assert "viewerdialog" not in md
    assert "vieweralsosee" not in md
    assert "viewerjumpto" not in md
    assert "INCLUDE" not in md
    assert "sncmdnote" not in md
    assert "{...}" not in md
    assert "marker" not in md.replace("## ", "")


def test_regress_sample_no_raw_braces():
    md = smcl_to_markdown(REGRESS_SAMPLE, current_file="regress")
    # No unprocessed SMCL tags should remain
    import re
    remaining_tags = re.findall(r"\{[a-zA-Z][^}]{0,30}\}", md)
    assert not remaining_tags, f"Unprocessed SMCL tags remain: {remaining_tags}"


def test_regress_sample_references():
    md = smcl_to_markdown(REGRESS_SAMPLE, current_file="regress")
    assert "Davidson" in md
    assert "*Estimation and Inference in Econometrics*" in md


# ---------------------------------------------------------------------------
# Legacy tests (preserved for backwards compatibility)
# ---------------------------------------------------------------------------

def test_smcl_to_markdown_title_and_paragraph():
    smcl = "{smcl}\n{title:Demo}\n{p 0 4 2}Hello {bf:world}!{p_end}\n"
    md = smcl_to_markdown(smcl, current_file="demo")
    assert md.startswith("# Help for demo")
    assert "Hello **world**!" in md


def test_smcl_to_markdown_multiple_paragraphs():
    smcl = "{smcl}\n{title:Sample}\n{pstd}First line{p_end}\n{pstd}Second line{p_end}\n"
    md = smcl_to_markdown(smcl, current_file="sample")
    assert md.startswith("# Help for sample")
    assert "First line" in md
    assert "Second line" in md


def test_smcl_to_markdown_inline_styles_and_code():
    smcl = (
        "{smcl}\n"
        "{title:Styled}\n"
        "{pstd}Bold {bf:text} and italics {it:text}.{p_end}\n"
        "{pstd}Command {cmd:regress price mpg} shown.{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="styled")
    assert "**text**" in md
    assert "*text*" in md
    assert "`regress price mpg`" in md


def test_smcl_to_markdown_includes_and_braces_are_removed():
    smcl = (
        "{smcl}\n"
        "{title:IncludeTest}\n"
        "INCLUDE help missing_file\n"
        "{pstd}Plain text {bf:kept}.{p_end}\n"
    )
    md = smcl_to_markdown(smcl, current_file="includetest", adopath="/nonexistent")
    assert "{bf:" not in md
    assert "Plain text **kept**." in md

