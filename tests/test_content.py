# tests/test_content.py
import httpx
import respx
from fastmcp import Client, FastMCP

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools import content as content_tools
from canvas_api_mcp.tools.content import (
    do_course_content,
    do_get_page,
    do_get_syllabus,
    do_list_files,
)

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
SMALL = Config(base_url="https://canvas.example.edu", token="tok", max_pages=2)
API = "https://canvas.example.edu/api/v1"


def _link(url: str) -> str:
    return f'<{url}>; rel="next"'


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
    result = await do_course_content(client, 101)
    await client.aclose()

    modules = result["modules"]
    assert result["truncated"] is False
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
    result = await do_course_content(client, 101)
    await client.aclose()

    modules = result["modules"]
    assert result["truncated"] is False
    assert modules[0]["name"] == "Restricted Module"
    assert modules[0]["items"] == []


@respx.mock
async def test_course_content_requests_items_inline():
    route = respx.get(f"{API}/courses/101/modules").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    result = await do_course_content(client, 101)
    await client.aclose()
    assert "items" in route.calls[0].request.url.params.get_list("include[]")
    assert result == {"modules": [], "truncated": False}


@respx.mock
async def test_list_files_shapes_metadata():
    respx.get(f"{API}/courses/101/files").mock(
        return_value=httpx.Response(200, json=[
            {"id": 501, "display_name": "lec01.pdf", "content-type": "application/pdf",
             "size": 1024, "url": "https://files/501", "updated_at": "2026-08-01T00:00:00Z"},
        ])
    )
    client = CanvasClient(CFG)
    result = await do_list_files(client, 101)
    await client.aclose()

    files = result["files"]
    assert result["truncated"] is False
    assert files[0]["display_name"] == "lec01.pdf"
    assert files[0]["content_type"] == "application/pdf"
    assert files[0]["size"] == 1024


@respx.mock
async def test_list_files_passes_search_term():
    route = respx.get(f"{API}/courses/101/files").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    result = await do_list_files(client, 101, search="tutorial")
    await client.aclose()
    assert route.calls[0].request.url.params["search_term"] == "tutorial"
    assert result == {"files": [], "truncated": False}


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
    assert syllabus["name"] == "Databases"
    # The body is fenced as untrusted before it reaches the model, so this can no
    # longer be an equality check. The fence itself is asserted in
    # tests/test_safety.py; here we only care that the content survived intact.
    assert "<p>Grading: 40/60</p>" in syllabus["syllabus_body"]
    assert set(syllabus) == {"name", "syllabus_body"}


@respx.mock
async def test_course_content_reports_truncation_when_max_pages_exceeded():
    base = f"{API}/courses/101/modules"
    page3 = respx.get(base, params={"page": "3"}).mock(
        return_value=httpx.Response(
            200, json=[{"id": 3, "name": "Week 3", "position": 3, "items": []}]
        )
    )
    respx.get(base, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 2, "name": "Week 2", "position": 2, "items": []}],
            headers={"Link": _link(f"{base}?page=3")},
        )
    )
    respx.get(base).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "name": "Week 1", "position": 1, "items": []}],
            headers={"Link": _link(f"{base}?page=2")},
        )
    )

    client = CanvasClient(SMALL)
    result = await do_course_content(client, 101)
    await client.aclose()

    assert [m["id"] for m in result["modules"]] == [1, 2]
    assert result["truncated"] is True
    assert not page3.called


@respx.mock
async def test_list_files_reports_truncation_when_max_pages_exceeded():
    base = f"{API}/courses/101/files"
    page3 = respx.get(base, params={"page": "3"}).mock(
        return_value=httpx.Response(
            200, json=[{"id": 503, "display_name": "lec03.pdf"}]
        )
    )
    respx.get(base, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 502, "display_name": "lec02.pdf"}],
            headers={"Link": _link(f"{base}?page=3")},
        )
    )
    respx.get(base).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 501, "display_name": "lec01.pdf"}],
            headers={"Link": _link(f"{base}?page=2")},
        )
    )

    client = CanvasClient(SMALL)
    result = await do_list_files(client, 101)
    await client.aclose()

    assert [f["id"] for f in result["files"]] == [501, 502]
    assert result["truncated"] is True
    assert not page3.called


@respx.mock
async def test_content_mcp_tools_return_truncated_envelope():
    respx.get(f"{API}/courses/101/modules").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1, "name": "Week 1", "position": 1, "items": []}]
        )
    )
    respx.get(f"{API}/courses/101/files").mock(
        return_value=httpx.Response(200, json=[{"id": 501, "display_name": "lec01.pdf"}])
    )

    client = CanvasClient(CFG)
    mcp = FastMCP("test-content")
    content_tools.register(mcp, lambda: client)
    try:
        async with Client(mcp) as mcp_client:
            content_res = await mcp_client.call_tool("course_content", {"course_id": 101})
            files_res = await mcp_client.call_tool("list_files", {"course_id": 101})
    finally:
        await client.aclose()

    assert content_res.is_error is False
    assert [m["id"] for m in content_res.data["modules"]] == [1]
    assert content_res.data["truncated"] is False

    assert files_res.is_error is False
    assert [f["id"] for f in files_res.data["files"]] == [501]
    assert files_res.data["truncated"] is False
