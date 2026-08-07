# src/canvas_api_mcp/tools/student.py
"""The student daily driver: deadlines, grades, assignments, submissions."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import CanvasClient, CanvasError

READ_ONLY = dict(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)

# Sorts unknown due dates to the end.
_FAR_FUTURE = "9999"


def _course_id_from_context(code: str | None) -> int | None:
    if not code or not code.startswith("course_"):
        return None
    try:
        return int(code.split("_", 1)[1])
    except ValueError:
        return None


def _from_todo(entry: dict) -> dict | None:
    assignment = entry.get("assignment") or {}
    if not assignment:
        return None
    return {
        "title": assignment.get("name"),
        "type": "assignment",
        "due_at": assignment.get("due_at"),
        "course_id": assignment.get("course_id"),
        "course_name": entry.get("context_name"),
        "html_url": assignment.get("html_url") or entry.get("html_url"),
        "submitted": False,
        "_key": ("assignment", assignment.get("id")),
    }


def _from_upcoming(entry: dict) -> dict | None:
    assignment = entry.get("assignment") or {}
    if assignment:
        return {
            "title": entry.get("title"),
            "type": "assignment",
            "due_at": assignment.get("due_at") or entry.get("start_at"),
            "course_id": assignment.get("course_id")
            or _course_id_from_context(entry.get("context_code")),
            "course_name": entry.get("context_name"),
            "html_url": entry.get("html_url"),
            "submitted": bool(assignment.get("has_submitted_submissions")),
            "_key": ("assignment", assignment.get("id")),
        }
    return {
        "title": entry.get("title"),
        "type": "event",
        "due_at": entry.get("start_at"),
        "course_id": _course_id_from_context(entry.get("context_code")),
        "course_name": entry.get("context_name"),
        "html_url": entry.get("html_url"),
        "submitted": False,
        "_key": ("event", entry.get("id")),
    }


async def _safe_fetch(client: CanvasClient, path: str, warnings: list[str]) -> list[dict]:
    try:
        response = await client.request("GET", path)
    except CanvasError as exc:
        warnings.append(f"Could not read {path}: {exc.message}")
        return []
    data = response.data
    return data if isinstance(data, list) else []


async def do_whats_due(client: CanvasClient, days: int = 14) -> dict[str, Any]:
    warnings: list[str] = []
    todo = await _safe_fetch(client, "users/self/todo", warnings)
    upcoming = await _safe_fetch(client, "users/self/upcoming_events", warnings)

    items: dict[tuple, dict] = {}
    for entry in todo:
        item = _from_todo(entry)
        if item:
            items.setdefault(item["_key"], item)
    for entry in upcoming:
        item = _from_upcoming(entry)
        if item:
            items.setdefault(item["_key"], item)

    ordered = sorted(items.values(), key=lambda i: i.get("due_at") or _FAR_FUTURE)
    for item in ordered:
        item.pop("_key", None)

    return {"items": ordered, "days": days, "warnings": warnings}


def register(mcp: FastMCP, get_client) -> None:
    @mcp.tool(
        description=(
            "List what is due for the user across all courses — assignments, quizzes, "
            "and scheduled events — sorted soonest first. This is the primary tool for "
            "'what's due this week', 'what do I have coming up', and deadline planning."
        ),
        annotations=ToolAnnotations(title="What's Due", **READ_ONLY),
    )
    async def whats_due(
        days: int = Field(default=14, description="Horizon in days to describe in the result"),
    ) -> dict:
        """Merged upcoming deadlines and events."""
        return await do_whats_due(get_client(), days=days)
