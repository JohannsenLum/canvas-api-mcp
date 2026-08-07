# src/canvas_api_mcp/tools/orientation.py
"""Who am I, and what am I enrolled in."""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import CanvasClient
from ..identity import fetch_identity

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)


async def do_whoami(client: CanvasClient) -> dict:
    return await fetch_identity(client)


async def do_my_courses(client: CanvasClient, state: str = "active") -> list[dict]:
    response = await client.request(
        "GET",
        "courses",
        params={"enrollment_state": state, "include[]": ["term"], "per_page": 100},
    )
    courses = response.data or []
    shaped = []
    for course in courses:
        term = course.get("term") or {}
        shaped.append(
            {
                "id": course.get("id"),
                "name": course.get("name"),
                "course_code": course.get("course_code"),
                "term": term.get("name"),
                "roles": [e.get("type") for e in (course.get("enrollments") or []) if e.get("type")],
            }
        )
    return shaped


def register(mcp: FastMCP, get_client) -> None:
    @mcp.tool(
        description=(
            "Identify the Canvas account this server is authenticated as, including "
            "the user's name, their role in each course (student, ta, teacher), and "
            "their private calendar_feed_url — an .ics link the user can subscribe to "
            "in Google/Apple/Outlook calendar to see every Canvas deadline natively. "
            "Call this first when you need to know what the user can access."
        ),
        annotations=ToolAnnotations(title="Who Am I", **READ_ONLY.model_dump(exclude={"title"})),
    )
    async def whoami() -> dict:
        """Return the authenticated user's identity and per-course roles."""
        return await do_whoami(get_client())

    @mcp.tool(
        description=(
            "List the user's Canvas courses with course code, term, and their role in "
            "each. Use this to resolve a course name or code to the course_id that "
            "other tools require."
        ),
        annotations=ToolAnnotations(title="My Courses", **READ_ONLY.model_dump(exclude={"title"})),
    )
    async def my_courses(
        state: str = Field(default="active", description="Enrollment state: active, completed, or invited"),
    ) -> list[dict]:
        """List enrolled courses."""
        return await do_my_courses(get_client(), state=state)
