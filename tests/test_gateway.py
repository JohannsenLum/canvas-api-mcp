import httpx
import pytest
import respx

from canvas_api_mcp.client import CanvasClient, CanvasError
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.gateway import do_request, do_search

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)


async def test_do_search_finds_the_todo_endpoint():
    results = await do_search("what is due todo items")
    assert any(r["path"] == "/v1/users/self/todo" for r in results)


async def test_do_search_respects_method_filter():
    results = await do_search("courses", method="POST", limit=5)
    assert all(r["method"] == "POST" for r in results)


async def test_dry_run_does_not_send_a_request():
    with respx.mock:
        route = respx.get("https://canvas.example.edu/api/v1/courses").mock(
            return_value=httpx.Response(200, json=[])
        )
        client = CanvasClient(CFG)
        result = await do_request(client, "GET", "courses", dry_run=True)
        await client.aclose()

    assert route.called is False
    assert result["dry_run"] is True
    assert result["method"] == "GET"
    assert result["url"] == "https://canvas.example.edu/api/v1/courses"


@respx.mock
async def test_request_executes_and_reports_truncation():
    respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[{"id": 1}])
    )
    client = CanvasClient(CFG)
    result = await do_request(client, "GET", "courses")
    await client.aclose()

    assert result["data"] == [{"id": 1}]
    assert result["truncated"] is False


@respx.mock
async def test_request_surfaces_canvas_error_as_structured_result():
    respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(403, json={"status": "unauthorized"})
    )
    client = CanvasClient(CFG)
    result = await do_request(client, "GET", "courses")
    await client.aclose()

    assert result["error"] is True
    assert result["status"] == 403
    assert "permission" in result["message"].lower()


async def test_rejects_unknown_http_method():
    client = CanvasClient(CFG)
    result = await do_request(client, "FETCH", "courses")
    await client.aclose()
    assert result["error"] is True
    assert "method" in result["message"].lower()
