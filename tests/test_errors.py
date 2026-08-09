import httpx
import pytest
import respx

from canvas_api_mcp.client import CanvasClient, CanvasError
from canvas_api_mcp.config import Config

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
URL = "https://canvas.example.edu/api/v1/courses"


@respx.mock
async def test_401_explains_token_problem():
    respx.get(URL).mock(return_value=httpx.Response(401, json={"errors": [{"message": "user authorisation required"}]}))
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert exc.value.status == 401
    assert "token" in str(exc.value).lower()
    assert "New access token" in str(exc.value)


@respx.mock
async def test_permission_403_is_not_confused_with_rate_limit():
    respx.get(URL).mock(return_value=httpx.Response(403, json={"status": "unauthorized"}))
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert exc.value.status == 403
    assert "permission" in str(exc.value).lower()
    assert "rate limit" not in str(exc.value).lower()


@respx.mock
async def test_rate_limit_403_is_identified_by_body():
    respx.get(URL).mock(return_value=httpx.Response(403, text="403 Forbidden (Rate Limit Exceeded)"))
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert "rate limit" in str(exc.value).lower()


@respx.mock
async def test_404_mentions_visibility_and_feature_availability():
    respx.get(URL).mock(return_value=httpx.Response(404, json={"errors": [{"message": "The specified resource does not exist."}]}))
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert exc.value.status == 404
    message = str(exc.value).lower()
    assert "visible" in message or "enabled" in message


@respx.mock
async def test_500_reports_server_side_failure():
    respx.get(URL).mock(return_value=httpx.Response(500, text="boom"))
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert exc.value.status == 500


@respx.mock
async def test_connect_error_is_translated_to_actionable_canvas_error():
    """A bad/unreachable CANVAS_BASE_URL raises httpx.ConnectError, which is
    httpx.HTTPError but NOT httpx.HTTPStatusError. _raise_for_status never
    sees it. It must still come out as a CanvasError a student can act on."""
    respx.get(URL).mock(
        side_effect=httpx.ConnectError(
            "[Errno 8] nodename nor servname provided, or not known"
        )
    )
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert exc.value.status == 0
    assert "CANVAS_BASE_URL" in str(exc.value)
    assert CFG.base_url in str(exc.value)
