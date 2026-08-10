import json

from canvas_api_mcp import catalog
from canvas_api_mcp.catalog import load_catalog, search

FIXTURE_ENTRY = {
    "family": "custom",
    "method": "GET",
    "path": "/v1/custom",
    "nickname": "custom_endpoint",
    "summary": "A fixture-only endpoint",
    "parameters": [],
}

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


def test_canvas_catalog_path_env_var_overrides_bundled_catalog(tmp_path, monkeypatch):
    custom = tmp_path / "custom-catalog.json"
    custom.write_text(json.dumps([FIXTURE_ENTRY]), encoding="utf-8")
    monkeypatch.setenv("CANVAS_CATALOG_PATH", str(custom))

    entries = load_catalog()

    assert entries == [FIXTURE_ENTRY]


def test_explicit_path_argument_wins_over_env_var(tmp_path, monkeypatch):
    env_catalog = tmp_path / "env-catalog.json"
    env_catalog.write_text(json.dumps([FIXTURE_ENTRY]), encoding="utf-8")
    monkeypatch.setenv("CANVAS_CATALOG_PATH", str(env_catalog))

    explicit_entry = {**FIXTURE_ENTRY, "nickname": "explicit_endpoint"}
    explicit = tmp_path / "explicit-catalog.json"
    explicit.write_text(json.dumps([explicit_entry]), encoding="utf-8")

    entries = load_catalog(explicit)

    assert entries == [explicit_entry]


def test_cache_dir_is_used_when_no_env_var_or_explicit_path(tmp_path, monkeypatch):
    monkeypatch.delenv("CANVAS_CATALOG_PATH", raising=False)
    cache_entry = {**FIXTURE_ENTRY, "nickname": "cache_endpoint"}
    cache_path = tmp_path / "cache-catalog.json"
    cache_path.write_text(json.dumps([cache_entry]), encoding="utf-8")
    monkeypatch.setattr(catalog, "CACHE_CATALOG_PATH", cache_path)

    entries = load_catalog()

    assert entries == [cache_entry]


def test_falls_back_to_bundled_catalog_when_nothing_else_present(tmp_path, monkeypatch):
    monkeypatch.delenv("CANVAS_CATALOG_PATH", raising=False)
    monkeypatch.setattr(catalog, "CACHE_CATALOG_PATH", tmp_path / "does-not-exist.json")

    entries = load_catalog()

    assert len(entries) > 1000
