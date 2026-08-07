from canvas_api_mcp.catalog import load_catalog, search

ENTRIES = [
    {"family": "users", "method": "GET", "path": "/v1/users/self/todo",
     "nickname": "list_todo_items", "summary": "List the TODO items", "parameters": []},
    {"family": "courses", "method": "GET", "path": "/v1/courses",
     "nickname": "courses_list_your_courses", "summary": "List your courses",
     "parameters": ["enrollment_state"]},
    {"family": "courses", "method": "POST", "path": "/v1/courses/{course_id}/files",
     "nickname": "upload_file", "summary": "Upload a file to a course", "parameters": []},
]


def test_search_matches_summary_terms():
    results = search("todo items", entries=ENTRIES)
    assert results[0]["nickname"] == "list_todo_items"


def test_search_matches_path_fragments():
    results = search("courses", entries=ENTRIES)
    assert any(r["path"] == "/v1/courses" for r in results)


def test_method_filter_excludes_others():
    results = search("courses", method="POST", entries=ENTRIES)
    assert all(r["method"] == "POST" for r in results)
    assert len(results) == 1


def test_limit_caps_results():
    results = search("courses", limit=1, entries=ENTRIES)
    assert len(results) == 1


def test_no_match_returns_empty_list():
    assert search("zzzznotathing", entries=ENTRIES) == []


def test_shipped_catalog_loads_and_is_substantial():
    entries = load_catalog()
    assert len(entries) > 1000
    sample = entries[0]
    assert {"family", "method", "path", "nickname", "summary", "parameters"} <= set(sample)


def test_shipped_catalog_contains_the_todo_endpoint():
    entries = load_catalog()
    assert any(
        e["method"] == "GET" and e["path"] == "/v1/users/self/todo" for e in entries
    )
