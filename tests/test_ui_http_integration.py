import json
from urllib.parse import urljoin

import anyio
import httpx
import pytest

from mcp_stata.server import get_ui_channel, run_command


pytestmark = [pytest.mark.requires_stata, pytest.mark.integration]


def _run_command_sync(code: str) -> str:
    async def _main() -> str:
        return await run_command(code)

    return anyio.run(_main)


def test_ui_http_auth_and_basic_endpoints():
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]

    # 401 when missing token
    r = httpx.get(urljoin(base, "/v1/dataset"))
    assert r.status_code == 401

    headers = {"Authorization": f"Bearer {token}"}

    r2 = httpx.get(urljoin(base, "/v1/dataset"), headers=headers)
    assert r2.status_code == 200
    payload = r2.json()
    assert payload["dataset"]["n"] > 0
    assert payload["dataset"]["k"] > 0

    r3 = httpx.get(urljoin(base, "/v1/vars"), headers=headers)
    assert r3.status_code == 200
    vars_payload = r3.json()
    names = {v["name"] for v in vars_payload["variables"]}
    assert "price" in names


def test_ui_http_paging_and_views_filtering():
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    page_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 20,
        "vars": ["price", "mpg", "make"],
        "includeObsNo": True,
        "maxChars": 200,
    }

    page = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req).json()
    assert page["view"]["returned"] == 20
    assert page["vars"][0] == "_n"
    assert len(page["rows"]) == 20

    view_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "filterExpr": "foreign == 1",
    }
    view = httpx.post(urljoin(base, "/v1/views"), headers=headers, json=view_req)
    assert view.status_code == 200
    view_payload = view.json()
    view_id = view_payload["view"]["id"]
    assert view_payload["view"]["filteredN"] < ds["n"]

    view_page_req = {
        "offset": 0,
        "limit": 10,
        "vars": ["price", "foreign"],
        "includeObsNo": True,
        "maxChars": 200,
    }
    vpage = httpx.post(urljoin(base, f"/v1/views/{view_id}/page"), headers=headers, json=view_page_req)
    assert vpage.status_code == 200
    vpayload = vpage.json()
    assert vpayload["view"].get("viewId") == view_id
    assert vpayload["view"].get("filteredN") is not None

    # Ensure filter applied: foreign column should be 1 or "1" depending on storage.
    foreign_idx = vpayload["vars"].index("foreign")
    for row in vpayload["rows"]:
        val = row[foreign_idx]
        assert str(val) in {"1", "1.0"}

    # Cleanup
    d = httpx.delete(urljoin(base, f"/v1/views/{view_id}"), headers=headers)
    assert d.status_code == 200
