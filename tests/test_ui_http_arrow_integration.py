import json
from urllib.parse import urljoin
import io

import anyio
import httpx
import pytest
import pyarrow as pa

from mcp_stata.server import get_ui_channel, run_command

pytestmark = [pytest.mark.requires_stata, pytest.mark.integration]

def _run_command_sync(code: str) -> str:
    async def _main() -> str:
        return await run_command(code)
    return anyio.run(_main)

def test_ui_http_arrow_basic():
    """Verify that /v1/arrow returns a valid Arrow stream with expected data"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Get dataset info to get the ID
    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    arrow_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 10,
        "vars": ["price", "mpg", "make"],
        "includeObsNo": True
    }

    # Request the arrow stream
    r = httpx.post(urljoin(base, "/v1/arrow"), headers=headers, json=arrow_req)
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "application/vnd.apache.arrow.stream"
    
    # Binary body
    data_bytes = r.content
    assert len(data_bytes) > 0
    
    # Parse with pyarrow
    with pa.ipc.open_stream(io.BytesIO(data_bytes)) as reader:
        table = reader.read_all()
    
    assert table.num_rows == 10
    assert "_n" in table.column_names
    assert "price" in table.column_names
    assert "mpg" in table.column_names
    assert "make" in table.column_names
    
    # Verify some values (auto.dta first row is AMC Concord, price 4099, mpg 22)
    # price and mpg are likely float64 or int64 in Arrow
    assert table["price"][0].as_py() == 4099
    assert table["mpg"][0].as_py() == 22
    assert table["_n"][0].as_py() == 1

def test_ui_http_arrow_sorting():
    """Verify that /v1/arrow respects the sortBy parameter"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Sort DESCENDING by price
    arrow_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 5,
        "vars": ["price"],
        "sortBy": ["-price"]
    }

    r = httpx.post(urljoin(base, "/v1/arrow"), headers=headers, json=arrow_req)
    assert r.status_code == 200
    
    with pa.ipc.open_stream(io.BytesIO(r.content)) as reader:
        table = reader.read_all()
    
    prices = table["price"].to_pylist()
    assert len(prices) == 5
    # Verify they are descending
    for i in range(1, len(prices)):
        assert prices[i] <= prices[i-1]

def test_ui_http_arrow_large_limit():
    """Verify that /v1/arrow supports much larger limits than /v1/page"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Limit of 1000 (auto only has 74, but this verifies it doesn't fail due to UI_LIMIT=500)
    arrow_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 1000,
        "vars": ["price"]
    }

    r = httpx.post(urljoin(base, "/v1/arrow"), headers=headers, json=arrow_req)
    assert r.status_code == 200
    
    with pa.ipc.open_stream(io.BytesIO(r.content)) as reader:
        table = reader.read_all()
    
    assert table.num_rows == 74 # Full auto dataset

def test_ui_http_arrow_with_view():
    """Verify that /v1/arrow works within a filtered view"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Create a view for foreign cars
    view_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "filterExpr": "foreign == 1"
    }
    view_resp = httpx.post(urljoin(base, "/v1/views"), headers=headers, json=view_req)
    view_id = view_resp.json()["view"]["id"]
    filtered_n = view_resp.json()["view"]["filteredN"]

    # Request arrow from this view
    arrow_req = {
        "offset": 0,
        "limit": 50,
        "vars": ["price", "foreign"]
    }
    r = httpx.post(urljoin(base, f"/v1/views/{view_id}/arrow"), headers=headers, json=arrow_req)
    assert r.status_code == 200
    
    with pa.ipc.open_stream(io.BytesIO(r.content)) as reader:
        table = reader.read_all()
    
    assert table.num_rows == filtered_n
    # foreign should be 1 for all
    for val in table["foreign"].to_pylist():
        assert val == 1

