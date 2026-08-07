# src/canvas_api_mcp/tools/discussions.py
"""Course discussion topics and replies."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import CanvasClient, CanvasError

READ_ONLY = dict(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)


def _flatten(entries: list[dict], depth: int = 0) -> list[dict]:
    out: list[dict] = []
    for entry in entries:
        out.append(
            {
                "id": entry.get("id"),
                "user_id": entry.get("user_id"),
                "message": entry.get("message"),
                "created_at": entry.get("created_at"),
                "depth": depth,
            }
        )
        out.extend(_flatten(entry.get("replies") or [], depth + 1))
    return out


async def do_read_discussion(
    client: CanvasClient, course_id: int, topic_id: int | None = None
) -> dict[str, Any]:
    if topic_id is None:
        response = await client.request(
            "GET", f"courses/{course_id}/discussion_topics", params={"per_page": 50}
        )
        return {
            "topics": [
                {
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "posted_at": t.get("posted_at"),
                    "reply_count": t.get("discussion_subentry_count"),
                    "html_url": t.get("html_url"),
                }
                for t in response.data or []
            ]
        }

    topic = (
        await client.request("GET", f"courses/{course_id}/discussion_topics/{topic_id}")
    ).data or {}
    view = (
        await client.request(
            "GET", f"courses/{course_id}/discussion_topics/{topic_id}/view"
        )
    ).data or {}

    return {
        "id": topic.get("id"),
        "title": topic.get("title"),
        "message": topic.get("message"),
        "entries": _flatten(view.get("view") or []),
    }


async def do_post_discussion_reply(
    client: CanvasClient,
    course_id: int,
    topic_id: int,
    message: str,
    parent_entry_id: int | None = None,
) -> dict:
    if not message or not message.strip():
        return {
            "error": True,
            "status": 0,
            "message": "Refusing to post an empty discussion reply. Nothing was sent.",
        }

    base = f"courses/{course_id}/discussion_topics/{topic_id}/entries"
    path = base if parent_entry_id is None else f"{base}/{parent_entry_id}/replies"

    try:
        response = await client.request("POST", path, json={"message": message})
    except CanvasError as exc:
        return {"error": True, "status": exc.status, "message": exc.message, "hint": exc.hint}

    entry = response.data or {}
    return {"id": entry.get("id"), "created_at": entry.get("created_at")}


def register(mcp: FastMCP, get_client) -> None:
    @mcp.tool(
        description=(
            "Read course discussions. With only course_id, lists the discussion topics. "
            "With topic_id, returns that topic and all its replies flattened in order, "
            "with a depth field showing nesting."
        ),
        annotations=ToolAnnotations(title="Read Discussion", **READ_ONLY),
    )
    async def read_discussion(
        course_id: int = Field(description="Course id"),
        topic_id: int | None = Field(default=None, description="Topic id; omit to list topics"),
    ) -> dict:
        """Discussion topics or one topic's replies."""
        return await do_read_discussion(get_client(), course_id, topic_id=topic_id)

    @mcp.tool(
        description=(
            "Posts a reply to a course discussion publicly under the user's own name, "
            "visible immediately to the whole class and the instructor. It cannot be "
            "deleted from here. Show the user the exact text and get their confirmation "
            "before calling."
        ),
        annotations=ToolAnnotations(
            title="Post Discussion Reply",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def post_discussion_reply(
        course_id: int = Field(description="Course id"),
        topic_id: int = Field(description="Discussion topic id"),
        message: str = Field(description="The reply text; HTML is allowed"),
        parent_entry_id: int | None = Field(
            default=None, description="Reply to this entry instead of the topic"
        ),
    ) -> dict:
        """Post a discussion reply."""
        return await do_post_discussion_reply(
            get_client(), course_id, topic_id, message, parent_entry_id=parent_entry_id
        )
