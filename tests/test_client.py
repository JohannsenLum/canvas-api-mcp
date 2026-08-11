import httpx
import pytest
import respx

from canvas_api_mcp.client import CanvasClient, CanvasError
from canvas_api_mcp.config import Config

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)


def test_client_uses_config_timeout():
    cfg = Config(
        base_url="https://canvas.example.edu",
        token="tok",
        max_pages=10,
        timeout=12.5,
    )
    client = CanvasClient(cfg)
    # httpx.Timeout stores the scalar on connect/read/write/pool when given a float
    assert client._client.timeout.read == 12.5


@respx.mock
async def test_get_sends_bearer_token_and_returns_data():
    route = respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "CS3230"}])
    )
    client = CanvasClient(CFG)
    resp = await client.request("GET", "courses")
    await client.aclose()

    assert resp.data == [{"id": 1, "name": "CS3230"}]
    assert resp.pages_fetched == 1
    assert resp.truncated is False
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok"


@respx.mock
@pytest.mark.parametrize(
    "given",
    ["courses", "/courses", "/v1/courses", "/api/v1/courses"],
)
async def test_path_forms_all_resolve_to_the_same_url(given):
    route = respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    await client.request("GET", given)
    await client.aclose()
    assert route.called


@respx.mock
async def test_query_params_are_passed_through():
    route = respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    await client.request("GET", "courses", params={"enrollment_state": "active"})
    await client.aclose()
    assert route.calls[0].request.url.params["enrollment_state"] == "active"


@respx.mock
async def test_non_json_response_raises_canvas_error():
    respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, text="<html>login</html>")
    )
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert "not valid JSON" in str(exc.value)


# --- path normalisation -----------------------------------------------------
# _normalise_path is the only place a caller-supplied string becomes the URL a
# request is sent to, and canvas_request accepts arbitrary paths from a model,
# so these cases are about containment as much as correctness.


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # shorthand expands
        ("courses", "/api/v1/courses"),
        ("/courses", "/api/v1/courses"),
        ("/v1/courses", "/api/v1/courses"),
        ("/v1", "/api/v1"),
        # already explicit, passed through untouched
        ("/api/v1/courses", "/api/v1/courses"),
        ("/api/v1", "/api/v1"),
        ("/api/graphql", "/api/graphql"),
        ("/api", "/api"),
        # near-misses must NOT be treated as explicit
        ("/apifoo", "/api/v1/apifoo"),
        ("/v1foo", "/api/v1/v1foo"),
        # incidental whitespace and duplicate leading slashes
        ("  /courses  ", "/api/v1/courses"),
        ("//courses", "/api/v1/courses"),
    ],
)
def test_normalise_path_resolves_expected(given, expected):
    from canvas_api_mcp.client import _normalise_path

    assert _normalise_path(given) == expected


@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil.example.com/steal",   # absolute URL, would send the token elsewhere
        "http://evil.example.com/steal",
        "ftp://evil.example.com/steal",
        "/api/../../../etc/passwd",         # traversal out of /api
        "/v1/../../admin",
        "courses\r\nX-Injected: 1",         # header smuggling
        "courses\nHost: evil.example.com",
        "cour\\ses",                        # backslash
        "cour\x00ses",                      # NUL
        "",                                 # empty
        "   ",
    ],
)
def test_normalise_path_rejects_hostile_input(hostile):
    from canvas_api_mcp.client import CanvasError, _normalise_path

    with pytest.raises(CanvasError):
        _normalise_path(hostile)
