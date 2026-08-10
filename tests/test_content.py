# tests/test_content.py
import httpx
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.content import (
    do_course_content,
    do_get_page,
    do_get_syllabus,
    do_list_files,
)

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
API = "https://canvas.example.edu/api/v1"


@respx.mock
async def test_course_content_nests_items_under_modules():
    respx.get(f"{API}/courses/101/modules").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "Week 1", "position": 1, "items": [
                {"id": 11, "title": "Lecture 1", "type": "File", "content_id": 501,
                 "html_url": "https://c/11"},
            ]},
        ])
    )
    client = CanvasClient(CFG)
    modules = await do_course_content(client, 101)
    await client.aclose()

    assert modules[0]["name"] == "Week 1"
    assert modules[0]["items"][0] == {
        "id": 11, "title": "Lecture 1", "type": "File",
        "content_id": 501, "page_url": None, "html_url": "https://c/11",
    }


@respx.mock
async def test_course_content_handles_null_items():
    """Canvas serializes items: null (not just an absent key) for modules the
    requesting user cannot fully enumerate; this must not raise TypeError."""
    respx.get(f"{API}/courses/101/modules").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "Restricted Module", "position": 1, "items": None},
        ])
    )
    client = CanvasClient(CFG)
    modules = await do_course_content(client, 101)
    await client.aclose()

    assert modules[0]["name"] == "Restricted Module"
    assert modules[0]["items"] == []


@respx.mock
async def test_course_content_requests_items_inline():
    route = respx.get(f"{API}/courses/101/modules").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    await do_course_content(client, 101)
    await client.aclose()
    assert "items" in route.calls[0].request.url.params.get_list("include[]")


@respx.mock
async def test_list_files_shapes_metadata():
    respx.get(f"{API}/courses/101/files").mock(
        return_value=httpx.Response(200, json=[
            {"id": 501, "display_name": "lec01.pdf", "content-type": "application/pdf",
             "size": 1024, "url": "https://files/501", "updated_at": "2026-08-01T00:00:00Z"},
        ])
    )
    client = CanvasClient(CFG)
    files = await do_list_files(client, 101)
    await client.aclose()

    assert files[0]["display_name"] == "lec01.pdf"
    assert files[0]["content_type"] == "application/pdf"
    assert files[0]["size"] == 1024


@respx.mock
async def test_list_files_passes_search_term():
    route = respx.get(f"{API}/courses/101/files").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    await do_list_files(client, 101, search="tutorial")
    await client.aclose()
    assert route.calls[0].request.url.params["search_term"] == "tutorial"


@respx.mock
async def test_get_page_returns_title_and_body():
    respx.get(f"{API}/courses/101/pages/week-1-overview").mock(
        return_value=httpx.Response(200, json={
            "title": "Week 1", "url": "week-1-overview", "body": "<p>Welcome</p>",
            "updated_at": "2026-08-01T00:00:00Z",
        })
    )
    client = CanvasClient(CFG)
    page = await do_get_page(client, 101, "week-1-overview")
    await client.aclose()

    assert page["title"] == "Week 1"
    assert "Welcome" in page["body"]


@respx.mock
async def test_get_syllabus_requests_and_returns_syllabus_body():
    route = respx.get(f"{API}/courses/101").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 101,
                "name": "Databases",
                "syllabus_body": "<p>Grading: 40/60</p>",
            },
        )
    )
    client = CanvasClient(CFG)
    syllabus = await do_get_syllabus(client, 101)
    await client.aclose()

    assert route.calls[0].request.url.params.get_list("include[]") == [
        "syllabus_body"
    ]
    assert syllabus == {
        "name": "Databases",
        "syllabus_body": "<p>Grading: 40/60</p>",
    }
