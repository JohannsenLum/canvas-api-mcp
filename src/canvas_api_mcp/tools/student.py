# src/canvas_api_mcp/tools/student.py
"""The student daily driver: deadlines, grades, assignments, submissions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import CanvasClient, CanvasError
from ..safety import BODY_LIMIT, COMMENT_LIMIT, MESSAGE_LIMIT, guard

READ_ONLY = dict(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)

# Sorts unknown due dates to the end.
_FAR_FUTURE = "9999"


def _fence_comments(comments: Any) -> Any:
    """Fence the text of each submission comment, leaving its metadata alone.

    Grader feedback is free text written by an instructor or TA, so it needs the
    same treatment as a page body. The surrounding fields (author, timestamp)
    are structural and stay readable, since fencing them would only make the
    result harder to use without narrowing any real attack.
    """
    if not isinstance(comments, list):
        return comments
    out = []
    for c in comments:
        if not isinstance(c, dict):
            out.append(c)
            continue
        fenced = dict(c)
        if "comment" in fenced:
            fenced["comment"] = guard(fenced["comment"], COMMENT_LIMIT, "submission.comment")
        out.append(fenced)
    return out


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


def _from_planner(entry: dict) -> dict | None:
    plannable = entry.get("plannable") or {}
    plannable_type = entry.get("plannable_type")
    plannable_id = entry.get("plannable_id")
    if plannable_type == "assignment":
        key = ("assignment", plannable.get("id") or plannable_id)
    else:
        key = ("planner", plannable_type, plannable_id)
    submissions = entry.get("submissions")
    submitted = bool(submissions.get("submitted")) if isinstance(submissions, dict) else False
    return {
        "title": plannable.get("title") or entry.get("context_name"),
        "type": plannable_type or "event",
        "due_at": entry.get("plannable_date") or plannable.get("due_at"),
        "course_id": entry.get("course_id"),
        "course_name": entry.get("context_name"),
        "html_url": entry.get("html_url"),
        "submitted": submitted,
        "_key": key,
    }


async def _safe_fetch(client: CanvasClient, path: str, warnings: list[str]) -> list[dict]:
    try:
        response = await client.request("GET", path)
    except CanvasError as exc:
        warnings.append(f"Could not read {path}: {exc.message}")
        return []
    except httpx.HTTPError as exc:
        warnings.append(f"Could not read {path}: {exc}")
        return []
    data = response.data
    return data if isinstance(data, list) else []


def _parse_due(value: str | None) -> datetime | None:
    """Parse a Canvas ISO-8601 timestamp. Returns None for missing or malformed values.

    Canvas emits a trailing 'Z'; fromisoformat only learned to accept that in 3.11,
    and a bad value must never take down the whole result.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def do_whats_due(client: CanvasClient, days: int = 14) -> dict[str, Any]:
    warnings: list[str] = []
    sources = ("users/self/todo", "users/self/upcoming_events", "planner/items")
    todo = await _safe_fetch(client, sources[0], warnings)
    upcoming = await _safe_fetch(client, sources[1], warnings)
    planner = await _safe_fetch(client, sources[2], warnings)

    if len(warnings) == len(sources):
        # Every source failed: nothing was actually read from Canvas, so an
        # empty `items` here would tell a student "nothing due" when the true
        # answer is "unknown". _safe_fetch appends exactly one warning per
        # failed source, so this count means a total outage, not a quiet day.
        # Return an error shape (no `items` at all) instead of a clean-looking
        # empty result, so a model can't mistake this for a real answer.
        return {
            "error": True,
            "status": 0,
            "message": (
                "Could not determine what is due: every source failed to load "
                "from Canvas, so this is not evidence of an empty schedule. "
                "Do not report that nothing is due. Report that Canvas "
                "could not be reached, and see `warnings` for the cause "
                "(e.g. a wrong CANVAS_BASE_URL or an unreachable host)."
            ),
            "warnings": warnings,
        }

    items: dict[tuple, dict] = {}
    for entry in todo:
        item = _from_todo(entry)
        if item:
            items.setdefault(item["_key"], item)
    for entry in upcoming:
        item = _from_upcoming(entry)
        if item:
            items.setdefault(item["_key"], item)
    for entry in planner:
        item = _from_planner(entry)
        if item:
            items.setdefault(item["_key"], item)

    ordered = sorted(items.values(), key=lambda i: i.get("due_at") or _FAR_FUTURE)
    for item in ordered:
        item.pop("_key", None)

    # Canvas decides its own horizons for /todo, /upcoming_events and /planner/items,
    # and they do not agree with each other or with the caller's request. Honour `days`
    # here so the promise in the tool signature actually holds.
    horizon = datetime.now(timezone.utc) + timedelta(days=days)
    within, undated = [], []
    for item in ordered:
        due = _parse_due(item.get("due_at"))
        if due is None:
            # Keep undated work: a to-do with no due date is still outstanding, and
            # dropping it would hide real tasks. Flagged so callers can tell them apart.
            item["undated"] = True
            undated.append(item)
        elif due <= horizon:
            within.append(item)

    return {
        "items": within + undated,
        "days": days,
        "horizon": horizon.isoformat(),
        "warnings": warnings,
    }


async def do_my_grades(client: CanvasClient, course_id: int | None = None) -> list[dict]:
    response = await client.request(
        "GET",
        "courses",
        params={"enrollment_state": "active", "include[]": ["total_scores"], "per_page": 100},
    )
    out = []
    for course in response.data or []:
        if course_id is not None and course.get("id") != course_id:
            continue
        enrolment = next(
            (e for e in (course.get("enrollments") or []) if e.get("type") == "student"),
            None,
        )
        if enrolment is None:
            continue
        out.append(
            {
                "course_id": course.get("id"),
                "course_name": course.get("name"),
                "current_score": enrolment.get("computed_current_score"),
                "current_grade": enrolment.get("computed_current_grade"),
                "final_score": enrolment.get("computed_final_score"),
            }
        )
    return out


async def do_list_assignments(
    client: CanvasClient, course_id: int, bucket: str | None = None
) -> list[dict]:
    params: dict[str, Any] = {"include[]": ["submission"], "per_page": 100}
    if bucket:
        params["bucket"] = bucket
    response = await client.request(
        "GET", f"courses/{course_id}/assignments", params=params
    )
    out = []
    for assignment in response.data or []:
        submission = assignment.get("submission") or {}
        state = submission.get("workflow_state")
        out.append(
            {
                "id": assignment.get("id"),
                "name": assignment.get("name"),
                "due_at": assignment.get("due_at"),
                "points_possible": assignment.get("points_possible"),
                "html_url": assignment.get("html_url"),
                "submitted": state in {"submitted", "graded", "pending_review"},
                "score": submission.get("score"),
            }
        )
    return out


async def do_get_assignment(
    client: CanvasClient, course_id: int, assignment_id: int
) -> dict:
    # GET assignment only accepts include[]=submission (among others). Comments and
    # rubric assessments live on the submissions endpoint. Canvas silently drops
    # unrecognised include[] values on the assignment route.
    response = await client.request(
        "GET",
        f"courses/{course_id}/assignments/{assignment_id}",
        params={"include[]": ["submission"]},
    )
    assignment = response.data or {}
    raw_submission = assignment.get("submission")
    submission: dict[str, Any] = (
        dict(raw_submission) if isinstance(raw_submission, dict) else {}
    )

    note: str | None = None
    try:
        sub_response = await client.request(
            "GET",
            f"courses/{course_id}/assignments/{assignment_id}/submissions/self",
            params={"include[]": ["submission_comments", "rubric_assessment"]},
        )
        detailed = sub_response.data or {}
        if isinstance(detailed, dict):
            # Prefer fields from the submissions endpoint (especially comments / rubric).
            submission = {**submission, **detailed}
            if "submission_comments" in submission:
                submission["submission_comments"] = _fence_comments(
                    submission["submission_comments"]
                )
    except CanvasError as exc:
        note = (
            "Assignment loaded, but submission comments/rubric could not be fetched: "
            f"{exc.message}"
        )
    except httpx.HTTPError as exc:
        note = (
            "Assignment loaded, but submission comments/rubric could not be fetched: "
            f"{exc}"
        )

    result: dict[str, Any] = {
        "id": assignment.get("id"),
        "name": assignment.get("name"),
        # Instructor-authored HTML. The sharpest case in this file: a model
        # reading an assignment brief has every reason to treat it as an
        # instruction addressed to the student.
        "description": guard(assignment.get("description"), BODY_LIMIT, "assignment.description"),
        "due_at": assignment.get("due_at"),
        "unlock_at": assignment.get("unlock_at"),
        "lock_at": assignment.get("lock_at"),
        "points_possible": assignment.get("points_possible"),
        "submission_types": assignment.get("submission_types", []),
        "allowed_extensions": assignment.get("allowed_extensions", []),
        "html_url": assignment.get("html_url"),
        "rubric": assignment.get("rubric", []),
        "submission": submission if submission else raw_submission,
    }
    if note:
        result["note"] = note
    return result


async def do_my_submission(
    client: CanvasClient, course_id: int, assignment_id: int
) -> dict:
    response = await client.request(
        "GET",
        f"courses/{course_id}/assignments/{assignment_id}/submissions/self",
        params={"include[]": ["submission_comments", "rubric_assessment"]},
    )
    submission = response.data or {}
    return {
        "workflow_state": submission.get("workflow_state"),
        "submitted_at": submission.get("submitted_at"),
        "score": submission.get("score"),
        "grade": submission.get("grade"),
        "late": submission.get("late"),
        "missing": submission.get("missing"),
        "attempt": submission.get("attempt"),
        "comments": _fence_comments(submission.get("submission_comments", [])),
        "rubric_assessment": submission.get("rubric_assessment"),
    }


async def do_course_announcements(
    client: CanvasClient, course_id: int | None = None, days: int = 14
) -> list[dict]:
    start = datetime.now(timezone.utc) - timedelta(days=days)
    params: dict[str, Any] = {
        "start_date": start.date().isoformat(),
        "per_page": 50,
    }
    if course_id is not None:
        params["context_codes[]"] = [f"course_{course_id}"]
    else:
        courses = await client.request(
            "GET", "courses", params={"enrollment_state": "active", "per_page": 100}
        )
        codes = [f"course_{c['id']}" for c in (courses.data or []) if c.get("id")]
        if not codes:
            return []
        params["context_codes[]"] = codes

    response = await client.request("GET", "announcements", params=params)
    out = []
    for item in response.data or []:
        out.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                # Announcements are normally restricted to teaching staff, which
                # is exactly why a model weights them heavily and why they need
                # fencing more than an ordinary discussion reply does.
                "message": guard(item.get("message"), MESSAGE_LIMIT, "announcement.message"),
                "posted_at": item.get("posted_at"),
                "html_url": item.get("html_url"),
                "course_id": _course_id_from_context(item.get("context_code")),
            }
        )
    return out


SUBMISSION_REQUIREMENTS = {
    "online_text_entry": "body",
    "online_url": "url",
    "online_upload": "file_ids",
}


async def do_submit_assignment(
    client: CanvasClient,
    course_id: int,
    assignment_id: int,
    submission_type: str,
    body: str | None = None,
    url: str | None = None,
    file_ids: list[int] | None = None,
) -> dict:
    if submission_type not in SUBMISSION_REQUIREMENTS:
        return {
            "error": True,
            "status": 0,
            "message": (
                f"Unknown submission_type {submission_type!r}. Supported types: "
                f"{', '.join(sorted(SUBMISSION_REQUIREMENTS))}. Check the assignment's "
                "submission_types with get_assignment."
            ),
        }

    supplied = {"body": body, "url": url, "file_ids": file_ids}
    required = SUBMISSION_REQUIREMENTS[submission_type]
    if not supplied[required]:
        return {
            "error": True,
            "status": 0,
            "message": (
                f"submission_type {submission_type!r} requires the {required!r} "
                "argument, which was not provided. Nothing was submitted."
            ),
        }

    payload: dict[str, Any] = {"submission_type": submission_type}
    if submission_type == "online_text_entry":
        payload["body"] = body
    elif submission_type == "online_url":
        payload["url"] = url
    else:
        payload["file_ids"] = file_ids

    try:
        response = await client.request(
            "POST",
            f"courses/{course_id}/assignments/{assignment_id}/submissions",
            json={"submission": payload},
        )
    except CanvasError as exc:
        return {
            "error": True,
            "status": exc.status,
            "message": exc.message,
            "hint": exc.hint,
        }

    submission = response.data or {}
    return {
        "id": submission.get("id"),
        "workflow_state": submission.get("workflow_state"),
        "submitted_at": submission.get("submitted_at"),
        "attempt": submission.get("attempt"),
        "late": submission.get("late"),
        "preview_url": submission.get("preview_url"),
    }


def register(mcp: FastMCP, get_client) -> None:
    @mcp.tool(
        description=(
            "List what is due for the user across all courses (assignments, quizzes, "
            "and scheduled events), sorted soonest first. This is the primary tool for "
            "'what's due this week', 'what do I have coming up', and deadline planning."
        ),
        annotations=ToolAnnotations(title="What's Due", **READ_ONLY),
    )
    async def whats_due(
        days: int = Field(default=14, description="Horizon in days to describe in the result"),
    ) -> dict:
        """Merged upcoming deadlines and events."""
        return await do_whats_due(get_client(), days=days)

    @mcp.tool(
        description=(
            "Report the user's current grade and score in each course, or in one course "
            "if course_id is given. Use this for 'how am I doing' and standing questions."
        ),
        annotations=ToolAnnotations(title="My Grades", **READ_ONLY),
    )
    async def my_grades(
        course_id: int | None = Field(default=None, description="Limit to one course; omit for all"),
    ) -> list[dict]:
        """Current scores per course."""
        return await do_my_grades(get_client(), course_id=course_id)

    @mcp.tool(
        description=(
            "List a course's assignments with due dates, points, and whether the user "
            "has submitted each one. Use bucket to filter to upcoming, overdue, "
            "unsubmitted, or past work."
        ),
        annotations=ToolAnnotations(title="List Assignments", **READ_ONLY),
    )
    async def list_assignments(
        course_id: int = Field(description="Course id, from my_courses"),
        bucket: str | None = Field(
            default=None,
            description="One of: past, overdue, undated, ungraded, unsubmitted, upcoming, future",
        ),
    ) -> list[dict]:
        """Assignments in a course."""
        return await do_list_assignments(get_client(), course_id, bucket=bucket)

    @mcp.tool(
        description=(
            "Get one assignment in full: instructions, due and lock dates, points, "
            "accepted submission types, rubric, and the user's current submission state."
        ),
        annotations=ToolAnnotations(title="Get Assignment", **READ_ONLY),
    )
    async def get_assignment(
        course_id: int = Field(description="Course id"),
        assignment_id: int = Field(description="Assignment id"),
    ) -> dict:
        """Full detail for a single assignment."""
        return await do_get_assignment(get_client(), course_id, assignment_id)

    @mcp.tool(
        description=(
            "Get the user's own submission for an assignment: state, score, grade, "
            "lateness, instructor comments, and rubric assessment."
        ),
        annotations=ToolAnnotations(title="My Submission", **READ_ONLY),
    )
    async def my_submission(
        course_id: int = Field(description="Course id"),
        assignment_id: int = Field(description="Assignment id"),
    ) -> dict:
        """The user's submission and feedback."""
        return await do_my_submission(get_client(), course_id, assignment_id)

    @mcp.tool(
        description=(
            "List recent course announcements across all active courses, or one course "
            "if course_id is given."
        ),
        annotations=ToolAnnotations(title="Announcements", **READ_ONLY),
    )
    async def course_announcements(
        course_id: int | None = Field(default=None, description="Limit to one course; omit for all"),
        days: int = Field(default=14, description="How many days back to look"),
    ) -> list[dict]:
        """Recent announcements."""
        return await do_course_announcements(get_client(), course_id=course_id, days=days)

    @mcp.tool(
        description=(
            "Submits work to Canvas for an assignment. This is recorded against the "
            "deadline immediately, is visible to the instructor, and cannot be undone "
            "from here. Confirm the assignment and content with the user before calling. "
            "Check accepted formats with get_assignment first: submission_type must be "
            "one the assignment allows. For online_upload, file_ids must reference files "
            "already uploaded to Canvas."
        ),
        annotations=ToolAnnotations(
            title="Submit Assignment",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def submit_assignment(
        course_id: int = Field(description="Course id"),
        assignment_id: int = Field(description="Assignment id"),
        submission_type: str = Field(
            description="One of: online_text_entry, online_url, online_upload"
        ),
        body: str | None = Field(default=None, description="Text content for online_text_entry"),
        url: str | None = Field(default=None, description="URL for online_url"),
        file_ids: list[int] | None = Field(
            default=None, description="Canvas file ids for online_upload"
        ),
    ) -> dict:
        """Submit an assignment."""
        return await do_submit_assignment(
            get_client(), course_id, assignment_id, submission_type,
            body=body, url=url, file_ids=file_ids,
        )
