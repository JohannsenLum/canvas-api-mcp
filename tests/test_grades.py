# tests/test_grades.py
import httpx
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.student import (
    do_course_announcements,
    do_get_assignment,
    do_list_assignments,
    do_my_grades,
    do_my_submission,
)

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
API = "https://canvas.example.edu/api/v1"


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
    grades = await do_my_grades(client)
    await client.aclose()

    assert grades == [{
        "course_id": 101, "course_name": "Algorithms",
        "current_score": 78.5, "current_grade": "B+", "final_score": 70.2,
    }]


@respx.mock
async def test_my_grades_filters_to_one_course():
    respx.get(f"{API}/courses").mock(
        return_value=httpx.Response(200, json=[
            {"id": 101, "name": "A", "enrollments": [{"type": "student", "computed_current_score": 1}]},
            {"id": 202, "name": "B", "enrollments": [{"type": "student", "computed_current_score": 2}]},
        ])
    )
    client = CanvasClient(CFG)
    grades = await do_my_grades(client, course_id=202)
    await client.aclose()

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
    grades = await do_my_grades(client)
    await client.aclose()

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
    items = await do_list_assignments(client, 101)
    await client.aclose()

    assert items[0]["submitted"] is True
    assert items[0]["score"] is None
    assert items[1]["score"] == 9.0


@respx.mock
async def test_list_assignments_passes_bucket_filter():
    route = respx.get(f"{API}/courses/101/assignments").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    await do_list_assignments(client, 101, bucket="overdue")
    await client.aclose()
    assert route.calls[0].request.url.params["bucket"] == "overdue"


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
    assert result["submission"]["submission_comments"][0]["comment"] == "nudge"
    assert result["submission"]["rubric_assessment"]["_123"]["points"] == 15
    assert result["submission"]["score"] == 15.0
    assert "note" not in result


@respx.mock
async def test_get_assignment_returns_note_when_submission_fetch_fails():
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
    assert "note" in result
    assert "submission comments/rubric" in result["note"]


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
    assert result["comments"][0]["comment"] == "Good work"


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
    items = await do_course_announcements(client, course_id=101)
    await client.aclose()

    assert items[0]["title"] == "Midterm venue"
    assert items[0]["course_id"] == 101
    assert "course_101" in route.calls[0].request.url.params.get_list("context_codes[]")
