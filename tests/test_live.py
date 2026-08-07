# tests/test_live.py
"""Live tests against a real Canvas account.

Skipped unless CANVAS_LIVE_TESTS=1. Never run in CI. Read-only except for a
dry_run that sends nothing.
"""

import os

import pytest

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.gateway import do_request
from canvas_api_mcp.tools.orientation import do_my_courses, do_whoami
from canvas_api_mcp.tools.student import do_whats_due

pytestmark = pytest.mark.skipif(
    os.environ.get("CANVAS_LIVE_TESTS") != "1",
    reason="set CANVAS_LIVE_TESTS=1 with real CANVAS_BASE_URL and CANVAS_TOKEN",
)


@pytest.fixture
async def client():
    c = CanvasClient(Config.from_env(os.environ))
    yield c
    await c.aclose()


async def test_whoami_returns_a_real_identity(client):
    me = await do_whoami(client)
    assert isinstance(me["id"], int)
    assert me["name"]


async def test_my_courses_returns_enrolments(client):
    courses = await do_my_courses(client)
    assert isinstance(courses, list)
    for course in courses:
        assert "id" in course and "name" in course


async def test_whats_due_runs_without_error(client):
    result = await do_whats_due(client)
    assert "items" in result
    assert result["warnings"] == []


async def test_gateway_reaches_an_uncurated_endpoint(client):
    result = await do_request(client, "GET", "/v1/users/self/groups")
    assert "error" not in result


async def test_write_path_dry_run_sends_nothing(client):
    result = await do_request(
        client, "POST", "/v1/courses/1/assignments/1/submissions", dry_run=True
    )
    assert result["dry_run"] is True
