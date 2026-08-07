# tests/test_submit.py
import httpx
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.student import do_submit_assignment

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
URL = "https://canvas.example.edu/api/v1/courses/101/assignments/1/submissions"


@respx.mock
async def test_text_entry_posts_correct_payload():
    route = respx.post(URL).mock(
        return_value=httpx.Response(201, json={"id": 7, "workflow_state": "submitted",
                                               "submitted_at": "2026-08-11T10:00:00Z"})
    )
    client = CanvasClient(CFG)
    result = await do_submit_assignment(
        client, 101, 1, "online_text_entry", body="my answer"
    )
    await client.aclose()

    sent = route.calls[0].request.read().decode()
    assert '"submission_type": "online_text_entry"' in sent.replace("  ", " ") or "online_text_entry" in sent
    assert "my answer" in sent
    assert result["workflow_state"] == "submitted"


@respx.mock
async def test_url_submission_posts_url_field():
    route = respx.post(URL).mock(return_value=httpx.Response(201, json={"id": 8}))
    client = CanvasClient(CFG)
    await do_submit_assignment(client, 101, 1, "online_url", url="https://github.com/me/x")
    await client.aclose()
    assert "github.com/me/x" in route.calls[0].request.read().decode()


@respx.mock
async def test_upload_posts_file_ids():
    route = respx.post(URL).mock(return_value=httpx.Response(201, json={"id": 9}))
    client = CanvasClient(CFG)
    await do_submit_assignment(client, 101, 1, "online_upload", file_ids=[55, 56])
    await client.aclose()
    assert "55" in route.calls[0].request.read().decode()


async def test_missing_body_for_text_entry_is_rejected_without_sending():
    with respx.mock:
        route = respx.post(URL).mock(return_value=httpx.Response(201, json={}))
        client = CanvasClient(CFG)
        result = await do_submit_assignment(client, 101, 1, "online_text_entry")
        await client.aclose()

    assert route.called is False
    assert result["error"] is True
    assert "body" in result["message"]


async def test_unknown_submission_type_is_rejected_without_sending():
    with respx.mock:
        route = respx.post(URL).mock(return_value=httpx.Response(201, json={}))
        client = CanvasClient(CFG)
        result = await do_submit_assignment(client, 101, 1, "carrier_pigeon", body="x")
        await client.aclose()

    assert route.called is False
    assert result["error"] is True
    assert "carrier_pigeon" in result["message"]


@respx.mock
async def test_canvas_rejection_is_returned_structured():
    respx.post(URL).mock(return_value=httpx.Response(403, json={"status": "unauthorized"}))
    client = CanvasClient(CFG)
    result = await do_submit_assignment(client, 101, 1, "online_text_entry", body="x")
    await client.aclose()

    assert result["error"] is True
    assert result["status"] == 403
