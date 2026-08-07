# tests/test_whats_due.py
import httpx
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.student import do_whats_due

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)

TODO = [
    {
        "type": "submitting",
        "assignment": {
            "id": 1, "name": "Problem Set 3", "due_at": "2026-08-12T15:59:00Z",
            "course_id": 101, "html_url": "https://c/1",
        },
    }
]
UPCOMING = [
    {
        "id": "assignment_1",
        "title": "Problem Set 3",
        "type": "assignment",
        "assignment": {"id": 1, "due_at": "2026-08-12T15:59:00Z", "course_id": 101},
        "html_url": "https://c/1",
    },
    {
        "id": "event_9",
        "title": "Lab Session",
        "type": "event",
        "start_at": "2026-08-09T02:00:00Z",
        "context_code": "course_101",
        "html_url": "https://c/9",
    },
]


def _mock_all(todo=None, upcoming=None):
    respx.get("https://canvas.example.edu/api/v1/users/self/todo").mock(
        return_value=httpx.Response(200, json=todo if todo is not None else TODO)
    )
    respx.get("https://canvas.example.edu/api/v1/users/self/upcoming_events").mock(
        return_value=httpx.Response(200, json=upcoming if upcoming is not None else UPCOMING)
    )


@respx.mock
async def test_merges_both_sources_and_sorts_by_due_date():
    _mock_all()
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    titles = [i["title"] for i in result["items"]]
    assert titles == ["Lab Session", "Problem Set 3"]


@respx.mock
async def test_deduplicates_the_same_assignment_from_both_sources():
    _mock_all()
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    assert sum(1 for i in result["items"] if i["title"] == "Problem Set 3") == 1


@respx.mock
async def test_items_carry_course_id_and_url():
    _mock_all()
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    ps3 = next(i for i in result["items"] if i["title"] == "Problem Set 3")
    assert ps3["course_id"] == 101
    assert ps3["html_url"] == "https://c/1"
    assert ps3["due_at"] == "2026-08-12T15:59:00Z"


@respx.mock
async def test_empty_sources_return_empty_list_not_error():
    _mock_all(todo=[], upcoming=[])
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    assert result["items"] == []


@respx.mock
async def test_one_source_failing_still_returns_the_other():
    respx.get("https://canvas.example.edu/api/v1/users/self/todo").mock(
        return_value=httpx.Response(403, json={"status": "unauthorized"})
    )
    respx.get("https://canvas.example.edu/api/v1/users/self/upcoming_events").mock(
        return_value=httpx.Response(200, json=UPCOMING)
    )
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    assert len(result["items"]) == 2
    assert "todo" in " ".join(result["warnings"]).lower()
