import json

import httpx
import respx

from canvas_api_mcp.catalog import build_catalog, fetch_raw_docs, parse_swagger, write_catalog

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

EXPECTED_ENTRIES = [
    {
        "family": "courses",
        "method": "GET",
        "path": "/v1/courses",
        "nickname": "courses_list_your_courses",
        "summary": "List your courses",
        "parameters": ["enrollment_state", "include"],
    }
]


@respx.mock
def test_build_catalog_flattens_operations():
    respx.get(f"{BASE}/doc/api/api-docs.json").mock(return_value=httpx.Response(200, json=INDEX))
    respx.get(f"{BASE}/doc/api/courses.json").mock(return_value=httpx.Response(200, json=COURSES))

    entries = build_catalog(BASE)

    assert entries == EXPECTED_ENTRIES


def test_build_catalog_is_importable_from_the_packaged_module():
    # scripts/build_catalog.py is excluded from the wheel (pyproject only
    # packages src/canvas_api_mcp), so regeneration has to live somewhere
    # that actually ships with pip/uvx installs. This is the regression
    # test for that: it fails if the logic ever moves back out of
    # canvas_api_mcp (see issue #9).
    import canvas_api_mcp.catalog as packaged

    assert packaged.build_catalog is build_catalog


def test_scripts_shim_still_reexports_build_catalog():
    # scripts/build_catalog.py is kept around for source checkouts and
    # must keep re-exporting the packaged implementation, not fork it.
    from scripts.build_catalog import build_catalog as shim_build_catalog

    assert shim_build_catalog is build_catalog


@respx.mock
def test_fetch_raw_docs_is_the_network_only_step():
    respx.get(f"{BASE}/doc/api/api-docs.json").mock(return_value=httpx.Response(200, json=INDEX))
    respx.get(f"{BASE}/doc/api/courses.json").mock(return_value=httpx.Response(200, json=COURSES))

    raw = fetch_raw_docs(BASE)

    assert raw == {"families": {"courses": COURSES}}


def test_parse_swagger_needs_no_network():
    # The fixture-only path: parse_swagger takes plain data, no respx.mock,
    # no httpx.Client, proving fetch and parse are genuinely separable.
    raw = {"families": {"courses": COURSES}}

    assert parse_swagger(raw) == EXPECTED_ENTRIES


def test_write_catalog_writes_readable_json(tmp_path):
    out = tmp_path / "nested" / "catalog.json"

    write_catalog(EXPECTED_ENTRIES, out)

    assert json.loads(out.read_text(encoding="utf-8")) == EXPECTED_ENTRIES


def test_regeneration_is_reachable_as_an_installed_console_script():
    """The catalog is a default, not the truth — a school on a different Canvas
    version must be able to regenerate it from a plain pip/uvx install.

    catalog.py's missing-catalog error names `canvas-api-mcp-build-catalog`, so if
    the entry point is absent the runtime tells users to run a command that does not
    exist. Importing the function proves nothing: the failure mode here is packaging,
    which only shows up once the distribution's metadata is what's being read.
    """
    from importlib.metadata import entry_points

    scripts = {ep.name: ep for ep in entry_points(group="console_scripts")}
    assert "canvas-api-mcp-build-catalog" in scripts, (
        "console script missing — `canvas-api-mcp-build-catalog` is advertised in "
        "catalog.py's error message but would be 'command not found' after install"
    )
    assert callable(scripts["canvas-api-mcp-build-catalog"].load())
