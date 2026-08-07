import httpx
import pytest
import respx

from canvas_api_mcp.client import CanvasClient, CanvasError
from canvas_api_mcp.config import Config

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)


@respx.mock
async def test_get_sends_bearer_token_and_returns_data():
    route = respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "CS3230"}])
    )
    client = CanvasClient(CFG)
    resp = await client.request("GET", "courses")
    await client.aclose()

    assert resp.data == [{"id": 1, "name": "CS3230"}]
    assert resp.pages_fetched == 1
    assert resp.truncated is False
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok"


@respx.mock
@pytest.mark.parametrize(
    "given",
    ["courses", "/courses", "/v1/courses", "/api/v1/courses"],
)
async def test_path_forms_all_resolve_to_the_same_url(given):
    route = respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    await client.request("GET", given)
    await client.aclose()
    assert route.called


@respx.mock
async def test_query_params_are_passed_through():
    route = respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    await client.request("GET", "courses", params={"enrollment_state": "active"})
    await client.aclose()
    assert route.calls[0].request.url.params["enrollment_state"] == "active"


@respx.mock
async def test_non_json_response_raises_canvas_error():
    respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, text="<html>login</html>")
    )
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert "not valid JSON" in str(exc.value)
