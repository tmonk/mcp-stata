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
        "limit": 100_000,
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


def test_ui_http_filter_price_less_than_5000():
    """Test that filtering for price < 5000 returns only rows where price < 5000"""
    # Load the auto dataset
    _run_command_sync("sysuse auto, clear")

    # Sort by price to make verification easier
    _run_command_sync("sort price")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Get dataset info
    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Create a view with filter: price < 5000
    view_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "filterExpr": "price < 5000",
    }
    view_resp = httpx.post(urljoin(base, "/v1/views"), headers=headers, json=view_req)
    assert view_resp.status_code == 200, f"Failed to create view: {view_resp.text}"

    view_payload = view_resp.json()
    view_id = view_payload["view"]["id"]
    filtered_n = view_payload["view"]["filteredN"]

    # The filtered count should be less than the total dataset
    assert filtered_n < ds["n"], f"Filtered count ({filtered_n}) should be less than total ({ds['n']})"
    assert filtered_n > 0, "Should have some rows with price < 5000"

    # Request all filtered rows with price variable
    page_req = {
        "offset": 0,
        "limit": 100,  # Get all rows
        "vars": ["price", "make"],
        "includeObsNo": True,
    }

    page_resp = httpx.post(urljoin(base, f"/v1/views/{view_id}/page"), headers=headers, json=page_req)
    assert page_resp.status_code == 200, f"Failed to get page: {page_resp.text}"

    page_data = page_resp.json()

    # Verify we got the expected number of rows
    assert page_data["view"]["returned"] == filtered_n, \
        f"Should return {filtered_n} rows, got {page_data['view']['returned']}"

    # Find the price column index
    vars_list = page_data["vars"]
    assert "price" in vars_list, "price should be in the returned variables"
    price_idx = vars_list.index("price")

    # Verify all returned rows have price < 5000
    rows = page_data["rows"]
    assert len(rows) == filtered_n, f"Should have {filtered_n} rows, got {len(rows)}"

    prices = []
    for i, row in enumerate(rows):
        price_value = row[price_idx]
        # Convert to float for comparison (might be string representation)
        try:
            price = float(price_value)
        except (ValueError, TypeError):
            # Handle missing values
            if price_value == "." or price_value is None:
                continue
            raise AssertionError(f"Row {i}: Invalid price value: {price_value!r}")

        prices.append(price)
        assert price < 5000, \
            f"Row {i}: price should be < 5000, got {price} (row data: {row})"

    # Verify we found at least some prices
    assert len(prices) > 0, "Should have found at least some non-missing prices"

    # Verify the data is sorted (since we sorted the dataset by price)
    # Note: The view should preserve the sort order
    for i in range(1, len(prices)):
        assert prices[i] >= prices[i-1], \
            f"Prices should be sorted: position {i-1} has {prices[i-1]}, position {i} has {prices[i]}"

    # Additional verification: fetch a page without the filter and ensure we have rows with price >= 5000
    unfiltered_page_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 100,
        "vars": ["price"],
    }

    unfiltered_resp = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=unfiltered_page_req)
    assert unfiltered_resp.status_code == 200

    unfiltered_data = unfiltered_resp.json()
    unfiltered_price_idx = unfiltered_data["vars"].index("price")

    # Check that the unfiltered dataset has at least some prices >= 5000
    has_expensive_cars = False
    for row in unfiltered_data["rows"]:
        price_value = row[unfiltered_price_idx]
        try:
            price = float(price_value)
            if price >= 5000:
                has_expensive_cars = True
                break
        except (ValueError, TypeError):
            continue

    assert has_expensive_cars, \
        "The full dataset should contain at least some cars with price >= 5000 to validate the filter is working"

    # Cleanup
    delete_resp = httpx.delete(urljoin(base, f"/v1/views/{view_id}"), headers=headers)
    assert delete_resp.status_code == 200

    print(f"✓ Filter test passed: {filtered_n} rows with price < 5000, all verified")
    print(f"✓ Price range in filtered data: {min(prices):.2f} to {max(prices):.2f}")


def test_ui_http_sorting_ascending():
    """Test sorting by a single variable in ascending order"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Request page sorted by price ascending
    page_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 10,
        "vars": ["price", "make"],
        "sortBy": ["price"],  # or ["+price"]
    }

    resp = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req)
    assert resp.status_code == 200, f"Failed: {resp.text}"

    data = resp.json()
    price_idx = data["vars"].index("price")
    prices = [float(row[price_idx]) for row in data["rows"]]

    # Verify prices are in ascending order
    for i in range(1, len(prices)):
        assert prices[i] >= prices[i-1], \
            f"Prices should be ascending: {prices[i-1]} > {prices[i]}"

    print(f"✓ Ascending sort test passed. Prices: {prices[0]:.0f} to {prices[-1]:.0f}")


def test_ui_http_sorting_descending():
    """Test sorting by a single variable in descending order"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Request page sorted by price descending
    page_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 10,
        "vars": ["price", "make"],
        "sortBy": ["-price"],
    }

    resp = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req)
    assert resp.status_code == 200, f"Failed: {resp.text}"

    data = resp.json()
    price_idx = data["vars"].index("price")
    prices = [float(row[price_idx]) for row in data["rows"]]

    # Verify prices are in descending order
    for i in range(1, len(prices)):
        assert prices[i] <= prices[i-1], \
            f"Prices should be descending: {prices[i-1]} < {prices[i]}"

    print(f"✓ Descending sort test passed. Prices: {prices[0]:.0f} to {prices[-1]:.0f}")


def test_ui_http_sorting_multiple_variables():
    """Test sorting by multiple variables"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Sort by foreign (ascending), then price (descending)
    page_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 74,  # Get all rows
        "vars": ["foreign", "price", "make"],
        "sortBy": ["foreign", "-price"],
    }

    resp = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req)
    assert resp.status_code == 200, f"Failed: {resp.text}"

    data = resp.json()
    foreign_idx = data["vars"].index("foreign")
    price_idx = data["vars"].index("price")

    # Extract foreign and price values
    rows_data = [(float(row[foreign_idx]), float(row[price_idx])) for row in data["rows"]]

    # Verify primary sort by foreign (ascending)
    for i in range(1, len(rows_data)):
        # If foreign values are different, current should be >= previous
        if rows_data[i][0] != rows_data[i-1][0]:
            assert rows_data[i][0] >= rows_data[i-1][0], \
                f"Foreign should be ascending: {rows_data[i-1][0]} > {rows_data[i][0]}"
        # If foreign values are the same, check price (descending)
        else:
            assert rows_data[i][1] <= rows_data[i-1][1], \
                f"Within same foreign group, price should be descending: {rows_data[i-1][1]} < {rows_data[i][1]}"

    print(f"✓ Multi-variable sort test passed")


def test_ui_http_sorting_with_filter():
    """Test that sorting works correctly with filtered views"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Create a filtered view for price < 5000
    view_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "filterExpr": "price < 5000",
    }
    view_resp = httpx.post(urljoin(base, "/v1/views"), headers=headers, json=view_req)
    assert view_resp.status_code == 200
    view_id = view_resp.json()["view"]["id"]

    # Request sorted page from filtered view
    page_req = {
        "offset": 0,
        "limit": 50,
        "vars": ["price", "make"],
        "sortBy": ["-price"],  # Sort descending
    }

    resp = httpx.post(urljoin(base, f"/v1/views/{view_id}/page"), headers=headers, json=page_req)
    assert resp.status_code == 200, f"Failed: {resp.text}"

    data = resp.json()
    price_idx = data["vars"].index("price")
    prices = [float(row[price_idx]) for row in data["rows"]]

    # Verify all prices are < 5000 (filter still applied)
    for price in prices:
        assert price < 5000, f"All prices should be < 5000, got {price}"

    # Verify prices are in descending order (sort applied)
    for i in range(1, len(prices)):
        assert prices[i] <= prices[i-1], \
            f"Prices should be descending: {prices[i-1]} < {prices[i]}"

    # Cleanup
    httpx.delete(urljoin(base, f"/v1/views/{view_id}"), headers=headers)

    print(f"✓ Sort with filter test passed. Filtered & sorted {len(prices)} rows, range: ${prices[-1]:.0f} to ${prices[0]:.0f}")


def test_ui_http_sorting_invalid_variable():
    """Test that sorting with invalid variable returns proper error"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Request with invalid sort variable
    page_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 10,
        "vars": ["price"],
        "sortBy": ["nonexistent_variable"],
    }

    resp = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req)
    assert resp.status_code == 400
    assert "invalid" in resp.json()["error"]["message"].lower()

    print("✓ Invalid variable test passed")


def test_ui_http_sorting_invalid_format():
    """Test that invalid sortBy format returns proper error"""
    _run_command_sync("sysuse auto, clear")

    info = json.loads(get_ui_channel())
    base = info["baseUrl"]
    token = info["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ds = httpx.get(urljoin(base, "/v1/dataset"), headers=headers).json()["dataset"]

    # Request with invalid sortBy format (not an array)
    page_req = {
        "datasetId": ds["id"],
        "frame": ds.get("frame", "default"),
        "offset": 0,
        "limit": 10,
        "vars": ["price"],
        "sortBy": "price",  # Should be an array
    }

    resp = httpx.post(urljoin(base, "/v1/page"), headers=headers, json=page_req)
    assert resp.status_code == 400
    assert "array" in resp.json()["error"]["message"].lower()

    print("✓ Invalid format test passed")
