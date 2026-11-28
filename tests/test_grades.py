# tests/test_grades.py
import httpx
import respx
from fastmcp import Client, FastMCP

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools import student as student_tools
from canvas_api_mcp.tools.student import (
    do_course_announcements,
    do_get_assignment,
    do_list_assignments,
    do_my_grades,
    do_my_submission,
)

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
SMALL = Config(base_url="https://canvas.example.edu", token="tok", max_pages=2)
API = "https://canvas.example.edu/api/v1"


def _link(url: str) -> str:
    return f'<{url}>; rel="next"'


@respx.mock
async def test_my_grades_extracts_scores_from_enrolments():
    respx.get(f"{API}/courses").mock(
        return_value=httpx.Response(200, json=[
            {"id": 101, "name": "Algorithms", "enrollments": [
                {"type": "student", "computed_current_score": 78.5,
                 "computed_current_grade": "B+", "computed_final_score": 70.2}
            ]}
        ])
    )
    client = CanvasClient(CFG)
    result = await do_my_grades(client)
    await client.aclose()

    assert result == {
        "grades": [{
            "course_id": 101, "course_name": "Algorithms",
            "current_score": 78.5, "current_grade": "B+", "final_score": 70.2,
        }],
        "truncated": False,
    }


@respx.mock
async def test_my_grades_filters_to_one_course():
    respx.get(f"{API}/courses").mock(
        return_value=httpx.Response(200, json=[
            {"id": 101, "name": "A", "enrollments": [{"type": "student", "computed_current_score": 1}]},
            {"id": 202, "name": "B", "enrollments": [{"type": "student", "computed_current_score": 2}]},
        ])
    )
    client = CanvasClient(CFG)
    result = await do_my_grades(client, course_id=202)
    await client.aclose()

    grades = result["grades"]
    assert result["truncated"] is False
    assert len(grades) == 1
    assert grades[0]["course_id"] == 202


@respx.mock
async def test_my_grades_skips_course_with_null_enrollments():
    """Canvas can serialize enrollments: null (not just an absent key) for a
    course; this must not raise TypeError and should just skip that course."""
    respx.get(f"{API}/courses").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "Course A", "enrollments": None},
            {"id": 101, "name": "Algorithms", "enrollments": [
                {"type": "student", "computed_current_score": 78.5,
                 "computed_current_grade": "B+", "computed_final_score": 70.2}
            ]},
        ])
    )
    client = CanvasClient(CFG)
    result = await do_my_grades(client)
    await client.aclose()

    grades = result["grades"]
    assert result["truncated"] is False
    assert len(grades) == 1
    assert grades[0]["course_id"] == 101


@respx.mock
async def test_list_assignments_flattens_submission_state():
    respx.get(f"{API}/courses/101/assignments").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "PS1", "due_at": "2026-08-12T15:59:00Z",
             "points_possible": 20, "html_url": "https://c/1",
             "submission": {"workflow_state": "submitted", "score": None}},
            {"id": 2, "name": "PS2", "due_at": None, "points_possible": 10,
             "html_url": "https://c/2", "submission": {"workflow_state": "graded", "score": 9.0}},
        ])
    )
    client = CanvasClient(CFG)
    result = await do_list_assignments(client, 101)
    await client.aclose()

    items = result["assignments"]
    assert result["truncated"] is False
    assert items[0]["submitted"] is True
    assert items[0]["score"] is None
    assert items[1]["score"] == 9.0


@respx.mock
async def test_list_assignments_passes_bucket_filter():
    route = respx.get(f"{API}/courses/101/assignments").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    result = await do_list_assignments(client, 101, bucket="overdue")
    await client.aclose()
    assert route.calls[0].request.url.params["bucket"] == "overdue"
    assert result == {"assignments": [], "truncated": False}


@respx.mock
async def test_get_assignment_includes_submission_and_rubric():
    """Comments/rubric live on the submissions endpoint, not GET assignment.

    Mock the two endpoints separately and put comments only on the submissions
    response so the test fails if the second call is dropped.
    """
    assignment_route = respx.get(f"{API}/courses/101/assignments/1").mock(
        return_value=httpx.Response(200, json={
            "id": 1, "name": "PS1", "description": "<p>Do it</p>",
            "due_at": "2026-08-12T15:59:00Z", "points_possible": 20,
            "rubric": [{"description": "Correctness", "points": 15}],
            # Realistic Canvas response: assignment include[]=submission does not
            # carry submission_comments or rubric_assessment.
            "submission": {
                "workflow_state": "graded",
                "score": 15.0,
            },
        })
    )
    submission_route = respx.get(
        f"{API}/courses/101/assignments/1/submissions/self"
    ).mock(
        return_value=httpx.Response(200, json={
            "workflow_state": "graded",
            "score": 15.0,
            "submission_comments": [{"comment": "nudge"}],
            "rubric_assessment": {"_123": {"points": 15}},
        })
    )
    client = CanvasClient(CFG)
    result = await do_get_assignment(client, 101, 1)
    await client.aclose()

    assert result["name"] == "PS1"
    assert result["rubric"][0]["description"] == "Correctness"
    assert assignment_route.called
    assert submission_route.called
    assignment_includes = assignment_route.calls[0].request.url.params.get_list("include[]")
    assert "submission" in assignment_includes
    assert "submission_comments" not in assignment_includes
    assert "rubric_assessment" not in assignment_includes
    submission_includes = submission_route.calls[0].request.url.params.get_list("include[]")
    assert "submission_comments" in submission_includes
    assert "rubric_assessment" in submission_includes
    # Comments only exist on the submissions mock, which proves the merge path ran.
    # Comment text is fenced as untrusted (see tests/test_safety.py), so assert
    # the payload survives inside the fence rather than comparing byte for byte.
    assert "nudge" in result["submission"]["submission_comments"][0]["comment"]
    assert result["submission"]["rubric_assessment"]["_123"]["points"] == 15
    assert result["submission"]["score"] == 15.0
    # `warnings` is always present, empty when nothing failed, matching whats_due.
    # Always-present is easier for a caller to branch on than sometimes-absent.
    assert result["warnings"] == []


@respx.mock
async def test_get_assignment_warns_when_submission_fetch_fails():
    respx.get(f"{API}/courses/101/assignments/1").mock(
        return_value=httpx.Response(200, json={
            "id": 1, "name": "PS1", "description": "<p>Do it</p>",
            "due_at": "2026-08-12T15:59:00Z", "points_possible": 20,
            "rubric": [],
            "submission": {"workflow_state": "unsubmitted"},
        })
    )
    respx.get(f"{API}/courses/101/assignments/1/submissions/self").mock(
        return_value=httpx.Response(403, json={"errors": [{"message": "forbidden"}]})
    )
    client = CanvasClient(CFG)
    result = await do_get_assignment(client, 101, 1)
    await client.aclose()

    assert result["name"] == "PS1"
    assert result["submission"]["workflow_state"] == "unsubmitted"
    # Same shape as whats_due: a list under `warnings`, not a singular `note`.
    assert result["warnings"], "a failed submissions fetch must be reported"
    assert "submission comments and rubric" in result["warnings"][0]
    assert "note" not in result, "the old singular key must be gone"


@respx.mock
async def test_my_submission_reports_score_and_comments():
    respx.get(f"{API}/courses/101/assignments/1/submissions/self").mock(
        return_value=httpx.Response(200, json={
            "workflow_state": "graded", "score": 17.0, "grade": "17",
            "submitted_at": "2026-08-10T10:00:00Z", "late": False,
            "submission_comments": [{"author_name": "Prof", "comment": "Good work"}],
        })
    )
    client = CanvasClient(CFG)
    result = await do_my_submission(client, 101, 1)
    await client.aclose()

    assert result["score"] == 17.0
    # Fenced as untrusted; the fence itself is asserted in tests/test_safety.py.
    assert "Good work" in result["comments"][0]["comment"]


@respx.mock
async def test_announcements_scopes_to_a_course_context():
    route = respx.get(f"{API}/announcements").mock(
        return_value=httpx.Response(200, json=[
            {"id": 5, "title": "Midterm venue", "message": "<p>LT7</p>",
             "posted_at": "2026-08-05T02:00:00Z", "html_url": "https://c/5",
             "context_code": "course_101"}
        ])
    )
    client = CanvasClient(CFG)
    result = await do_course_announcements(client, course_id=101)
    await client.aclose()

    items = result["announcements"]
    assert result["truncated"] is False
    assert items[0]["title"] == "Midterm venue"
    assert items[0]["course_id"] == 101
    assert "course_101" in route.calls[0].request.url.params.get_list("context_codes[]")


@respx.mock
async def test_my_grades_reports_truncation_when_max_pages_exceeded():
    base = f"{API}/courses"
    page3 = respx.get(base, params={"page": "3"}).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 303, "name": "C", "enrollments": [{"type": "student", "computed_current_score": 90}]}
            ],
        )
    )
    respx.get(base, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 202, "name": "B", "enrollments": [{"type": "student", "computed_current_score": 80}]}
            ],
            headers={"Link": _link(f"{base}?page=3")},
        )
    )
    respx.get(base).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 101, "name": "A", "enrollments": [{"type": "student", "computed_current_score": 70}]}
            ],
            headers={"Link": _link(f"{base}?page=2")},
        )
    )

    client = CanvasClient(SMALL)
    result = await do_my_grades(client)
    await client.aclose()

    assert [g["course_id"] for g in result["grades"]] == [101, 202]
    assert result["truncated"] is True
    assert not page3.called


@respx.mock
async def test_list_assignments_reports_truncation_when_max_pages_exceeded():
    base = f"{API}/courses/101/assignments"
    page3 = respx.get(base, params={"page": "3"}).mock(
        return_value=httpx.Response(200, json=[{"id": 3, "name": "PS3"}])
    )
    respx.get(base, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 2, "name": "PS2"}],
            headers={"Link": _link(f"{base}?page=3")},
        )
    )
    respx.get(base).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "name": "PS1"}],
            headers={"Link": _link(f"{base}?page=2")},
        )
    )

    client = CanvasClient(SMALL)
    result = await do_list_assignments(client, 101)
    await client.aclose()

    assert [a["id"] for a in result["assignments"]] == [1, 2]
    assert result["truncated"] is True
    assert not page3.called


@respx.mock
async def test_announcements_reports_truncation_when_announcements_exceed_max_pages():
    base = f"{API}/announcements"
    page3 = respx.get(base, params={"page": "3"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 3, "title": "A3", "message": "m3", "context_code": "course_101"}],
        )
    )
    respx.get(base, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 2, "title": "A2", "message": "m2", "context_code": "course_101"}],
            headers={"Link": _link(f"{base}?page=3")},
        )
    )
    respx.get(base).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "title": "A1", "message": "m1", "context_code": "course_101"}],
            headers={"Link": _link(f"{base}?page=2")},
        )
    )

    client = CanvasClient(SMALL)
    result = await do_course_announcements(client, course_id=101)
    await client.aclose()

    assert [a["id"] for a in result["announcements"]] == [1, 2]
    assert result["truncated"] is True
    assert not page3.called


@respx.mock
async def test_announcements_all_courses_reports_not_truncated():
    respx.get(f"{API}/courses").mock(
        return_value=httpx.Response(200, json=[{"id": 101}, {"id": 202}])
    )
    announcements_route = respx.get(f"{API}/announcements").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 5, "title": "Update", "message": "Hi", "context_code": "course_101"}],
        )
    )

    client = CanvasClient(CFG)
    result = await do_course_announcements(client)
    await client.aclose()

    assert announcements_route.calls[0].request.url.params.get_list("context_codes[]") == [
        "course_101",
        "course_202",
    ]
    assert [a["id"] for a in result["announcements"]] == [5]
    assert result["truncated"] is False


@respx.mock
async def test_announcements_reports_truncation_when_courses_exceed_max_pages():
    courses_base = f"{API}/courses"
    page3_courses = respx.get(courses_base, params={"page": "3"}).mock(
        return_value=httpx.Response(200, json=[{"id": 303}])
    )
    respx.get(courses_base, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 202}],
            headers={"Link": _link(f"{courses_base}?page=3")},
        )
    )
    respx.get(courses_base).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 101}],
            headers={"Link": _link(f"{courses_base}?page=2")},
        )
    )
    announcements_route = respx.get(f"{API}/announcements").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 5, "title": "Update", "message": "Hi", "context_code": "course_101"}],
        )
    )

    client = CanvasClient(SMALL)
    result = await do_course_announcements(client)
    await client.aclose()

    assert not page3_courses.called
    assert announcements_route.calls[0].request.url.params.get_list("context_codes[]") == [
        "course_101",
        "course_202",
    ]
    assert [a["id"] for a in result["announcements"]] == [5]
    assert result["truncated"] is True


@respx.mock
async def test_announcements_empty_active_courses_returns_envelope():
    respx.get(f"{API}/courses").mock(return_value=httpx.Response(200, json=[]))
    announcements_route = respx.get(f"{API}/announcements").mock(
        return_value=httpx.Response(200, json=[])
    )

    client = CanvasClient(CFG)
    result = await do_course_announcements(client)
    await client.aclose()

    assert result == {"announcements": [], "truncated": False}
    assert not announcements_route.called


@respx.mock
async def test_announcements_empty_codes_preserves_courses_truncation():
    courses_base = f"{API}/courses"
    page3_courses = respx.get(courses_base, params={"page": "3"}).mock(
        return_value=httpx.Response(200, json=[{"id": 303}])
    )
    page2_courses = respx.get(courses_base, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"name": "Missing id 2"}],
            headers={"Link": _link(f"{courses_base}?page=3")},
        )
    )
    respx.get(courses_base).mock(
        return_value=httpx.Response(
            200,
            json=[{"name": "Missing id 1"}],
            headers={"Link": _link(f"{courses_base}?page=2")},
        )
    )
    announcements_route = respx.get(f"{API}/announcements").mock(
        return_value=httpx.Response(200, json=[])
    )

    client = CanvasClient(SMALL)
    result = await do_course_announcements(client)
    await client.aclose()

    assert result == {"announcements": [], "truncated": True}
    assert page2_courses.called
    assert not announcements_route.called
    assert not page3_courses.called


@respx.mock
async def test_my_grades_preserves_truncation_when_filtered_course_not_on_fetched_pages():
    base = f"{API}/courses"
    page3 = respx.get(base, params={"page": "3"}).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 303, "name": "C", "enrollments": [{"type": "student", "computed_current_score": 90}]}
            ],
        )
    )
    respx.get(base, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 202, "name": "B", "enrollments": [{"type": "student", "computed_current_score": 80}]}
            ],
            headers={"Link": _link(f"{base}?page=3")},
        )
    )
    respx.get(base).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 101, "name": "A", "enrollments": [{"type": "student", "computed_current_score": 70}]}
            ],
            headers={"Link": _link(f"{base}?page=2")},
        )
    )

    client = CanvasClient(SMALL)
    result = await do_my_grades(client, course_id=303)
    await client.aclose()

    assert result == {"grades": [], "truncated": True}
    assert not page3.called


@respx.mock
async def test_announcements_reports_truncation_when_all_courses_announcements_exceed_max_pages():
    respx.get(f"{API}/courses").mock(
        return_value=httpx.Response(200, json=[{"id": 101}])
    )
    base = f"{API}/announcements"
    page3 = respx.get(base, params={"page": "3"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 3, "title": "A3", "message": "m3", "context_code": "course_101"}],
        )
    )
    respx.get(base, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 2, "title": "A2", "message": "m2", "context_code": "course_101"}],
            headers={"Link": _link(f"{base}?page=3")},
        )
    )
    respx.get(base).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "title": "A1", "message": "m1", "context_code": "course_101"}],
            headers={"Link": _link(f"{base}?page=2")},
        )
    )

    client = CanvasClient(SMALL)
    result = await do_course_announcements(client)
    await client.aclose()

    assert [a["id"] for a in result["announcements"]] == [1, 2]
    assert result["truncated"] is True
    assert not page3.called


@respx.mock
async def test_student_paginated_mcp_tools_return_truncated_envelope():
    respx.get(f"{API}/courses").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 101, "name": "A", "enrollments": [{"type": "student", "computed_current_score": 70}]}
            ],
        )
    )
    respx.get(f"{API}/courses/101/assignments").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "PS1"}])
    )
    respx.get(f"{API}/announcements").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 5, "title": "Update", "message": "Hi", "context_code": "course_101"}],
        )
    )

    client = CanvasClient(CFG)
    mcp = FastMCP("test-student")
    student_tools.register(mcp, lambda: client)
    try:
        async with Client(mcp) as mcp_client:
            grades_res = await mcp_client.call_tool("my_grades", {})
            assignments_res = await mcp_client.call_tool("list_assignments", {"course_id": 101})
            ann_res = await mcp_client.call_tool("course_announcements", {"course_id": 101})
    finally:
        await client.aclose()

    assert grades_res.is_error is False
    assert [g["course_id"] for g in grades_res.data["grades"]] == [101]
    assert grades_res.data["truncated"] is False

    assert assignments_res.is_error is False
    assert [a["id"] for a in assignments_res.data["assignments"]] == [1]
    assert assignments_res.data["truncated"] is False

    assert ann_res.is_error is False
    assert [a["id"] for a in ann_res.data["announcements"]] == [5]
    assert ann_res.data["truncated"] is False
