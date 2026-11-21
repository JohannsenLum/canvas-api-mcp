import pytest

from canvas_api_mcp.catalog import DEFAULT_CATALOG
from canvas_api_mcp.tools.gateway import do_search


@pytest.mark.parametrize(
    ("query", "path"),
    [
        ("what's due", "/v1/users/self/todo"),
        ("what is due this week", "/v1/users/self/todo"),
        ("what do I have coming up", "/v1/users/self/upcoming_events"),
        ("who am I", "/v1/users/{id}"),
        ("my group memberships", "/v1/users/self/groups"),
    ],
)
async def test_natural_queries_return_relevant_canvas_endpoints(monkeypatch, query, path):
    monkeypatch.setenv("CANVAS_CATALOG_PATH", str(DEFAULT_CATALOG))

    results = await do_search(query, limit=3)

    assert ("GET", path) in [(result["method"], result["path"]) for result in results]
