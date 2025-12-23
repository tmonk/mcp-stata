from mcp_stata.stata_client import StataClient


def test_select_stata_error_message_from_nested_output():
    client = StataClient()
    cases = [
        (
            """
. ********************************************************************************
. *** EXECUTION ******************************************************************
. ********************************************************************************
.
.
. *** Appendix Figure 5: Decay of Preventive Behaviors
.
. * Panel A: Shaking hands
. make_decay_graph, ///
>     depvar(compl_shake_hands) ///
>     name("$out_dir/Appendix_Figure5_tableA") ///
>     xtitle("Deaths per 100,000 in Home Country") ///
>         ytitle("Wear gloves in June & July")
  ----------------------------------------------------------------------------------- begin make_decay_graph ---
  - syntax, depvar(string) name(string) [g_color(string)] [xtitle(string) ytitle(string)] [save_gph(string)] [line_source(string)] [fe_override(string)]
  - local used_controls "$controls_base"
  = local used_controls "female age graduate"
  - if ""
type mismatch
  ------------------------------------------------------------------------------------- end make_decay_graph ---
r(109);

end of do-file

r(109);
""",
            "type mismatch",
        ),
        (
            """
. do "/tmp/missing_child.do"
file /tmp/missing_child.do not found
r(601);

end of do-file

r(601);
""",
            "file /tmp/missing_child.do not found",
        ),
        (
            """
. summarize price, foo
option foo not allowed
r(198);
""",
            "option foo not allowed",
        ),
        (
            """
. count if price < 0
no observations
r(2000);
""",
            "no observations",
        ),
        (
            """
. regress price bogusvar
variable bogusvar not found
r(111);
""",
            "variable bogusvar not found",
        ),
        (
            """
. matrix A = (1,2) \ (3,4)
. matrix B = (1,2,3)
. matrix C = A + B
conformability error
r(503);
""",
            "conformability error",
        ),
    ]

    for text, expected in cases:
        assert client._select_stata_error_message(text, "fallback") == expected


def test_select_stata_error_message_fallback():
    client = StataClient()
    text = """
end of do-file

r(459);
"""
    assert client._select_stata_error_message(text, "fallback") == "r(459);"


def test_select_stata_error_message_skips_prompts_but_finds_error():
    client = StataClient()
    text = """
  - gen pc_11_10 = total_deaths11_10 / population * 100000
  - capture confirm variable total_deaths_in_US11_10
  - if _rc == 0 {
    gen pc_11_10_in_US = total_deaths_in_US11_10 / population_U
> S * 100000
    }
invalid name
r(198);
"""
    assert client._select_stata_error_message(text, "fallback") == "invalid name"
