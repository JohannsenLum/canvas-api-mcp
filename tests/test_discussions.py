# tests/test_discussions.py
import httpx
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.discussions import do_post_discussion_reply, do_read_discussion

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
API = "https://canvas.example.edu/api/v1"


@respx.mock
async def test_lists_topics_when_no_topic_id():
    respx.get(f"{API}/courses/101/discussion_topics").mock(
        return_value=httpx.Response(200, json=[
            {"id": 7, "title": "PS3 clarifications", "posted_at": "2026-08-01T00:00:00Z",
             "discussion_subentry_count": 12, "html_url": "https://c/7"},
        ])
    )
    client = CanvasClient(CFG)
    result = await do_read_discussion(client, 101)
    await client.aclose()

    assert result["topics"][0]["title"] == "PS3 clarifications"
    assert result["topics"][0]["reply_count"] == 12


@respx.mock
async def test_reads_a_topic_and_flattens_nested_replies():
    respx.get(f"{API}/courses/101/discussion_topics/7").mock(
        return_value=httpx.Response(200, json={"id": 7, "title": "PS3", "message": "<p>Ask here</p>"})
    )
    respx.get(f"{API}/courses/101/discussion_topics/7/view").mock(
        return_value=httpx.Response(200, json={
            "view": [
                {"id": 1, "user_id": 42, "message": "Is Q2 recursive?",
                 "created_at": "2026-08-02T00:00:00Z",
                 "replies": [
                     {"id": 2, "user_id": 9, "message": "Yes.",
                      "created_at": "2026-08-02T01:00:00Z"},
                 ]},
            ]
        })
    )
    client = CanvasClient(CFG)
    result = await do_read_discussion(client, 101, topic_id=7)
    await client.aclose()

    assert result["title"] == "PS3"
    assert [e["id"] for e in result["entries"]] == [1, 2]
    assert result["entries"][1]["depth"] == 1


@respx.mock
async def test_post_reply_sends_message():
    route = respx.post(f"{API}/courses/101/discussion_topics/7/entries").mock(
        return_value=httpx.Response(201, json={"id": 33, "created_at": "2026-08-11T00:00:00Z"})
    )
    client = CanvasClient(CFG)
    result = await do_post_discussion_reply(client, 101, 7, "My answer")
    await client.aclose()

    assert "My answer" in route.calls[0].request.read().decode()
    assert result["id"] == 33


@respx.mock
async def test_reply_to_entry_uses_nested_endpoint():
    route = respx.post(f"{API}/courses/101/discussion_topics/7/entries/2/replies").mock(
        return_value=httpx.Response(201, json={"id": 34})
    )
    client = CanvasClient(CFG)
    await do_post_discussion_reply(client, 101, 7, "Thanks", parent_entry_id=2)
    await client.aclose()
    assert route.called


@respx.mock
async def test_canvas_rejection_is_returned_structured():
    """A rejected POST (e.g. 403) must come back as the tool's structured
    error contract, not an unhandled exception."""
    respx.post(f"{API}/courses/101/discussion_topics/7/entries").mock(
        return_value=httpx.Response(403, json={"status": "unauthorized"})
    )
    client = CanvasClient(CFG)
    result = await do_post_discussion_reply(client, 101, 7, "My answer")
    await client.aclose()

    assert result["error"] is True
    assert result["status"] == 403


@respx.mock
async def test_empty_message_is_rejected_without_sending():
    route = respx.post(f"{API}/courses/101/discussion_topics/7/entries").mock(
        return_value=httpx.Response(201, json={})
    )
    client = CanvasClient(CFG)
    result = await do_post_discussion_reply(client, 101, 7, "   ")
    await client.aclose()

    assert route.called is False
    assert result["error"] is True
