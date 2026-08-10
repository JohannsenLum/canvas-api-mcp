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


PLANNER = [
    {
        "context_type": "Course",
        "course_id": 101,
        "plannable_type": "planner_note",
        "plannable_id": 55,
        "plannable": {"id": 55, "title": "Read Chapter 4"},
        "plannable_date": "2026-08-10T09:00:00Z",
        "context_name": "Algorithms",
        "html_url": "https://c/55",
        "submissions": False,
    }
]


def _mock_all(todo=None, upcoming=None, planner=None):
    respx.get("https://canvas.example.edu/api/v1/users/self/todo").mock(
        return_value=httpx.Response(200, json=todo if todo is not None else TODO)
    )
    respx.get("https://canvas.example.edu/api/v1/users/self/upcoming_events").mock(
        return_value=httpx.Response(200, json=upcoming if upcoming is not None else UPCOMING)
    )
    respx.get("https://canvas.example.edu/api/v1/planner/items").mock(
        return_value=httpx.Response(200, json=planner if planner is not None else [])
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
    respx.get("https://canvas.example.edu/api/v1/planner/items").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    assert len(result["items"]) == 2
    assert "todo" in " ".join(result["warnings"]).lower()


@respx.mock
async def test_one_source_network_error_still_returns_the_others():
    """A transport-level failure (timeout, connection refused, ...) on one
    source must degrade gracefully, exactly like an HTTP-status failure does."""
    respx.get("https://canvas.example.edu/api/v1/users/self/todo").mock(
        side_effect=httpx.ReadTimeout("timed out")
    )
    respx.get("https://canvas.example.edu/api/v1/users/self/upcoming_events").mock(
        return_value=httpx.Response(200, json=UPCOMING)
    )
    respx.get("https://canvas.example.edu/api/v1/planner/items").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    assert len(result["items"]) == 2
    assert "todo" in " ".join(result["warnings"]).lower()


@respx.mock
async def test_all_sources_failing_is_not_reported_as_nothing_due():
    """If Canvas is completely unreachable, `items: []` would read as 'nothing
    due' to a model relaying it: a false negative, not a visible error. All
    three sources failing must produce a distinct, unmissable signal."""
    for path in (
        "https://canvas.example.edu/api/v1/users/self/todo",
        "https://canvas.example.edu/api/v1/users/self/upcoming_events",
        "https://canvas.example.edu/api/v1/planner/items",
    ):
        respx.get(path).mock(
            side_effect=httpx.ConnectError(
                "[Errno 8] nodename nor servname provided, or not known"
            )
        )

    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    assert result.get("error") is True
    assert "items" not in result
    assert len(result["warnings"]) == 3


@respx.mock
async def test_planner_only_items_are_merged_in():
    """An item that only exists in /planner/items (e.g. a planner note) must
    still surface, even though it is absent from /todo and /upcoming_events."""
    _mock_all(planner=PLANNER)
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    titles = [i["title"] for i in result["items"]]
    assert "Read Chapter 4" in titles
    note = next(i for i in result["items"] if i["title"] == "Read Chapter 4")
    assert note["course_id"] == 101
    assert note["due_at"] == "2026-08-10T09:00:00Z"


@respx.mock
async def test_planner_assignment_dedupes_against_todo():
    """A planner item for the same assignment already seen via /todo must not
    produce a duplicate entry."""
    planner_dupe = [
        {
            "context_type": "Course",
            "course_id": 101,
            "plannable_type": "assignment",
            "plannable_id": 1,
            "plannable": {"id": 1, "title": "Problem Set 3"},
            "plannable_date": "2026-08-12T15:59:00Z",
            "context_name": "Algorithms",
            "html_url": "https://c/1",
            "submissions": False,
        }
    ]
    _mock_all(planner=planner_dupe)
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    assert sum(1 for i in result["items"] if i["title"] == "Problem Set 3") == 1


# --- the `days` horizon (issue #11) --------------------------------------------
# whats_due accepted `days`, echoed it back, and filtered nothing. Canvas applies
# its own horizons to /todo, /upcoming_events and /planner/items, and they neither
# agree with each other nor with what the caller asked for.


def _todo(name, due, ident):
    return {
        "type": "submitting",
        "assignment": {
            "id": ident, "name": name, "due_at": due,
            "course_id": 101, "html_url": f"https://c/{ident}",
        },
    }


@respx.mock
async def test_days_horizon_excludes_items_beyond_it():
    respx.get("https://canvas.example.edu/api/v1/users/self/todo").mock(
        return_value=httpx.Response(200, json=[
            _todo("Due tomorrow", "2026-08-09T00:00:00Z", 1),
            _todo("Far future", "2027-08-08T00:00:00Z", 2),
        ])
    )
    respx.get("https://canvas.example.edu/api/v1/users/self/upcoming_events").mock(
        return_value=httpx.Response(200, json=[]))
    respx.get("https://canvas.example.edu/api/v1/planner/items").mock(
        return_value=httpx.Response(200, json=[]))

    client = CanvasClient(CFG)
    result = await do_whats_due(client, days=1)
    await client.aclose()

    titles = [i["title"] for i in result["items"]]
    assert "Far future" not in titles, "an item a year out must not appear in a 1-day horizon"


@respx.mock
async def test_wide_horizon_keeps_distant_items():
    respx.get("https://canvas.example.edu/api/v1/users/self/todo").mock(
        return_value=httpx.Response(200, json=[
            _todo("Far future", "2027-08-08T00:00:00Z", 2),
        ])
    )
    respx.get("https://canvas.example.edu/api/v1/users/self/upcoming_events").mock(
        return_value=httpx.Response(200, json=[]))
    respx.get("https://canvas.example.edu/api/v1/planner/items").mock(
        return_value=httpx.Response(200, json=[]))

    client = CanvasClient(CFG)
    result = await do_whats_due(client, days=400)
    await client.aclose()

    assert [i["title"] for i in result["items"]] == ["Far future"]


@respx.mock
async def test_undated_work_survives_any_horizon():
    """A to-do with no due date is still outstanding: filtering it out would hide
    real work. It is kept and flagged so callers can tell it apart."""
    respx.get("https://canvas.example.edu/api/v1/users/self/todo").mock(
        return_value=httpx.Response(200, json=[_todo("No due date", None, 3)]))
    respx.get("https://canvas.example.edu/api/v1/users/self/upcoming_events").mock(
        return_value=httpx.Response(200, json=[]))
    respx.get("https://canvas.example.edu/api/v1/planner/items").mock(
        return_value=httpx.Response(200, json=[]))

    client = CanvasClient(CFG)
    result = await do_whats_due(client, days=1)
    await client.aclose()

    assert [i["title"] for i in result["items"]] == ["No due date"]
    assert result["items"][0]["undated"] is True


@respx.mock
async def test_malformed_due_date_does_not_crash():
    respx.get("https://canvas.example.edu/api/v1/users/self/todo").mock(
        return_value=httpx.Response(200, json=[_todo("Broken date", "not-a-date", 4)]))
    respx.get("https://canvas.example.edu/api/v1/users/self/upcoming_events").mock(
        return_value=httpx.Response(200, json=[]))
    respx.get("https://canvas.example.edu/api/v1/planner/items").mock(
        return_value=httpx.Response(200, json=[]))

    client = CanvasClient(CFG)
    result = await do_whats_due(client, days=7)
    await client.aclose()

    assert result["items"][0]["undated"] is True
