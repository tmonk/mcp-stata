from mcp_stata.stata_client import StataClient


def test_smcl_to_text_strips_markup():
    client = StataClient()
    smcl = "{smcl}\n{p 0 4 2}Hello {bf:world}!{p_end}\n{viewerdialog regress}\n"
    text = client._smcl_to_text(smcl)
    assert "Hello world!" in text
    assert "{" not in text


def test_smcl_to_text_preserves_lines():
    client = StataClient()
    smcl = "{smcl}\nTitle line\n{p 0 4 2}Second line{p_end}\n"
    text = client._smcl_to_text(smcl)
    lines = text.splitlines()
    assert lines[0].startswith("Title")
    assert "Second line" in lines[-1]


def test_smcl_to_text_merge_paragraphs_joins_wrapped_lines():
    client = StataClient()
    smcl = (
        "{smcl}\n"
        "{title:Description}\n"
        "{pstd}\n"
        "This paragraph is wrapped\n"
        "across two lines for display width.\n"
        "{p_end}\n"
    )
    text = client._smcl_to_text(smcl, merge_paragraphs=True)
    assert "This paragraph is wrapped across two lines for display width." in text


def test_smcl_to_text_without_merge_paragraphs_keeps_line_breaks():
    client = StataClient()
    smcl = (
        "{smcl}\n"
        "{title:Description}\n"
        "{pstd}\n"
        "This paragraph is wrapped\n"
        "across two lines for display width.\n"
        "{p_end}\n"
    )
    text = client._smcl_to_text(smcl, merge_paragraphs=False)
    assert "This paragraph is wrapped\nacross two lines for display width." in text
