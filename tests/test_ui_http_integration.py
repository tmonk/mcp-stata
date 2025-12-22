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


def test_ui_http_page_limit_validation():
    """Test that limit parameter is properly validated"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Test missing limit - should fail
    page_req_no_limit = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_no_limit)
    assert r.status_code == 400
    assert "limit is required" in r.json()["error"]["message"]

    # Test limit = 0 - should fail
    page_req_zero = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 0,
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_zero)
    assert r.status_code == 400
    assert "limit must be > 0" in r.json()["error"]["message"]

    # Test limit = -1 - should fail
    page_req_negative = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": -1,
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_negative)
    assert r.status_code == 400
    assert "limit must be > 0" in r.json()["error"]["message"]

    # Test limit = null - should fail with "limit is required"
    page_req_null = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": None,
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_null)
    assert r.status_code == 400
    assert "limit is required" in r.json()["error"]["message"]

    # Test limit as string - should fail with type error
    page_req_string = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": "not a number",
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_string)
    assert r.status_code == 400
    assert "must be a valid integer" in r.json()["error"]["message"]

    # Test limit = 1 - should succeed
    page_req_valid = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 1,
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_valid)
    assert r.status_code == 200
    assert r.json()["view"]["returned"] == 1

    # Test limit = 100 - should succeed
    page_req_100 = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 100,
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_100)
    assert r.status_code == 200
    # auto dataset has 74 observations, so should return all of them
    assert r.json()["view"]["returned"] <= 100

    # Test limit exceeds max_limit (default 500) - should fail
    page_req_too_large = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 1000,
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_too_large)
    assert r.status_code == 400
    assert "limit must be <=" in r.json()["error"]["message"]


def test_ui_http_page_offset_validation():
    """Test that offset parameter is properly validated"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Test offset = -1 - should fail
    page_req_negative_offset = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": -1,
        "limit": 10,
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_negative_offset)
    assert r.status_code == 400
    assert "offset must be >=" in r.json()["error"]["message"]

    # Test offset = 0 - should succeed (default)
    page_req_zero_offset = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 10,
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_zero_offset)
    assert r.status_code == 200

    # Test offset missing - should default to 0 and succeed
    page_req_no_offset = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "limit": 10,
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_no_offset)
    assert r.status_code == 200
    assert r.json()["view"]["offset"] == 0

    # Test offset as invalid string - should fail
    page_req_invalid_offset = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": "not a number",
        "limit": 10,
        "vars": ["price"],
    }
    r = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req_invalid_offset)
    assert r.status_code == 400
    assert "offset must be a valid integer" in r.json()["error"]["message"]
