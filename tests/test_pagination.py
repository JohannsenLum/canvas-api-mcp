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


# --- Link-header origin validation -------------------------------------------
# The Link header is chosen by the server, and httpx attaches the Authorization
# header to every request the client sends. Following an off-origin "next" would
# therefore leak the user's Canvas token to that host.


@respx.mock
async def test_does_not_follow_next_link_to_a_foreign_host():
    evil = respx.get("https://evil.attacker.example/steal").mock(
        return_value=httpx.Response(200, json=[{"id": 2}])
    )
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"Link": _link("https://evil.attacker.example/steal")},
        )
    )

    client = CanvasClient(CFG)
    resp = await client.request("GET", "courses")
    await client.aclose()

    assert not evil.called, "token would have been sent to a third-party host"
    assert resp.data == [{"id": 1}]
    assert resp.pages_fetched == 1
    assert resp.truncated is True


@respx.mock
async def test_does_not_follow_next_link_to_a_different_port():
    other = respx.get("https://canvas.example.edu:8443/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[{"id": 2}])
    )
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"Link": _link("https://canvas.example.edu:8443/api/v1/courses")},
        )
    )

    client = CanvasClient(CFG)
    resp = await client.request("GET", "courses")
    await client.aclose()

    assert not other.called
    assert resp.truncated is True


@respx.mock
async def test_does_not_follow_next_link_downgraded_to_http():
    plain = respx.get("http://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[{"id": 2}])
    )
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"Link": _link("http://canvas.example.edu/api/v1/courses")},
        )
    )

    client = CanvasClient(CFG)
    resp = await client.request("GET", "courses")
    await client.aclose()

    assert not plain.called, "token would have been sent over cleartext"
    assert resp.truncated is True


@respx.mock
async def test_still_follows_a_relative_next_link():
    respx.get(BASE, params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[{"id": 2}])
    )
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}], headers={"Link": _link("/api/v1/courses?page=2")}
        )
    )

    client = CanvasClient(CFG)
    resp = await client.request("GET", "courses")
    await client.aclose()

    assert resp.data == [{"id": 1}, {"id": 2}]
    assert resp.truncated is False


@respx.mock
async def test_host_comparison_is_case_insensitive():
    respx.get(BASE, params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[{"id": 2}])
    )
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"Link": _link("https://CANVAS.example.edu/api/v1/courses?page=2")},
        )
    )

    client = CanvasClient(CFG)
    resp = await client.request("GET", "courses")
    await client.aclose()

    assert resp.data == [{"id": 1}, {"id": 2}]
    assert resp.truncated is False
