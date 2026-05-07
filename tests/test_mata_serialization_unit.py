import json
from unittest.mock import AsyncMock, patch

import pytest

from mcp_stata.server import stata_get_results
from mcp_stata.models import ToolEnvelope
from mcp_stata.stata_client import StataClient


def test_parse_mata_describe_extracts_objects_and_functions():
    sample = """
    # bytes   type                        name and extent

               32   real matrix                 M[2,2]
                8   real scalar                 a
               24   real rowvector              v[3]
               96   real scalar                 g()
    """
    parsed = StataClient._parse_mata_describe(sample, max_objects=20)
    assert len(parsed) == 4
    assert parsed[0]["name"] == "M"
    assert parsed[0]["shape"] == "2,2"
    assert parsed[1]["name"] == "a"
    assert parsed[1]["shape"] is None
    assert parsed[2]["name"] == "v"
    assert parsed[2]["shape"] == "3"
    assert parsed[3]["name"] == "g"
    assert parsed[3]["is_function"] is True


def test_json_safe_mata_value_handles_complex_numbers():
    out = StataClient._json_safe_mata_value(3 + 4j)
    assert out == {"re": 3.0, "im": 4.0}


@pytest.mark.asyncio
async def test_stata_get_results_includes_structured_mata_payload():
    mock_session = AsyncMock()
    mock_session.call = AsyncMock(
        side_effect=[
            {"r": {"N": 10}, "e": {}, "s": {}},
            {"success": True, "objects": [{"name": "a"}], "functions": [{"name": "g"}]},
        ]
    )
    with patch("mcp_stata.server.session_manager.get_or_create_session", new=AsyncMock(return_value=mock_session)):
        out = await stata_get_results(session_id="t1", include_mata=True)
    if isinstance(out, ToolEnvelope):
        assert out.success is True
        assert isinstance(out.data, dict)
        payload = out.data
    else:
        payload = json.loads(out)
    assert payload["r"]["N"] == 10
    assert payload["mata"]["success"] is True
    assert payload["mata"]["objects"][0]["name"] == "a"
    assert payload["mata"]["functions"][0]["name"] == "g"
