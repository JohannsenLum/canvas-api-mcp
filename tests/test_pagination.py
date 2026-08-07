import httpx
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
SMALL = Config(base_url="https://canvas.example.edu", token="tok", max_pages=2)
BASE = "https://canvas.example.edu/api/v1/courses"


def _link(url: str) -> str:
    return f'<{url}>; rel="next"'


@respx.mock
async def test_follows_next_links_and_merges_lists():
    respx.get(BASE, params={"page": "1"}).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}], headers={"Link": _link(f"{BASE}?page=2")}
        )
    )
    respx.get(BASE, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200, json=[{"id": 2}], headers={"Link": _link(f"{BASE}?page=3")}
        )
    )
    respx.get(BASE, params={"page": "3"}).mock(
        return_value=httpx.Response(200, json=[{"id": 3}])
    )

    client = CanvasClient(CFG)
    resp = await client.request("GET", "courses", params={"page": "1"})
    await client.aclose()

    assert resp.data == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert resp.pages_fetched == 3
    assert resp.truncated is False


@respx.mock
async def test_stops_at_max_pages_and_flags_truncation():
    respx.get(BASE, params={"page": "1"}).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}], headers={"Link": _link(f"{BASE}?page=2")}
        )
    )
    respx.get(BASE, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200, json=[{"id": 2}], headers={"Link": _link(f"{BASE}?page=3")}
        )
    )

    client = CanvasClient(SMALL)
    resp = await client.request("GET", "courses", params={"page": "1"})
    await client.aclose()

    assert resp.data == [{"id": 1}, {"id": 2}]
    assert resp.pages_fetched == 2
    assert resp.truncated is True


@respx.mock
async def test_dict_response_is_not_paginated():
    respx.get("https://canvas.example.edu/api/v1/users/self").mock(
        return_value=httpx.Response(
            200,
            json={"id": 9},
            headers={"Link": _link(f"{BASE}?page=2")},
        )
    )
    client = CanvasClient(CFG)
    resp = await client.request("GET", "users/self")
    await client.aclose()

    assert resp.data == {"id": 9}
    assert resp.pages_fetched == 1
    assert resp.truncated is False


@respx.mock
async def test_paginate_false_returns_first_page_only():
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}], headers={"Link": _link(f"{BASE}?page=2")}
        )
    )
    client = CanvasClient(CFG)
    resp = await client.request("GET", "courses", paginate=False)
    await client.aclose()

    assert resp.data == [{"id": 1}]
    assert resp.pages_fetched == 1
