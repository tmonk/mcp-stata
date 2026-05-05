import json

import pytest

from mcp_stata.server import stata_get_results, stata_run

pytestmark = pytest.mark.requires_stata


@pytest.mark.asyncio
async def test_stata_get_results_returns_mata_structured_state():
    session_id = "mata_e2e"
    await stata_run(code="mata: mata clear", session_id=session_id, strip_smcl=True)
    await stata_run(code="mata: real scalar a", session_id=session_id, strip_smcl=True)
    await stata_run(code="mata: a=42", session_id=session_id, strip_smcl=True)
    await stata_run(code='mata: string scalar s', session_id=session_id, strip_smcl=True)
    await stata_run(code='mata: s="world"', session_id=session_id, strip_smcl=True)
    await stata_run(code="mata: real matrix M", session_id=session_id, strip_smcl=True)
    await stata_run(code="mata: M=J(2,2,0)", session_id=session_id, strip_smcl=True)
    await stata_run(code="mata: M[1,1]=10", session_id=session_id, strip_smcl=True)
    await stata_run(code="mata: M[1,2]=20", session_id=session_id, strip_smcl=True)
    await stata_run(code="mata: M[2,1]=30", session_id=session_id, strip_smcl=True)
    await stata_run(code="mata: M[2,2]=40", session_id=session_id, strip_smcl=True)
    await stata_run(
        code="mata:\nreal scalar h(real scalar x) {\n return(x+1)\n}\nend",
        session_id=session_id,
        strip_smcl=True,
    )

    out = await stata_get_results(session_id=session_id, include_mata=True)
    payload = json.loads(out)
    assert "mata" in payload
    assert payload["mata"]["success"] is True
    objects = {o["name"]: o for o in payload["mata"]["objects"]}
    funcs = {f["name"]: f for f in payload["mata"]["functions"]}
    assert objects["a"]["value"] == 42
    assert objects["s"]["value"] == "world"
    assert objects["M"]["value"]["values"][1][1] == 40
    assert "h" in funcs
