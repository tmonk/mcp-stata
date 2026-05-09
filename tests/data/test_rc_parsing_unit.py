import pytest
from mcp_stata.stata_client import StataClient

class TestRCParsingUnit:
    @pytest.fixture
    def client(self):
        return StataClient()

    def test_parse_rc_from_smcl_search_tag(self, client):
        smcl = "{txt}{search r(111), local:r(111);}"
        assert client._parse_rc_from_smcl(smcl) == 111

    def test_parse_rc_from_smcl_standalone(self, client):
        smcl = "some output\nr(601);\n"
        assert client._parse_rc_from_smcl(smcl) == 601

    def test_parse_rc_from_smcl_false_positive(self, client):
        # char(10) ends in r(10) but should not match without semicolon or search tag
        smcl = "{txt}241{com}.         local NL = char(10)"
        assert client._parse_rc_from_smcl(smcl) is None

    def test_parse_rc_from_smcl_multi_line(self, client):
        smcl = """
{res}{err}variable {bf}compl_gloves{sf} not found
{txt}{search r(111), local:r(111);}
"""
        assert client._parse_rc_from_smcl(smcl) == 111

    def test_parse_rc_from_text_search_pattern(self, client):
        text = "search r(111), local:r(111);"
        assert client._parse_rc_from_text(text) == 111

    def test_parse_rc_from_text_standalone(self, client):
        text = "error happened\nr(198);"
        assert client._parse_rc_from_text(text) == 198

    def test_parse_rc_from_text_false_positive(self, client):
        text = "local NL = char(10)"
        assert client._parse_rc_from_text(text) is None

    def test_parse_rc_from_smcl_complex_boundary(self, client):
        # Should match if preceded by space or start of line
        assert client._parse_rc_from_smcl(" r(123);") == 123
        assert client._parse_rc_from_smcl("\nr(123);") == 123
        # Should NOT match if preceded by word character (like char)
        assert client._parse_rc_from_smcl("char(10);") is None
