from mcp_stata.smcl.smcl2html import smcl_to_markdown


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

