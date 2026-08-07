import httpx
import pytest
import respx

from canvas_api_mcp.client import CanvasClient, CanvasError
from canvas_api_mcp.config import Config

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
URL = "https://canvas.example.edu/api/v1/courses"


def make_client():
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    return CanvasClient(CFG, sleep=fake_sleep), slept


@respx.mock
async def test_retries_on_500_then_succeeds():
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(500, text="boom"),
            httpx.Response(200, json=[{"id": 1}]),
        ]
    )
    client, slept = make_client()
    resp = await client.request("GET", "courses")
    await client.aclose()

    assert resp.data == [{"id": 1}]
    assert slept == [0.5]


@respx.mock
async def test_retries_on_429_then_succeeds():
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, text="Rate Limit Exceeded"),
            httpx.Response(200, json=[]),
        ]
    )
    client, slept = make_client()
    await client.request("GET", "courses")
    await client.aclose()
    assert slept == [0.5]


@respx.mock
async def test_gives_up_after_three_attempts():
    respx.get(URL).mock(return_value=httpx.Response(500, text="boom"))
    client, slept = make_client()
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert exc.value.status == 500
    assert slept == [0.5, 1.0]


@respx.mock
async def test_does_not_retry_on_404():
    route = respx.get(URL).mock(return_value=httpx.Response(404, json={}))
    client, slept = make_client()
    with pytest.raises(CanvasError):
        await client.request("GET", "courses")
    await client.aclose()
    assert route.call_count == 1
    assert slept == []


@respx.mock
async def test_throttles_when_quota_is_nearly_exhausted():
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, json=[], headers={"X-Rate-Limit-Remaining": "42.0"}
        )
    )
    client, slept = make_client()
    await client.request("GET", "courses")
    await client.request("GET", "courses")
    await client.aclose()
    # First response reports low quota; the second request pauses first.
    assert 1.0 in slept


@respx.mock
async def test_no_throttle_when_quota_is_healthy():
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, json=[], headers={"X-Rate-Limit-Remaining": "600.0"}
        )
    )
    client, slept = make_client()
    await client.request("GET", "courses")
    await client.request("GET", "courses")
    await client.aclose()
    assert slept == []
