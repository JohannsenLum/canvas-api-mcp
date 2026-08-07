# src/canvas_api_mcp/identity.py
"""Who the token belongs to, and what role it holds in each course.

Used for orientation and error messages only. Authorisation decisions are
always Canvas's — this module never gates a call.
"""

from __future__ import annotations

from .client import CanvasClient

_cache: dict | None = None

# Canvas enrolment type -> plain role name
ROLE_NAMES = {
    "StudentEnrollment": "student",
    "TeacherEnrollment": "teacher",
    "TaEnrollment": "ta",
    "DesignerEnrollment": "designer",
    "ObserverEnrollment": "observer",
}


def clear_cache() -> None:
    global _cache
    _cache = None


async def fetch_identity(client: CanvasClient) -> dict:
    global _cache
    if _cache is not None:
        return _cache

    profile = (await client.request("GET", "users/self/profile")).data or {}
    enrolments = (await client.request("GET", "users/self/enrollments")).data or []

    roles_by_course: dict[int, list[str]] = {}
    for enrolment in enrolments:
        course_id = enrolment.get("course_id")
        if course_id is None:
            continue
        raw = enrolment.get("type", "")
        role = ROLE_NAMES.get(raw, raw.replace("Enrollment", "").lower())
        roles_by_course.setdefault(course_id, [])
        if role not in roles_by_course[course_id]:
            roles_by_course[course_id].append(role)

    _cache = {
        "id": profile.get("id"),
        "name": profile.get("name"),
        "login_id": profile.get("login_id"),
        "calendar_feed_url": (profile.get("calendar") or {}).get("ics"),
        "roles_by_course": roles_by_course,
    }
    return _cache
