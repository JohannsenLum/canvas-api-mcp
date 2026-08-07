import httpx
import respx

from scripts.build_catalog import build_catalog

BASE = "https://canvas.example.edu"
INDEX = {"apis": [{"path": "/courses.json", "description": "Courses"}]}
COURSES = {
    "apis": [
        {
            "path": "/v1/courses",
            "operations": [
                {
                    "method": "GET",
                    "nickname": "courses_list_your_courses",
                    "summary": "List your courses",
                    "parameters": [
                        {"name": "enrollment_state"},
                        {"name": "include"},
                    ],
                }
            ],
        }
    ]
}


@respx.mock
def test_build_catalog_flattens_operations():
    respx.get(f"{BASE}/doc/api/api-docs.json").mock(return_value=httpx.Response(200, json=INDEX))
    respx.get(f"{BASE}/doc/api/courses.json").mock(return_value=httpx.Response(200, json=COURSES))

    entries = build_catalog(BASE)

    assert entries == [
        {
            "family": "courses",
            "method": "GET",
            "path": "/v1/courses",
            "nickname": "courses_list_your_courses",
            "summary": "List your courses",
            "parameters": ["enrollment_state", "include"],
        }
    ]
