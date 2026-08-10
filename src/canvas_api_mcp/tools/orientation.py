# src/canvas_api_mcp/tools/orientation.py
"""Who am I, and what am I enrolled in."""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import CanvasClient
from ..identity import fetch_calendar_feed_url, fetch_identity

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)


async def do_whoami(client: CanvasClient) -> dict:
    return await fetch_identity(client)


async def do_get_calendar_feed_url(client: CanvasClient) -> dict:
    return {
        "calendar_feed_url": await fetch_calendar_feed_url(client),
        "warning": (
            "This URL is a bearer credential: anyone holding it can read the "
            "user's full Canvas calendar with no authentication, and it does "
            "not expire when the access token is rotated. Treat it like a "
            "password. Do not paste it anywhere untrusted."
        ),
    }


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
            "the user's name and their role in each course (student, ta, teacher). "
            "Call this first when you need to know what the user can access."
        ),
        annotations=ToolAnnotations(title="Who Am I", **READ_ONLY.model_dump(exclude={"title"})),
    )
    async def whoami() -> dict:
        """Return the authenticated user's identity and per-course roles."""
        return await do_whoami(get_client())

    @mcp.tool(
        description=(
            "Fetch the user's private calendar .ics subscription URL, a link they "
            "can add to Google/Apple/Outlook calendar to see every Canvas deadline "
            "natively. This URL is a bearer credential: whoever holds it can read the "
            "user's full calendar with no authentication, and it survives token "
            "rotation. Only call this when the user has explicitly asked for their "
            "calendar feed / subscription link. Do not call it as part of general "
            "orientation, and do not repeat the URL back unless asked to."
        ),
        annotations=ToolAnnotations(
            title="Get Calendar Feed URL", **READ_ONLY.model_dump(exclude={"title"})
        ),
    )
    async def get_calendar_feed_url() -> dict:
        """Return the user's calendar .ics subscription URL, fetched on demand."""
        return await do_get_calendar_feed_url(get_client())

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
