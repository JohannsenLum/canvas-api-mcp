# tests/test_orientation.py
import httpx
import respx

from canvas_api_mcp import identity
from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.orientation import do_my_courses, do_whoami

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)

SELF = {"id": 42, "name": "Jo Tan", "login_id": "e0123456"}
ENROLMENTS = [
    {"course_id": 101, "type": "StudentEnrollment"},
    {"course_id": 202, "type": "TaEnrollment"},
]
COURSES = [
    {"id": 101, "name": "Algorithms", "course_code": "CS3230",
     "term": {"name": "AY2526 S1"},
     "enrollments": [{"type": "student"}]},
    {"id": 202, "name": "Programming Methodology", "course_code": "CS1101S",
     "term": {"name": "AY2526 S1"},
     "enrollments": [{"type": "ta"}]},
]


def _mock_identity():
    respx.get("https://canvas.example.edu/api/v1/users/self").mock(
        return_value=httpx.Response(200, json=SELF)
    )
    respx.get("https://canvas.example.edu/api/v1/users/self/enrollments").mock(
        return_value=httpx.Response(200, json=ENROLMENTS)
    )


@respx.mock
async def test_whoami_reports_name_and_per_course_roles():
    identity.clear_cache()
    _mock_identity()
    client = CanvasClient(CFG)
    result = await do_whoami(client)
    await client.aclose()

    assert result["name"] == "Jo Tan"
    assert result["id"] == 42
    assert result["roles_by_course"][101] == ["student"]
    assert result["roles_by_course"][202] == ["ta"]


@respx.mock
async def test_identity_is_cached_across_calls():
    identity.clear_cache()
    route = respx.get("https://canvas.example.edu/api/v1/users/self").mock(
        return_value=httpx.Response(200, json=SELF)
    )
    respx.get("https://canvas.example.edu/api/v1/users/self/enrollments").mock(
        return_value=httpx.Response(200, json=ENROLMENTS)
    )
    client = CanvasClient(CFG)
    await do_whoami(client)
    await do_whoami(client)
    await client.aclose()

    assert route.call_count == 1


@respx.mock
async def test_my_courses_shapes_term_and_roles():
    respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=COURSES)
    )
    client = CanvasClient(CFG)
    courses = await do_my_courses(client)
    await client.aclose()

    assert courses[0] == {
        "id": 101,
        "name": "Algorithms",
        "course_code": "CS3230",
        "term": "AY2526 S1",
        "roles": ["student"],
    }
    assert courses[1]["roles"] == ["ta"]


@respx.mock
async def test_my_courses_handles_null_enrollments():
    """Canvas can serialize enrollments: null (not just an absent key) for a
    course; this must not raise TypeError and should yield an empty roles list."""
    respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "Course A", "course_code": "A",
             "term": {"name": "T"}, "enrollments": None},
        ])
    )
    client = CanvasClient(CFG)
    courses = await do_my_courses(client)
    await client.aclose()

    assert courses[0]["id"] == 1
    assert courses[0]["roles"] == []


@respx.mock
async def test_my_courses_requests_active_enrolments_with_term():
    route = respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    await do_my_courses(client)
    await client.aclose()

    params = route.calls[0].request.url.params
    assert params["enrollment_state"] == "active"
    assert "term" in params.get_list("include[]")
