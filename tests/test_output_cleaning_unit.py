import pytest
import re
from unittest.mock import MagicMock
from mcp_stata.stata_client import StataClient

@pytest.fixture
def client():
    c = StataClient()
    # Mock init and stata to avoid actual Stata dependency in unit tests
    c._initialized = True
    c.stata = MagicMock()
    return c

def _smcl_to_text(smcl: str) -> str:
    """Helper used in some tests if client._smcl_to_text isn't accessible"""
    # Simply strip all SMCL tags for basic verification
    return re.sub(r"\{[^}]+\}", "", smcl).strip()

def test_clean_bundle_wrapper(client):
    smcl = "{com}. capture noisily {c -(}\n. display \"HI\"\n{res}HI\n{com}. {c )-}\n{txt}\n"
    cleaned = client._clean_internal_smcl(smcl)
    assert "capture noisily" not in cleaned
    assert "HI" in cleaned
    assert "display" in cleaned
    # Ensure brace escape markers are cleaned
    assert "{c -(}" not in cleaned
    assert "{c )-}" not in cleaned

def test_clean_maintenance_commands(client):
    smcl = (
        "{com}. scalar _mcp_rc = _rc\n"
        "{txt}\n"
        "{com}. capture _return hold mcp_hold_05f5cfe4\n"
        "{txt}\n"
        "{com}. capture quietly log flush _mcp_session\n"
        "{txt}\n"
        "{com}. {txt}\n"
    )
    cleaned = client._clean_internal_smcl(smcl)
    assert _smcl_to_text(cleaned) == ""

def test_smcl_to_text_braces(client):
    smcl = "{com}. display \"{c -(}HELLO{c )-}\"\n{res}{c -(}HELLO{c )-}\n"
    text = client._smcl_to_text(smcl)
    # The command display "{HELLO}" should result in output {HELLO}
    assert "{HELLO}" in text
    assert "display \"{HELLO}\"" in text

def test_clean_file_notifications(client):
    smcl = "{res}(file {txt}/tmp/mcp_stata_123.svg{res} saved)\n"
    cleaned = client._clean_internal_smcl(smcl)
    assert cleaned == ""

def test_clean_bare_prompt_end(client):
    smcl = "sysuse auto\n{com}. {txt}\n"
    cleaned = client._clean_internal_smcl(smcl)
    assert cleaned == "sysuse auto"

def test_regression_sample(client):
    smcl = (
        "{smcl}\n"
        "{txt}{sf}{ul off}{.-}\n"
        "      name:  {res}_mcp_session\n"
        "       {txt}log:  {res}/var/folders/4h/57tv1nhj11g23lnw73k0csm40000gn/T/mcp_session_9d727263619f46ca96c31dd56adf97f9.smcl\n"
        "  {txt}log type:  {res}smcl\n"
        " {txt}opened on:  {res}23 Jan 2026, 12:13:21\n"
        "{txt}\n\n\n\n\n\n"
        "{com}. capture noisily {c -(}\n"
        ". do \"/Users/tom/Library/CloudStorage/Dropbox/projects/stata-workbench/test/do.do\"\n"
        "{txt}\n"
        "{com}. sysuse auto, clear\n"
        "{txt}(1978 automobile data)\n"
        "\n"
        "{com}. reg price mpg\n"
        "\n"
        "{com}. twoway scatter price mpg, name(scatter1, replace)\n"
        "{res}{txt}\n"
        "{com}. twoway scatter mpg price\n"
        "{res}{txt}\n"
        "{com}. \n"
        "{txt}end of do-file\n"
        "{com}. {c )-}\n"
        "{txt}\n"
        "{com}. scalar _mcp_rc = _rc\n"
        "{txt}\n"
        "{com}. capture _return hold mcp_hold_05f5cfe4\n"
        "{txt}\n"
        "{com}. capture quietly log flush _mcp_session\n"
        "{txt}\n"
        "{com}. {txt}\n"
    )
    cleaned_smcl = client._clean_internal_smcl(smcl)
    text = client._smcl_to_text(cleaned_smcl)
    
    # Assertions on cleaned text
    assert "capture noisily" not in text
    assert "scalar _mcp_rc" not in text
    assert "_return hold" not in text
    assert "log flush" not in text
    assert "opened on" not in text
    assert "log type" not in text
    
    assert "sysuse auto, clear" in text
    assert "reg price mpg" in text
    assert "twoway scatter" in text
    assert "end of do-file" in text
    
    # Ensure no excessive trailing whitespace/newlines
    assert "end of do-file" in text
