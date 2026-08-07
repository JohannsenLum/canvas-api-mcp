# canvas-api-mcp Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MCP server that lets any AI agent read and act on a student's own Canvas LMS account, exposing 15 curated job-shaped tools plus a 2-tool gateway that reaches all 1,116 Canvas endpoints.

**Architecture:** Three layers over one HTTP client. `client.py` owns auth, RFC 5988 `Link` pagination, rate-limit throttling, and error translation — no tool touches HTTP directly. `catalog.py` holds a searchable index of every endpoint in the target Canvas instance's own Swagger spec. Tools are thin: they call the client, shape the response, and return plain dicts. Authorisation is never simulated — Canvas decides what a token may do and the server surfaces that answer.

**Tech Stack:** Python 3.11+, FastMCP 3.x, httpx, Pydantic, pytest + pytest-asyncio + respx, pypdf / python-pptx / python-docx for text extraction.

## Global Constraints

- Python 3.11+ (`requires-python = ">=3.11"`).
- Package name `canvas-api-mcp`; import package `canvas_api_mcp`; `src/` layout.
- MIT licence.
- No institution hardcoding. `CANVAS_BASE_URL` is required config with no default.
- Phase 1 is student-scoped. Do NOT add curated educator tools (grading, roster, extensions, announcements-as-teacher). Educator endpoints remain reachable only via the gateway.
- Every write tool carries `ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False)`.
- Every write tool's description states the concrete effect in its FIRST sentence.
- Rate-limit throttling in `client.py` is a compliance requirement. It must not be optional, removable, or bypassable by any tool.
- Pagination cap defaults to 10 pages (`CANVAS_MAX_PAGES`); truncation must be reported in the response, never silent.
- All async. Tools are `async def`.
- Follow the tool-declaration style already proven in `../nusmods-mcp/server.py`: `@mcp.tool(description=..., annotations=ToolAnnotations(...))` with `pydantic.Field` defaults for parameters.

---

### Task 1: Project scaffolding and configuration

**Files:**
- Create: `pyproject.toml`
- Create: `src/canvas_api_mcp/__init__.py`
- Create: `src/canvas_api_mcp/config.py`
- Create: `tests/__init__.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Config` dataclass with fields `base_url: str`, `token: str`, `max_pages: int`; classmethod `Config.from_env(env: Mapping[str, str]) -> Config`; exception `ConfigError(Exception)`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "canvas-api-mcp"
version = "0.1.0"
description = "MCP server for Canvas LMS — student tools plus full API gateway"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
    "fastmcp>=3.0",
    "httpx>=0.27",
    "pydantic>=2.0",
    "pypdf>=4.0",
    "python-pptx>=0.6",
    "python-docx>=1.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "respx>=0.21"]

[project.scripts]
canvas-api-mcp = "canvas_api_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/canvas_api_mcp"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_config.py
import pytest
from canvas_api_mcp.config import Config, ConfigError


def test_from_env_reads_required_values():
    cfg = Config.from_env({
        "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
        "CANVAS_TOKEN": "abc123",
    })
    assert cfg.base_url == "https://canvas.nus.edu.sg"
    assert cfg.token == "abc123"
    assert cfg.max_pages == 10


def test_strips_trailing_slash_and_api_suffix():
    cfg = Config.from_env({
        "CANVAS_BASE_URL": "https://canvas.nus.edu.sg/api/v1/",
        "CANVAS_TOKEN": "abc123",
    })
    assert cfg.base_url == "https://canvas.nus.edu.sg"


def test_missing_token_raises_actionable_error():
    with pytest.raises(ConfigError) as exc:
        Config.from_env({"CANVAS_BASE_URL": "https://canvas.nus.edu.sg"})
    assert "CANVAS_TOKEN" in str(exc.value)
    assert "profile/settings" in str(exc.value)


def test_missing_base_url_raises():
    with pytest.raises(ConfigError) as exc:
        Config.from_env({"CANVAS_TOKEN": "abc123"})
    assert "CANVAS_BASE_URL" in str(exc.value)


def test_rejects_non_https_base_url():
    with pytest.raises(ConfigError) as exc:
        Config.from_env({"CANVAS_BASE_URL": "http://canvas.nus.edu.sg", "CANVAS_TOKEN": "x"})
    assert "https" in str(exc.value).lower()


def test_max_pages_override():
    cfg = Config.from_env({
        "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
        "CANVAS_TOKEN": "abc123",
        "CANVAS_MAX_PAGES": "3",
    })
    assert cfg.max_pages == 3
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'canvas_api_mcp.config'`

- [ ] **Step 4: Write the implementation**

```python
# src/canvas_api_mcp/config.py
"""Configuration loading and validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

TOKEN_HELP = (
    "Create one in Canvas: Account -> Settings -> Approved Integrations -> "
    "'+ New access token'. Then set it in your MCP client config, e.g. "
    '"env": {"CANVAS_TOKEN": "..."} in ~/.claude.json. '
    "See <your-canvas>/profile/settings"
)


class ConfigError(Exception):
    """Raised when environment configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    base_url: str
    token: str
    max_pages: int = 10

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Config:
        base_url = (env.get("CANVAS_BASE_URL") or "").strip()
        if not base_url:
            raise ConfigError(
                "CANVAS_BASE_URL is not set. Set it to your institution's Canvas "
                "URL, e.g. https://canvas.nus.edu.sg"
            )

        # Accept a pasted API URL and normalise it back to the site root.
        base_url = base_url.rstrip("/")
        for suffix in ("/api/v1", "/api"):
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]
        base_url = base_url.rstrip("/")

        if not base_url.startswith("https://"):
            raise ConfigError(
                f"CANVAS_BASE_URL must use https, got: {base_url}. "
                "Access tokens are password-equivalent and must not travel over http."
            )

        token = (env.get("CANVAS_TOKEN") or "").strip()
        if not token:
            raise ConfigError(f"CANVAS_TOKEN is not set. {TOKEN_HELP}")

        raw_pages = (env.get("CANVAS_MAX_PAGES") or "10").strip()
        try:
            max_pages = int(raw_pages)
        except ValueError as exc:
            raise ConfigError(
                f"CANVAS_MAX_PAGES must be an integer, got: {raw_pages!r}"
            ) from exc
        if max_pages < 1:
            raise ConfigError("CANVAS_MAX_PAGES must be at least 1")

        return cls(base_url=base_url, token=token, max_pages=max_pages)

    @property
    def api_root(self) -> str:
        return f"{self.base_url}/api"
```

- [ ] **Step 5: Create the package init and tests init**

```python
# src/canvas_api_mcp/__init__.py
"""canvas-api-mcp — MCP server for Canvas LMS."""

__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS — 6 passed

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/canvas_api_mcp/__init__.py src/canvas_api_mcp/config.py tests/__init__.py tests/test_config.py
git commit -m "feat: project scaffolding and config validation"
```

---

### Task 2: HTTP client — auth and single GET

**Files:**
- Create: `src/canvas_api_mcp/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `Config` from Task 1.
- Produces:
  - `@dataclass CanvasResponse` with fields `data: Any`, `truncated: bool`, `pages_fetched: int`
  - `class CanvasError(Exception)` with attributes `status: int`, `message: str`, `hint: str`
  - `class CanvasClient` with `__init__(self, config: Config, transport: httpx.AsyncBaseTransport | None = None)`, `async def request(self, method: str, path: str, params: dict | None = None, json: dict | None = None, paginate: bool = True) -> CanvasResponse`, `async def aclose(self) -> None`
  - Path normalisation: `request` accepts `"courses"`, `"/courses"`, `"/v1/courses"`, or `"/api/v1/courses"` and resolves all to `{base_url}/api/v1/courses`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_client.py
import httpx
import pytest
import respx

from canvas_api_mcp.client import CanvasClient, CanvasError
from canvas_api_mcp.config import Config

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'canvas_api_mcp.client'`

- [ ] **Step 3: Write the implementation**

```python
# src/canvas_api_mcp/client.py
"""HTTP client for the Canvas REST API.

Owns authentication, pagination, rate limiting, and error translation.
No tool module should construct HTTP requests directly.
"""

from __future__ import annotations

import json as jsonlib
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Config


class CanvasError(Exception):
    """A Canvas API failure, translated into something actionable."""

    def __init__(self, status: int, message: str, hint: str = "") -> None:
        self.status = status
        self.message = message
        self.hint = hint
        super().__init__(f"{message} {hint}".strip())


@dataclass
class CanvasResponse:
    data: Any
    truncated: bool = False
    pages_fetched: int = 1


def _normalise_path(path: str) -> str:
    """Accept any of courses, /courses, /v1/courses, /api/v1/courses."""
    p = path.strip()
    if p.startswith("http://") or p.startswith("https://"):
        raise CanvasError(0, f"Path must be relative, got a full URL: {p}")
    p = "/" + p.lstrip("/")
    for prefix in ("/api/v1/", "/v1/"):
        if p.startswith(prefix):
            return "/api/v1/" + p[len(prefix):]
    if p.startswith("/api/"):
        return "/api/v1/" + p[len("/api/"):]
    return "/api/v1" + p


class CanvasClient:
    def __init__(
        self,
        config: Config,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={
                "Authorization": f"Bearer {config.token}",
                "Accept": "application/json",
            },
            timeout=30.0,
            transport=transport,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json: dict | None = None,
        paginate: bool = True,
    ) -> CanvasResponse:
        url = _normalise_path(path)
        response = await self._client.request(
            method.upper(), url, params=params, json=json
        )
        data = self._parse(response)
        return CanvasResponse(data=data, truncated=False, pages_fetched=1)

    def _parse(self, response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except (jsonlib.JSONDecodeError, ValueError) as exc:
            raise CanvasError(
                response.status_code,
                "Canvas returned a response that is not valid JSON.",
                "This usually means the request was redirected to a login page — "
                "check that CANVAS_TOKEN is set and has not expired.",
            ) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v`
Expected: PASS — 7 passed (4 parametrised cases plus 3)

- [ ] **Step 5: Commit**

```bash
git add src/canvas_api_mcp/client.py tests/test_client.py
git commit -m "feat: Canvas HTTP client with bearer auth and path normalisation"
```

---

### Task 3: Client — RFC 5988 Link-header pagination

**Files:**
- Modify: `src/canvas_api_mcp/client.py`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Consumes: `CanvasClient.request`, `CanvasResponse` from Task 2.
- Produces: `request(..., paginate=True)` merges list pages; `CanvasResponse.truncated` is `True` when the cap stopped a further page; helper `_next_link(response: httpx.Response) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pagination.py
import httpx
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
SMALL = Config(base_url="https://canvas.example.edu", token="tok", max_pages=2)
BASE = "https://canvas.example.edu/api/v1/courses"


def _link(url: str) -> str:
    return f'<{url}>; rel="next"'


@respx.mock
async def test_follows_next_links_and_merges_lists():
    respx.get(BASE, params={"page": "1"}).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}], headers={"Link": _link(f"{BASE}?page=2")}
        )
    )
    respx.get(BASE, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200, json=[{"id": 2}], headers={"Link": _link(f"{BASE}?page=3")}
        )
    )
    respx.get(BASE, params={"page": "3"}).mock(
        return_value=httpx.Response(200, json=[{"id": 3}])
    )

    client = CanvasClient(CFG)
    resp = await client.request("GET", "courses", params={"page": "1"})
    await client.aclose()

    assert resp.data == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert resp.pages_fetched == 3
    assert resp.truncated is False


@respx.mock
async def test_stops_at_max_pages_and_flags_truncation():
    respx.get(BASE, params={"page": "1"}).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}], headers={"Link": _link(f"{BASE}?page=2")}
        )
    )
    respx.get(BASE, params={"page": "2"}).mock(
        return_value=httpx.Response(
            200, json=[{"id": 2}], headers={"Link": _link(f"{BASE}?page=3")}
        )
    )

    client = CanvasClient(SMALL)
    resp = await client.request("GET", "courses", params={"page": "1"})
    await client.aclose()

    assert resp.data == [{"id": 1}, {"id": 2}]
    assert resp.pages_fetched == 2
    assert resp.truncated is True


@respx.mock
async def test_dict_response_is_not_paginated():
    respx.get("https://canvas.example.edu/api/v1/users/self").mock(
        return_value=httpx.Response(
            200,
            json={"id": 9},
            headers={"Link": _link(f"{BASE}?page=2")},
        )
    )
    client = CanvasClient(CFG)
    resp = await client.request("GET", "users/self")
    await client.aclose()

    assert resp.data == {"id": 9}
    assert resp.pages_fetched == 1
    assert resp.truncated is False


@respx.mock
async def test_paginate_false_returns_first_page_only():
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}], headers={"Link": _link(f"{BASE}?page=2")}
        )
    )
    client = CanvasClient(CFG)
    resp = await client.request("GET", "courses", paginate=False)
    await client.aclose()

    assert resp.data == [{"id": 1}]
    assert resp.pages_fetched == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pagination.py -v`
Expected: FAIL — `assert [{'id': 1}] == [{'id': 1}, {'id': 2}, {'id': 3}]`

- [ ] **Step 3: Add the `_next_link` helper to `client.py`**

Insert after `_normalise_path`:

```python
def _next_link(response: httpx.Response) -> str | None:
    """Parse the RFC 5988 Link header and return the rel="next" URL."""
    header = response.headers.get("Link")
    if not header:
        return None
    for part in header.split(","):
        segments = part.split(";")
        if len(segments) < 2:
            continue
        url = segments[0].strip()
        if not (url.startswith("<") and url.endswith(">")):
            continue
        for attr in segments[1:]:
            key, _, value = attr.strip().partition("=")
            if key.strip() == "rel" and value.strip().strip('"') == "next":
                return url[1:-1]
    return None
```

- [ ] **Step 4: Replace `CanvasClient.request` with the paginating version**

```python
    async def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json: dict | None = None,
        paginate: bool = True,
    ) -> CanvasResponse:
        url: str | None = _normalise_path(path)
        query: dict | None = params
        merged: list[Any] = []
        first: Any = None
        pages = 0
        truncated = False

        while url is not None:
            response = await self._client.request(
                method.upper(), url, params=query, json=json
            )
            payload = self._parse(response)
            pages += 1

            if pages == 1:
                first = payload
            if isinstance(payload, list):
                merged.extend(payload)

            # Only list responses paginate. Subsequent pages carry their full
            # query string in the Link URL, so params must not be re-sent.
            if not paginate or not isinstance(payload, list):
                break

            next_url = _next_link(response)
            if next_url is None:
                break
            if pages >= self._config.max_pages:
                truncated = True
                break
            url, query, json = next_url, None, None

        data = merged if isinstance(first, list) else first
        return CanvasResponse(data=data, truncated=truncated, pages_fetched=pages)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all config, client, and pagination tests green

- [ ] **Step 6: Commit**

```bash
git add src/canvas_api_mcp/client.py tests/test_pagination.py
git commit -m "feat: follow RFC 5988 Link pagination with explicit truncation"
```

---

### Task 4: Client — error translation

**Files:**
- Modify: `src/canvas_api_mcp/client.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: `CanvasError`, `CanvasClient` from Task 2.
- Produces: `CanvasClient._raise_for_status(response: httpx.Response) -> None`, called before `_parse` on every response. `CanvasError.hint` carries the actionable half.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_errors.py
import httpx
import pytest
import respx

from canvas_api_mcp.client import CanvasClient, CanvasError
from canvas_api_mcp.config import Config

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
URL = "https://canvas.example.edu/api/v1/courses"


@respx.mock
async def test_401_explains_token_problem():
    respx.get(URL).mock(return_value=httpx.Response(401, json={"errors": [{"message": "user authorisation required"}]}))
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert exc.value.status == 401
    assert "token" in str(exc.value).lower()
    assert "New access token" in str(exc.value)


@respx.mock
async def test_permission_403_is_not_confused_with_rate_limit():
    respx.get(URL).mock(return_value=httpx.Response(403, json={"status": "unauthorized"}))
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert exc.value.status == 403
    assert "permission" in str(exc.value).lower()
    assert "rate limit" not in str(exc.value).lower()


@respx.mock
async def test_rate_limit_403_is_identified_by_body():
    respx.get(URL).mock(return_value=httpx.Response(403, text="403 Forbidden (Rate Limit Exceeded)"))
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert "rate limit" in str(exc.value).lower()


@respx.mock
async def test_404_mentions_visibility_and_feature_availability():
    respx.get(URL).mock(return_value=httpx.Response(404, json={"errors": [{"message": "The specified resource does not exist."}]}))
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert exc.value.status == 404
    message = str(exc.value).lower()
    assert "visible" in message or "enabled" in message


@respx.mock
async def test_500_reports_server_side_failure():
    respx.get(URL).mock(return_value=httpx.Response(500, text="boom"))
    client = CanvasClient(CFG)
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert exc.value.status == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_errors.py -v`
Expected: FAIL — no `CanvasError` raised; the 401 body parses as JSON and is returned as data

- [ ] **Step 3: Add rate-limit detection and status translation to `client.py`**

Add near the top, after the imports:

```python
RATE_LIMIT_MARKER = "rate limit exceeded"


def _is_rate_limited(response: httpx.Response) -> bool:
    """Canvas signals throttling with a 403 whose body names the rate limit."""
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    return RATE_LIMIT_MARKER in response.text.lower()
```

Add this method to `CanvasClient`:

```python
    @staticmethod
    def _canvas_message(response: httpx.Response) -> str:
        try:
            body = response.json()
        except Exception:
            return response.text.strip()[:300]
        if isinstance(body, dict):
            errors = body.get("errors")
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, dict) and "message" in first:
                    return str(first["message"])
            if isinstance(errors, dict) and "message" in errors:
                return str(errors["message"])
            for key in ("message", "error", "status"):
                if key in body:
                    return str(body[key])
        return response.text.strip()[:300]

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return

        detail = self._canvas_message(response)

        if _is_rate_limited(response):
            raise CanvasError(
                status,
                "Canvas rate limit exceeded.",
                "The client throttles automatically; this means the account's quota "
                "is exhausted. Wait a minute before retrying.",
            )

        if status == 401:
            raise CanvasError(
                status,
                f"Canvas rejected the access token ({detail}).",
                "The token is missing, invalid, or expired. Generate a new one at "
                "<your-canvas>/profile/settings -> Approved Integrations -> "
                "'+ New access token', then update CANVAS_TOKEN in your MCP client config.",
            )

        if status == 403:
            raise CanvasError(
                status,
                f"Canvas denied permission for this request ({detail}).",
                "Your account does not have rights to this resource. Educator and "
                "admin endpoints require a teacher or admin enrolment.",
            )

        if status == 404:
            raise CanvasError(
                status,
                f"Canvas returned not found ({detail}).",
                "The resource does not exist, is not visible to your account, or the "
                "feature is not enabled at this institution.",
            )

        if 500 <= status < 600:
            raise CanvasError(
                status, f"Canvas server error ({detail}).", "This is a Canvas-side failure."
            )

        raise CanvasError(status, f"Canvas request failed ({detail}).")
```

- [ ] **Step 4: Call `_raise_for_status` from the request loop**

In `request`, insert immediately after the `response = await self._client.request(...)` line and before `payload = self._parse(response)`:

```python
            self._raise_for_status(response)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all tests green

- [ ] **Step 6: Commit**

```bash
git add src/canvas_api_mcp/client.py tests/test_errors.py
git commit -m "feat: translate Canvas errors into actionable messages"
```

---

### Task 5: Client — rate-limit throttling and retries

**Files:**
- Modify: `src/canvas_api_mcp/client.py`
- Test: `tests/test_throttle.py`

**Interfaces:**
- Consumes: everything from Tasks 2–4.
- Produces: `CanvasClient.__init__` gains `sleep: Callable[[float], Awaitable[None]] | None = None` (defaults to `asyncio.sleep`; tests inject a recorder). Retries: up to 3 attempts on 429 and 5xx with exponential backoff (0.5s, 1s, 2s). Throttle: when `X-Rate-Limit-Remaining` drops below 100, sleep 1.0s before the next request.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_throttle.py
import httpx
import pytest
import respx

from canvas_api_mcp.client import CanvasClient, CanvasError
from canvas_api_mcp.config import Config

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
URL = "https://canvas.example.edu/api/v1/courses"


def make_client():
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    return CanvasClient(CFG, sleep=fake_sleep), slept


@respx.mock
async def test_retries_on_500_then_succeeds():
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(500, text="boom"),
            httpx.Response(200, json=[{"id": 1}]),
        ]
    )
    client, slept = make_client()
    resp = await client.request("GET", "courses")
    await client.aclose()

    assert resp.data == [{"id": 1}]
    assert slept == [0.5]


@respx.mock
async def test_retries_on_429_then_succeeds():
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, text="Rate Limit Exceeded"),
            httpx.Response(200, json=[]),
        ]
    )
    client, slept = make_client()
    await client.request("GET", "courses")
    await client.aclose()
    assert slept == [0.5]


@respx.mock
async def test_gives_up_after_three_attempts():
    respx.get(URL).mock(return_value=httpx.Response(500, text="boom"))
    client, slept = make_client()
    with pytest.raises(CanvasError) as exc:
        await client.request("GET", "courses")
    await client.aclose()
    assert exc.value.status == 500
    assert slept == [0.5, 1.0]


@respx.mock
async def test_does_not_retry_on_404():
    route = respx.get(URL).mock(return_value=httpx.Response(404, json={}))
    client, slept = make_client()
    with pytest.raises(CanvasError):
        await client.request("GET", "courses")
    await client.aclose()
    assert route.call_count == 1
    assert slept == []


@respx.mock
async def test_throttles_when_quota_is_nearly_exhausted():
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, json=[], headers={"X-Rate-Limit-Remaining": "42.0"}
        )
    )
    client, slept = make_client()
    await client.request("GET", "courses")
    await client.request("GET", "courses")
    await client.aclose()
    # First response reports low quota; the second request pauses first.
    assert 1.0 in slept


@respx.mock
async def test_no_throttle_when_quota_is_healthy():
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, json=[], headers={"X-Rate-Limit-Remaining": "600.0"}
        )
    )
    client, slept = make_client()
    await client.request("GET", "courses")
    await client.request("GET", "courses")
    await client.aclose()
    assert slept == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_throttle.py -v`
Expected: FAIL — `TypeError: CanvasClient.__init__() got an unexpected keyword argument 'sleep'`

- [ ] **Step 3: Add throttling state to `CanvasClient.__init__`**

Add `import asyncio` and `from collections.abc import Awaitable, Callable` to the imports, then add these module constants after `RATE_LIMIT_MARKER`:

```python
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0.5, 1.0)
LOW_QUOTA_THRESHOLD = 100.0
THROTTLE_PAUSE_SECONDS = 1.0
```

Replace the `__init__` signature and body with:

```python
    def __init__(
        self,
        config: Config,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._sleep = sleep or asyncio.sleep
        self._quota_low = False
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={
                "Authorization": f"Bearer {config.token}",
                "Accept": "application/json",
            },
            timeout=30.0,
            transport=transport,
            follow_redirects=True,
        )
```

- [ ] **Step 4: Add the send-with-retry method**

```python
    def _note_quota(self, response: httpx.Response) -> None:
        raw = response.headers.get("X-Rate-Limit-Remaining")
        if raw is None:
            return
        try:
            self._quota_low = float(raw) < LOW_QUOTA_THRESHOLD
        except ValueError:
            self._quota_low = False

    async def _send(
        self, method: str, url: str, params: dict | None, json: dict | None
    ) -> httpx.Response:
        """Send one request, honouring throttle state and retrying transient failures."""
        for attempt in range(MAX_ATTEMPTS):
            if self._quota_low:
                await self._sleep(THROTTLE_PAUSE_SECONDS)

            response = await self._client.request(method, url, params=params, json=json)
            self._note_quota(response)

            transient = response.status_code >= 500 or _is_rate_limited(response)
            if transient and attempt < MAX_ATTEMPTS - 1:
                await self._sleep(BACKOFF_SECONDS[attempt])
                continue
            return response

        return response  # pragma: no cover - loop always returns
```

- [ ] **Step 5: Route the request loop through `_send`**

In `request`, replace:

```python
            response = await self._client.request(
                method.upper(), url, params=query, json=json
            )
```

with:

```python
            response = await self._send(method.upper(), url, query, json)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all tests green

- [ ] **Step 7: Commit**

```bash
git add src/canvas_api_mcp/client.py tests/test_throttle.py
git commit -m "feat: rate-limit throttling and transient-failure retries"
```

---

### Task 6: Catalog build script

**Files:**
- Create: `scripts/build_catalog.py`
- Create: `data/catalog.json` (generated output, committed)
- Test: `tests/test_build_catalog.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone script, sync `httpx`).
- Produces: `build_catalog(base_url: str) -> list[dict]` returning entries shaped `{"family": str, "method": str, "path": str, "nickname": str, "summary": str, "parameters": list[str]}`; CLI `python scripts/build_catalog.py <base_url> [-o data/catalog.json]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build_catalog.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_build_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts'`

- [ ] **Step 3: Write the script**

Create `scripts/__init__.py` (empty) and `scripts/build_catalog.py`:

```python
#!/usr/bin/env python3
"""Build the Canvas endpoint catalog from an instance's own Swagger spec.

Every Canvas instance serves its API docs at /doc/api/api-docs.json, so the
catalog matches that deployment's version and enabled feature set exactly.

Usage:
    python scripts/build_catalog.py https://canvas.nus.edu.sg -o data/catalog.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

DOC_ROOT = "/doc/api"


def build_catalog(base_url: str, timeout: float = 40.0) -> list[dict]:
    base = base_url.rstrip("/")
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        index = client.get(f"{base}{DOC_ROOT}/api-docs.json").raise_for_status().json()

        entries: list[dict] = []
        for resource in index.get("apis", []):
            rel = resource.get("path", "")
            if not rel:
                continue
            family = rel.lstrip("/").removesuffix(".json")
            spec = client.get(f"{base}{DOC_ROOT}{rel}").raise_for_status().json()

            for api in spec.get("apis", []):
                path = api.get("path", "")
                for op in api.get("operations", []):
                    entries.append(
                        {
                            "family": family,
                            "method": op.get("method", "").upper(),
                            "path": path,
                            "nickname": op.get("nickname", ""),
                            "summary": (op.get("summary") or "").strip(),
                            "parameters": [
                                p.get("name", "")
                                for p in op.get("parameters", [])
                                if p.get("name")
                            ],
                        }
                    )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="e.g. https://canvas.nus.edu.sg")
    parser.add_argument("-o", "--output", default="data/catalog.json")
    args = parser.parse_args()

    entries = build_catalog(args.base_url)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    print(f"wrote {len(entries)} endpoints to {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_build_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Generate the shipped catalog**

Run: `uv run python scripts/build_catalog.py https://canvas.nus.edu.sg -o data/catalog.json`
Expected: `wrote 1116 endpoints to data/catalog.json` (count may differ if NUS has upgraded Canvas — any count above 1000 is healthy)

- [ ] **Step 6: Remove the superseded design-time snapshot**

```bash
git rm data/catalog-nus-2026-08-07.json
```

- [ ] **Step 7: Commit**

```bash
git add scripts/__init__.py scripts/build_catalog.py data/catalog.json tests/test_build_catalog.py
git commit -m "feat: generate endpoint catalog from a Canvas instance's own spec"
```

---

### Task 7: Catalog loading and search

**Files:**
- Create: `src/canvas_api_mcp/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `data/catalog.json` from Task 6.
- Produces: `load_catalog(path: Path | None = None) -> list[dict]` (cached via `functools.lru_cache`); `search(query: str, method: str | None = None, limit: int = 10, entries: list[dict] | None = None) -> list[dict]` returning catalog entries ordered best-match first.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'canvas_api_mcp.catalog'`

- [ ] **Step 3: Write the implementation**

```python
# src/canvas_api_mcp/catalog.py
"""Searchable index of every endpoint in the target Canvas instance."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "data" / "catalog.json"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@lru_cache(maxsize=4)
def _load(path_str: str) -> tuple[dict, ...]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(
            f"Endpoint catalog not found at {path}. Regenerate it with: "
            "python scripts/build_catalog.py <your-canvas-base-url>"
        )
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def load_catalog(path: Path | None = None) -> list[dict]:
    return list(_load(str(path or DEFAULT_CATALOG)))


def _score(entry: dict, terms: list[str]) -> int:
    """Weight nickname matches highest, then summary, then path."""
    nickname = " ".join(_tokens(entry.get("nickname", "")))
    summary = " ".join(_tokens(entry.get("summary", "")))
    path = " ".join(_tokens(entry.get("path", "")))
    family = " ".join(_tokens(entry.get("family", "")))

    total = 0
    for term in terms:
        if term in nickname.split():
            total += 5
        elif term in nickname:
            total += 3
        if term in summary.split():
            total += 3
        if term in path.split():
            total += 2
        if term in family.split():
            total += 2
    return total


def search(
    query: str,
    method: str | None = None,
    limit: int = 10,
    entries: list[dict] | None = None,
) -> list[dict]:
    pool = entries if entries is not None else load_catalog()
    if method:
        wanted = method.upper()
        pool = [e for e in pool if e.get("method", "").upper() == wanted]

    terms = _tokens(query)
    if not terms:
        return []

    scored = [(s, e) for e in pool if (s := _score(e, terms)) > 0]
    scored.sort(key=lambda pair: (-pair[0], len(pair[1].get("path", ""))))
    return [entry for _, entry in scored[:limit]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/canvas_api_mcp/catalog.py tests/test_catalog.py
git commit -m "feat: catalog loading and ranked endpoint search"
```

---

### Task 8: Server skeleton and gateway tools

**Files:**
- Create: `src/canvas_api_mcp/server.py`
- Create: `src/canvas_api_mcp/tools/__init__.py`
- Create: `src/canvas_api_mcp/tools/gateway.py`
- Test: `tests/test_gateway.py`

**Interfaces:**
- Consumes: `Config`, `CanvasClient`, `CanvasError`, `catalog.search`.
- Produces:
  - `server.py`: module-level `mcp: FastMCP`, `get_client() -> CanvasClient` (lazy singleton built from `Config.from_env(os.environ)`), `main() -> None` calling `mcp.run()`.
  - `tools/gateway.py`: `register(mcp: FastMCP, get_client) -> None` registering `search_canvas_api` and `canvas_request`.
  - Underlying testable functions: `async def do_search(query, method=None, limit=10) -> list[dict]` and `async def do_request(client, method, path, params=None, body=None, dry_run=False) -> dict`.

At the end of this task the server is already useful: it can reach all 1,116 endpoints.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gateway.py
import httpx
import pytest
import respx

from canvas_api_mcp.client import CanvasClient, CanvasError
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.gateway import do_request, do_search

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)


async def test_do_search_finds_the_todo_endpoint():
    results = await do_search("what is due todo items")
    assert any(r["path"] == "/v1/users/self/todo" for r in results)


async def test_do_search_respects_method_filter():
    results = await do_search("courses", method="POST", limit=5)
    assert all(r["method"] == "POST" for r in results)


async def test_dry_run_does_not_send_a_request():
    with respx.mock:
        route = respx.get("https://canvas.example.edu/api/v1/courses").mock(
            return_value=httpx.Response(200, json=[])
        )
        client = CanvasClient(CFG)
        result = await do_request(client, "GET", "courses", dry_run=True)
        await client.aclose()

    assert route.called is False
    assert result["dry_run"] is True
    assert result["method"] == "GET"
    assert result["url"] == "https://canvas.example.edu/api/v1/courses"


@respx.mock
async def test_request_executes_and_reports_truncation():
    respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[{"id": 1}])
    )
    client = CanvasClient(CFG)
    result = await do_request(client, "GET", "courses")
    await client.aclose()

    assert result["data"] == [{"id": 1}]
    assert result["truncated"] is False


@respx.mock
async def test_request_surfaces_canvas_error_as_structured_result():
    respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(403, json={"status": "unauthorized"})
    )
    client = CanvasClient(CFG)
    result = await do_request(client, "GET", "courses")
    await client.aclose()

    assert result["error"] is True
    assert result["status"] == 403
    assert "permission" in result["message"].lower()


async def test_rejects_unknown_http_method():
    client = CanvasClient(CFG)
    result = await do_request(client, "FETCH", "courses")
    await client.aclose()
    assert result["error"] is True
    assert "method" in result["message"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gateway.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'canvas_api_mcp.tools'`

- [ ] **Step 3: Write `tools/gateway.py`**

Create `src/canvas_api_mcp/tools/__init__.py` (empty), then:

```python
# src/canvas_api_mcp/tools/gateway.py
"""Layer 2 and 3: endpoint discovery and generic passthrough.

Together these reach every endpoint the Canvas instance exposes. What they
are permitted to do is decided by Canvas, per token — never by this server.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .. import catalog
from ..client import CanvasClient, CanvasError, _normalise_path

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


async def do_search(query: str, method: str | None = None, limit: int = 10) -> list[dict]:
    return catalog.search(query, method=method, limit=limit)


async def do_request(
    client: CanvasClient,
    method: str,
    path: str,
    params: dict | None = None,
    body: dict | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    verb = method.upper().strip()
    if verb not in ALLOWED_METHODS:
        return {
            "error": True,
            "status": 0,
            "message": (
                f"Unsupported HTTP method {method!r}. "
                f"Use one of: {', '.join(sorted(ALLOWED_METHODS))}."
            ),
        }

    try:
        normalised = _normalise_path(path)
    except CanvasError as exc:
        return {"error": True, "status": 0, "message": exc.message, "hint": exc.hint}

    if dry_run:
        return {
            "dry_run": True,
            "method": verb,
            "url": f"{client._config.base_url}{normalised}",
            "params": params or {},
            "body": body or {},
        }

    try:
        response = await client.request(verb, path, params=params, json=body)
    except CanvasError as exc:
        return {
            "error": True,
            "status": exc.status,
            "message": exc.message,
            "hint": exc.hint,
        }

    return {
        "data": response.data,
        "truncated": response.truncated,
        "pages_fetched": response.pages_fetched,
    }


def register(mcp: FastMCP, get_client) -> None:
    @mcp.tool(
        description=(
            "Search all Canvas API endpoints by keyword. Use this to find the right "
            "endpoint for anything the curated tools do not cover, then execute it "
            "with canvas_request. Returns method, path, summary, and parameter names."
        ),
        annotations=ToolAnnotations(
            title="Search Canvas API",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def search_canvas_api(
        query: str = Field(description="Keywords, e.g. 'group membership' or 'quiz submission'"),
        method: str | None = Field(default=None, description="Optional filter: GET, POST, PUT, PATCH, DELETE"),
        limit: int = Field(default=10, description="Maximum results to return"),
    ) -> list[dict]:
        """Find Canvas endpoints matching a keyword query."""
        return await do_search(query, method=method, limit=limit)

    @mcp.tool(
        description=(
            "Executes any Canvas API endpoint directly. Non-GET methods CREATE, MODIFY, "
            "or DELETE real data in Canvas immediately and cannot be undone from here. "
            "Find endpoints with search_canvas_api first. Set dry_run=true to preview the "
            "prepared request without sending it. What this is permitted to do is decided "
            "by Canvas based on your account's role."
        ),
        annotations=ToolAnnotations(
            title="Canvas API Request",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def canvas_request(
        method: str = Field(description="GET, POST, PUT, PATCH, or DELETE"),
        path: str = Field(description="Endpoint path, e.g. '/v1/users/self/groups' or 'courses/123/assignments'"),
        params: dict | None = Field(default=None, description="Query string parameters"),
        body: dict | None = Field(default=None, description="JSON request body for write methods"),
        dry_run: bool = Field(default=False, description="Return the prepared request without sending it"),
    ) -> dict:
        """Execute an arbitrary Canvas API request."""
        return await do_request(
            get_client(), method, path, params=params, body=body, dry_run=dry_run
        )
```

- [ ] **Step 4: Write `server.py`**

```python
# src/canvas_api_mcp/server.py
"""FastMCP server entrypoint."""

from __future__ import annotations

import os

from fastmcp import FastMCP

from .client import CanvasClient
from .config import Config
from .tools import gateway

mcp = FastMCP(
    "Canvas",
    instructions=(
        "You are a Canvas LMS assistant operating on the user's own account via the "
        "Canvas REST API. Prefer the curated tools for everyday questions — whats_due, "
        "my_courses, my_grades. For anything they do not cover, use search_canvas_api "
        "to find the right endpoint and canvas_request to execute it. "
        "Permissions are enforced by Canvas per access token: a 403 means the account "
        "lacks that role, not that the request was malformed. Never guess at grades or "
        "deadlines — always read them from a tool result."
    ),
)

_client: CanvasClient | None = None


def get_client() -> CanvasClient:
    """Lazily build the shared client so config errors surface on first tool use."""
    global _client
    if _client is None:
        _client = CanvasClient(Config.from_env(os.environ))
    return _client


gateway.register(mcp, get_client)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all tests green

- [ ] **Step 6: Verify the server speaks MCP end to end**

```bash
CANVAS_BASE_URL=https://canvas.example.edu CANVAS_TOKEN=dummy \
uv run python -c "
import json, subprocess, os
msgs = [
  {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'t','version':'1'}}},
  {'jsonrpc':'2.0','method':'notifications/initialized'},
  {'jsonrpc':'2.0','id':2,'method':'tools/list'},
]
p = subprocess.run(['python','-m','canvas_api_mcp.server'],
    input='\n'.join(json.dumps(m) for m in msgs), capture_output=True, text=True, timeout=20, env=os.environ)
for line in p.stdout.splitlines():
    m = json.loads(line)
    if m.get('id') == 2:
        print([t['name'] for t in m['result']['tools']])
"
```

Expected: `['search_canvas_api', 'canvas_request']`

- [ ] **Step 7: Commit**

```bash
git add src/canvas_api_mcp/server.py src/canvas_api_mcp/tools/ tests/test_gateway.py
git commit -m "feat: FastMCP server with endpoint search and generic gateway"
```

---

### Task 9: Identity and orientation tools

**Files:**
- Create: `src/canvas_api_mcp/identity.py`
- Create: `src/canvas_api_mcp/tools/orientation.py`
- Modify: `src/canvas_api_mcp/server.py`
- Test: `tests/test_orientation.py`

**Interfaces:**
- Consumes: `CanvasClient`, `CanvasError`.
- Produces:
  - `identity.py`: `async def fetch_identity(client: CanvasClient) -> dict` returning `{"id": int, "name": str, "login_id": str | None, "roles_by_course": dict[int, list[str]]}`; `clear_cache() -> None`.
  - `tools/orientation.py`: `async def do_whoami(client) -> dict`, `async def do_my_courses(client, state="active") -> list[dict]`, `register(mcp, get_client) -> None`.
- `do_my_courses` returns entries shaped `{"id", "name", "course_code", "term", "roles"}`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orientation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'canvas_api_mcp.identity'`

- [ ] **Step 3: Write `identity.py`**

```python
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

    profile = (await client.request("GET", "users/self")).data or {}
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
        "roles_by_course": roles_by_course,
    }
    return _cache
```

- [ ] **Step 4: Write `tools/orientation.py`**

```python
# src/canvas_api_mcp/tools/orientation.py
"""Who am I, and what am I enrolled in."""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import CanvasClient
from ..identity import fetch_identity

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)


async def do_whoami(client: CanvasClient) -> dict:
    return await fetch_identity(client)


async def do_my_courses(client: CanvasClient, state: str = "active") -> list[dict]:
    response = await client.request(
        "GET",
        "courses",
        params={"enrollment_state": state, "include[]": ["term"], "per_page": 100},
    )
    courses = response.data or []
    shaped = []
    for course in courses:
        term = course.get("term") or {}
        shaped.append(
            {
                "id": course.get("id"),
                "name": course.get("name"),
                "course_code": course.get("course_code"),
                "term": term.get("name"),
                "roles": [e.get("type") for e in course.get("enrollments", []) if e.get("type")],
            }
        )
    return shaped


def register(mcp: FastMCP, get_client) -> None:
    @mcp.tool(
        description=(
            "Identify the Canvas account this server is authenticated as, including "
            "the user's name and their role in each course (student, ta, teacher). "
            "Call this first when you need to know what the user can access."
        ),
        annotations=ToolAnnotations(title="Who Am I", **READ_ONLY.model_dump(exclude={"title"})),
    )
    async def whoami() -> dict:
        """Return the authenticated user's identity and per-course roles."""
        return await do_whoami(get_client())

    @mcp.tool(
        description=(
            "List the user's Canvas courses with course code, term, and their role in "
            "each. Use this to resolve a course name or code to the course_id that "
            "other tools require."
        ),
        annotations=ToolAnnotations(title="My Courses", **READ_ONLY.model_dump(exclude={"title"})),
    )
    async def my_courses(
        state: str = Field(default="active", description="Enrollment state: active, completed, or invited"),
    ) -> list[dict]:
        """List enrolled courses."""
        return await do_my_courses(get_client(), state=state)
```

- [ ] **Step 5: Register the module in `server.py`**

Change the import line:

```python
from .tools import gateway, orientation
```

and add below `gateway.register(mcp, get_client)`:

```python
orientation.register(mcp, get_client)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all tests green

- [ ] **Step 7: Commit**

```bash
git add src/canvas_api_mcp/identity.py src/canvas_api_mcp/tools/orientation.py src/canvas_api_mcp/server.py tests/test_orientation.py
git commit -m "feat: whoami and my_courses with per-course role detection"
```

---

### Task 10: whats_due

**Files:**
- Create: `src/canvas_api_mcp/tools/student.py`
- Modify: `src/canvas_api_mcp/server.py`
- Test: `tests/test_whats_due.py`

**Interfaces:**
- Consumes: `CanvasClient`.
- Produces: `async def do_whats_due(client, days: int = 14) -> dict` returning `{"items": list[dict], "days": int}` where each item is `{"title", "type", "due_at", "course_id", "course_name", "html_url", "submitted"}`, sorted by `due_at` ascending with unknown dates last. `register(mcp, get_client)` registers `whats_due`.

This is the highest-frequency tool in the server. It merges `/users/self/todo` and `/users/self/upcoming_events` and de-duplicates, because "what's due?" means both.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_whats_due.py
import httpx
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.student import do_whats_due

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)

TODO = [
    {
        "type": "submitting",
        "assignment": {
            "id": 1, "name": "Problem Set 3", "due_at": "2026-08-12T15:59:00Z",
            "course_id": 101, "html_url": "https://c/1",
        },
    }
]
UPCOMING = [
    {
        "id": "assignment_1",
        "title": "Problem Set 3",
        "type": "assignment",
        "assignment": {"id": 1, "due_at": "2026-08-12T15:59:00Z", "course_id": 101},
        "html_url": "https://c/1",
    },
    {
        "id": "event_9",
        "title": "Lab Session",
        "type": "event",
        "start_at": "2026-08-09T02:00:00Z",
        "context_code": "course_101",
        "html_url": "https://c/9",
    },
]


def _mock_all(todo=None, upcoming=None):
    respx.get("https://canvas.example.edu/api/v1/users/self/todo").mock(
        return_value=httpx.Response(200, json=todo if todo is not None else TODO)
    )
    respx.get("https://canvas.example.edu/api/v1/users/self/upcoming_events").mock(
        return_value=httpx.Response(200, json=upcoming if upcoming is not None else UPCOMING)
    )


@respx.mock
async def test_merges_both_sources_and_sorts_by_due_date():
    _mock_all()
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    titles = [i["title"] for i in result["items"]]
    assert titles == ["Lab Session", "Problem Set 3"]


@respx.mock
async def test_deduplicates_the_same_assignment_from_both_sources():
    _mock_all()
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    assert sum(1 for i in result["items"] if i["title"] == "Problem Set 3") == 1


@respx.mock
async def test_items_carry_course_id_and_url():
    _mock_all()
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    ps3 = next(i for i in result["items"] if i["title"] == "Problem Set 3")
    assert ps3["course_id"] == 101
    assert ps3["html_url"] == "https://c/1"
    assert ps3["due_at"] == "2026-08-12T15:59:00Z"


@respx.mock
async def test_empty_sources_return_empty_list_not_error():
    _mock_all(todo=[], upcoming=[])
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    assert result["items"] == []


@respx.mock
async def test_one_source_failing_still_returns_the_other():
    respx.get("https://canvas.example.edu/api/v1/users/self/todo").mock(
        return_value=httpx.Response(403, json={"status": "unauthorized"})
    )
    respx.get("https://canvas.example.edu/api/v1/users/self/upcoming_events").mock(
        return_value=httpx.Response(200, json=UPCOMING)
    )
    client = CanvasClient(CFG)
    result = await do_whats_due(client)
    await client.aclose()

    assert len(result["items"]) == 2
    assert "todo" in " ".join(result["warnings"]).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_whats_due.py -v`
Expected: FAIL with `ImportError: cannot import name 'do_whats_due'`

- [ ] **Step 3: Write `tools/student.py`**

```python
# src/canvas_api_mcp/tools/student.py
"""The student daily driver: deadlines, grades, assignments, submissions."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import CanvasClient, CanvasError

READ_ONLY = dict(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)

# Sorts unknown due dates to the end.
_FAR_FUTURE = "9999"


def _course_id_from_context(code: str | None) -> int | None:
    if not code or not code.startswith("course_"):
        return None
    try:
        return int(code.split("_", 1)[1])
    except ValueError:
        return None


def _from_todo(entry: dict) -> dict | None:
    assignment = entry.get("assignment") or {}
    if not assignment:
        return None
    return {
        "title": assignment.get("name"),
        "type": "assignment",
        "due_at": assignment.get("due_at"),
        "course_id": assignment.get("course_id"),
        "course_name": entry.get("context_name"),
        "html_url": assignment.get("html_url") or entry.get("html_url"),
        "submitted": False,
        "_key": ("assignment", assignment.get("id")),
    }


def _from_upcoming(entry: dict) -> dict | None:
    assignment = entry.get("assignment") or {}
    if assignment:
        return {
            "title": entry.get("title"),
            "type": "assignment",
            "due_at": assignment.get("due_at") or entry.get("start_at"),
            "course_id": assignment.get("course_id")
            or _course_id_from_context(entry.get("context_code")),
            "course_name": entry.get("context_name"),
            "html_url": entry.get("html_url"),
            "submitted": bool(assignment.get("has_submitted_submissions")),
            "_key": ("assignment", assignment.get("id")),
        }
    return {
        "title": entry.get("title"),
        "type": "event",
        "due_at": entry.get("start_at"),
        "course_id": _course_id_from_context(entry.get("context_code")),
        "course_name": entry.get("context_name"),
        "html_url": entry.get("html_url"),
        "submitted": False,
        "_key": ("event", entry.get("id")),
    }


async def _safe_fetch(client: CanvasClient, path: str, warnings: list[str]) -> list[dict]:
    try:
        response = await client.request("GET", path)
    except CanvasError as exc:
        warnings.append(f"Could not read {path}: {exc.message}")
        return []
    data = response.data
    return data if isinstance(data, list) else []


async def do_whats_due(client: CanvasClient, days: int = 14) -> dict[str, Any]:
    warnings: list[str] = []
    todo = await _safe_fetch(client, "users/self/todo", warnings)
    upcoming = await _safe_fetch(client, "users/self/upcoming_events", warnings)

    items: dict[tuple, dict] = {}
    for entry in todo:
        item = _from_todo(entry)
        if item:
            items.setdefault(item["_key"], item)
    for entry in upcoming:
        item = _from_upcoming(entry)
        if item:
            items.setdefault(item["_key"], item)

    ordered = sorted(items.values(), key=lambda i: i.get("due_at") or _FAR_FUTURE)
    for item in ordered:
        item.pop("_key", None)

    return {"items": ordered, "days": days, "warnings": warnings}


def register(mcp: FastMCP, get_client) -> None:
    @mcp.tool(
        description=(
            "List what is due for the user across all courses — assignments, quizzes, "
            "and scheduled events — sorted soonest first. This is the primary tool for "
            "'what's due this week', 'what do I have coming up', and deadline planning."
        ),
        annotations=ToolAnnotations(title="What's Due", **READ_ONLY),
    )
    async def whats_due(
        days: int = Field(default=14, description="Horizon in days to describe in the result"),
    ) -> dict:
        """Merged upcoming deadlines and events."""
        return await do_whats_due(get_client(), days=days)
```

- [ ] **Step 4: Register in `server.py`**

Change the import to `from .tools import gateway, orientation, student` and add:

```python
student.register(mcp, get_client)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all tests green

- [ ] **Step 6: Commit**

```bash
git add src/canvas_api_mcp/tools/student.py src/canvas_api_mcp/server.py tests/test_whats_due.py
git commit -m "feat: whats_due merging todo and upcoming events"
```

---

### Task 11: Grades, assignments, and submission status

**Files:**
- Modify: `src/canvas_api_mcp/tools/student.py`
- Test: `tests/test_grades.py`

**Interfaces:**
- Consumes: `CanvasClient` and the helpers in `tools/student.py`.
- Produces, all appended to `tools/student.py`:
  - `async def do_my_grades(client, course_id: int | None = None) -> list[dict]` → items `{"course_id", "course_name", "current_score", "current_grade", "final_score"}`
  - `async def do_list_assignments(client, course_id: int, bucket: str | None = None) -> list[dict]` → items `{"id", "name", "due_at", "points_possible", "html_url", "submitted", "score"}`
  - `async def do_get_assignment(client, course_id: int, assignment_id: int) -> dict`
  - `async def do_my_submission(client, course_id: int, assignment_id: int) -> dict`
  - `async def do_course_announcements(client, course_id: int | None = None, days: int = 14) -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
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
    route = respx.get(f"{API}/courses/101/assignments/1").mock(
        return_value=httpx.Response(200, json={
            "id": 1, "name": "PS1", "description": "<p>Do it</p>",
            "due_at": "2026-08-12T15:59:00Z", "points_possible": 20,
            "rubric": [{"description": "Correctness", "points": 15}],
            "submission": {"workflow_state": "unsubmitted"},
        })
    )
    client = CanvasClient(CFG)
    result = await do_get_assignment(client, 101, 1)
    await client.aclose()

    assert result["name"] == "PS1"
    assert result["rubric"][0]["description"] == "Correctness"
    assert "submission" in route.calls[0].request.url.params.get_list("include[]")


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_grades.py -v`
Expected: FAIL with `ImportError: cannot import name 'do_my_grades'`

- [ ] **Step 3: Append the implementations to `tools/student.py`**

Add `from datetime import datetime, timedelta, timezone` to the imports, then append before `def register`:

```python
async def do_my_grades(client: CanvasClient, course_id: int | None = None) -> list[dict]:
    response = await client.request(
        "GET",
        "courses",
        params={"enrollment_state": "active", "include[]": ["total_scores"], "per_page": 100},
    )
    out = []
    for course in response.data or []:
        if course_id is not None and course.get("id") != course_id:
            continue
        enrolment = next(
            (e for e in course.get("enrollments", []) if e.get("type") == "student"),
            None,
        )
        if enrolment is None:
            continue
        out.append(
            {
                "course_id": course.get("id"),
                "course_name": course.get("name"),
                "current_score": enrolment.get("computed_current_score"),
                "current_grade": enrolment.get("computed_current_grade"),
                "final_score": enrolment.get("computed_final_score"),
            }
        )
    return out


async def do_list_assignments(
    client: CanvasClient, course_id: int, bucket: str | None = None
) -> list[dict]:
    params: dict[str, Any] = {"include[]": ["submission"], "per_page": 100}
    if bucket:
        params["bucket"] = bucket
    response = await client.request(
        "GET", f"courses/{course_id}/assignments", params=params
    )
    out = []
    for assignment in response.data or []:
        submission = assignment.get("submission") or {}
        state = submission.get("workflow_state")
        out.append(
            {
                "id": assignment.get("id"),
                "name": assignment.get("name"),
                "due_at": assignment.get("due_at"),
                "points_possible": assignment.get("points_possible"),
                "html_url": assignment.get("html_url"),
                "submitted": state in {"submitted", "graded", "pending_review"},
                "score": submission.get("score"),
            }
        )
    return out


async def do_get_assignment(
    client: CanvasClient, course_id: int, assignment_id: int
) -> dict:
    response = await client.request(
        "GET",
        f"courses/{course_id}/assignments/{assignment_id}",
        params={"include[]": ["submission"]},
    )
    assignment = response.data or {}
    return {
        "id": assignment.get("id"),
        "name": assignment.get("name"),
        "description": assignment.get("description"),
        "due_at": assignment.get("due_at"),
        "unlock_at": assignment.get("unlock_at"),
        "lock_at": assignment.get("lock_at"),
        "points_possible": assignment.get("points_possible"),
        "submission_types": assignment.get("submission_types", []),
        "allowed_extensions": assignment.get("allowed_extensions", []),
        "html_url": assignment.get("html_url"),
        "rubric": assignment.get("rubric", []),
        "submission": assignment.get("submission"),
    }


async def do_my_submission(
    client: CanvasClient, course_id: int, assignment_id: int
) -> dict:
    response = await client.request(
        "GET",
        f"courses/{course_id}/assignments/{assignment_id}/submissions/self",
        params={"include[]": ["submission_comments", "rubric_assessment"]},
    )
    submission = response.data or {}
    return {
        "workflow_state": submission.get("workflow_state"),
        "submitted_at": submission.get("submitted_at"),
        "score": submission.get("score"),
        "grade": submission.get("grade"),
        "late": submission.get("late"),
        "missing": submission.get("missing"),
        "attempt": submission.get("attempt"),
        "comments": submission.get("submission_comments", []),
        "rubric_assessment": submission.get("rubric_assessment"),
    }


async def do_course_announcements(
    client: CanvasClient, course_id: int | None = None, days: int = 14
) -> list[dict]:
    start = datetime.now(timezone.utc) - timedelta(days=days)
    params: dict[str, Any] = {
        "start_date": start.date().isoformat(),
        "per_page": 50,
    }
    if course_id is not None:
        params["context_codes[]"] = [f"course_{course_id}"]
    else:
        courses = await client.request(
            "GET", "courses", params={"enrollment_state": "active", "per_page": 100}
        )
        codes = [f"course_{c['id']}" for c in (courses.data or []) if c.get("id")]
        if not codes:
            return []
        params["context_codes[]"] = codes

    response = await client.request("GET", "announcements", params=params)
    out = []
    for item in response.data or []:
        out.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "message": item.get("message"),
                "posted_at": item.get("posted_at"),
                "html_url": item.get("html_url"),
                "course_id": _course_id_from_context(item.get("context_code")),
            }
        )
    return out
```

- [ ] **Step 4: Register the five tools**

Append inside `register`, after `whats_due`:

```python
    @mcp.tool(
        description=(
            "Report the user's current grade and score in each course, or in one course "
            "if course_id is given. Use this for 'how am I doing' and standing questions."
        ),
        annotations=ToolAnnotations(title="My Grades", **READ_ONLY),
    )
    async def my_grades(
        course_id: int | None = Field(default=None, description="Limit to one course; omit for all"),
    ) -> list[dict]:
        """Current scores per course."""
        return await do_my_grades(get_client(), course_id=course_id)

    @mcp.tool(
        description=(
            "List a course's assignments with due dates, points, and whether the user "
            "has submitted each one. Use bucket to filter to upcoming, overdue, "
            "unsubmitted, or past work."
        ),
        annotations=ToolAnnotations(title="List Assignments", **READ_ONLY),
    )
    async def list_assignments(
        course_id: int = Field(description="Course id, from my_courses"),
        bucket: str | None = Field(
            default=None,
            description="One of: past, overdue, undated, ungraded, unsubmitted, upcoming, future",
        ),
    ) -> list[dict]:
        """Assignments in a course."""
        return await do_list_assignments(get_client(), course_id, bucket=bucket)

    @mcp.tool(
        description=(
            "Get one assignment in full: instructions, due and lock dates, points, "
            "accepted submission types, rubric, and the user's current submission state."
        ),
        annotations=ToolAnnotations(title="Get Assignment", **READ_ONLY),
    )
    async def get_assignment(
        course_id: int = Field(description="Course id"),
        assignment_id: int = Field(description="Assignment id"),
    ) -> dict:
        """Full detail for a single assignment."""
        return await do_get_assignment(get_client(), course_id, assignment_id)

    @mcp.tool(
        description=(
            "Get the user's own submission for an assignment: state, score, grade, "
            "lateness, instructor comments, and rubric assessment."
        ),
        annotations=ToolAnnotations(title="My Submission", **READ_ONLY),
    )
    async def my_submission(
        course_id: int = Field(description="Course id"),
        assignment_id: int = Field(description="Assignment id"),
    ) -> dict:
        """The user's submission and feedback."""
        return await do_my_submission(get_client(), course_id, assignment_id)

    @mcp.tool(
        description=(
            "List recent course announcements across all active courses, or one course "
            "if course_id is given."
        ),
        annotations=ToolAnnotations(title="Announcements", **READ_ONLY),
    )
    async def course_announcements(
        course_id: int | None = Field(default=None, description="Limit to one course; omit for all"),
        days: int = Field(default=14, description="How many days back to look"),
    ) -> list[dict]:
        """Recent announcements."""
        return await do_course_announcements(get_client(), course_id=course_id, days=days)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all tests green

- [ ] **Step 6: Commit**

```bash
git add src/canvas_api_mcp/tools/student.py tests/test_grades.py
git commit -m "feat: grades, assignments, submission status, announcements"
```

---

### Task 12: submit_assignment (write tool)

**Files:**
- Modify: `src/canvas_api_mcp/tools/student.py`
- Test: `tests/test_submit.py`

**Interfaces:**
- Consumes: `CanvasClient`.
- Produces: `async def do_submit_assignment(client, course_id: int, assignment_id: int, submission_type: str, body: str | None = None, url: str | None = None, file_ids: list[int] | None = None) -> dict`.
- Valid `submission_type` values: `online_text_entry`, `online_url`, `online_upload`. Each requires its matching payload field; a mismatch returns a structured error without sending.

This is the only tool in phase 1 that changes state visible to an instructor.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_submit.py
import httpx
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.student import do_submit_assignment

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
URL = "https://canvas.example.edu/api/v1/courses/101/assignments/1/submissions"


@respx.mock
async def test_text_entry_posts_correct_payload():
    route = respx.post(URL).mock(
        return_value=httpx.Response(201, json={"id": 7, "workflow_state": "submitted",
                                               "submitted_at": "2026-08-11T10:00:00Z"})
    )
    client = CanvasClient(CFG)
    result = await do_submit_assignment(
        client, 101, 1, "online_text_entry", body="my answer"
    )
    await client.aclose()

    sent = route.calls[0].request.read().decode()
    assert '"submission_type": "online_text_entry"' in sent.replace("  ", " ") or "online_text_entry" in sent
    assert "my answer" in sent
    assert result["workflow_state"] == "submitted"


@respx.mock
async def test_url_submission_posts_url_field():
    route = respx.post(URL).mock(return_value=httpx.Response(201, json={"id": 8}))
    client = CanvasClient(CFG)
    await do_submit_assignment(client, 101, 1, "online_url", url="https://github.com/me/x")
    await client.aclose()
    assert "github.com/me/x" in route.calls[0].request.read().decode()


@respx.mock
async def test_upload_posts_file_ids():
    route = respx.post(URL).mock(return_value=httpx.Response(201, json={"id": 9}))
    client = CanvasClient(CFG)
    await do_submit_assignment(client, 101, 1, "online_upload", file_ids=[55, 56])
    await client.aclose()
    assert "55" in route.calls[0].request.read().decode()


async def test_missing_body_for_text_entry_is_rejected_without_sending():
    with respx.mock:
        route = respx.post(URL).mock(return_value=httpx.Response(201, json={}))
        client = CanvasClient(CFG)
        result = await do_submit_assignment(client, 101, 1, "online_text_entry")
        await client.aclose()

    assert route.called is False
    assert result["error"] is True
    assert "body" in result["message"]


async def test_unknown_submission_type_is_rejected_without_sending():
    with respx.mock:
        route = respx.post(URL).mock(return_value=httpx.Response(201, json={}))
        client = CanvasClient(CFG)
        result = await do_submit_assignment(client, 101, 1, "carrier_pigeon", body="x")
        await client.aclose()

    assert route.called is False
    assert result["error"] is True
    assert "carrier_pigeon" in result["message"]


@respx.mock
async def test_canvas_rejection_is_returned_structured():
    respx.post(URL).mock(return_value=httpx.Response(403, json={"status": "unauthorized"}))
    client = CanvasClient(CFG)
    result = await do_submit_assignment(client, 101, 1, "online_text_entry", body="x")
    await client.aclose()

    assert result["error"] is True
    assert result["status"] == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_submit.py -v`
Expected: FAIL with `ImportError: cannot import name 'do_submit_assignment'`

- [ ] **Step 3: Append the implementation to `tools/student.py`**

```python
SUBMISSION_REQUIREMENTS = {
    "online_text_entry": "body",
    "online_url": "url",
    "online_upload": "file_ids",
}


async def do_submit_assignment(
    client: CanvasClient,
    course_id: int,
    assignment_id: int,
    submission_type: str,
    body: str | None = None,
    url: str | None = None,
    file_ids: list[int] | None = None,
) -> dict:
    if submission_type not in SUBMISSION_REQUIREMENTS:
        return {
            "error": True,
            "status": 0,
            "message": (
                f"Unknown submission_type {submission_type!r}. Supported types: "
                f"{', '.join(sorted(SUBMISSION_REQUIREMENTS))}. Check the assignment's "
                "submission_types with get_assignment."
            ),
        }

    supplied = {"body": body, "url": url, "file_ids": file_ids}
    required = SUBMISSION_REQUIREMENTS[submission_type]
    if not supplied[required]:
        return {
            "error": True,
            "status": 0,
            "message": (
                f"submission_type {submission_type!r} requires the {required!r} "
                "argument, which was not provided. Nothing was submitted."
            ),
        }

    payload: dict[str, Any] = {"submission_type": submission_type}
    if submission_type == "online_text_entry":
        payload["body"] = body
    elif submission_type == "online_url":
        payload["url"] = url
    else:
        payload["file_ids"] = file_ids

    try:
        response = await client.request(
            "POST",
            f"courses/{course_id}/assignments/{assignment_id}/submissions",
            json={"submission": payload},
        )
    except CanvasError as exc:
        return {
            "error": True,
            "status": exc.status,
            "message": exc.message,
            "hint": exc.hint,
        }

    submission = response.data or {}
    return {
        "id": submission.get("id"),
        "workflow_state": submission.get("workflow_state"),
        "submitted_at": submission.get("submitted_at"),
        "attempt": submission.get("attempt"),
        "late": submission.get("late"),
        "preview_url": submission.get("preview_url"),
    }
```

- [ ] **Step 4: Register the tool**

Append inside `register`:

```python
    @mcp.tool(
        description=(
            "Submits work to Canvas for an assignment. This is recorded against the "
            "deadline immediately, is visible to the instructor, and cannot be undone "
            "from here. Confirm the assignment and content with the user before calling. "
            "Check accepted formats with get_assignment first — submission_type must be "
            "one the assignment allows. For online_upload, file_ids must reference files "
            "already uploaded to Canvas."
        ),
        annotations=ToolAnnotations(
            title="Submit Assignment",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def submit_assignment(
        course_id: int = Field(description="Course id"),
        assignment_id: int = Field(description="Assignment id"),
        submission_type: str = Field(
            description="One of: online_text_entry, online_url, online_upload"
        ),
        body: str | None = Field(default=None, description="Text content for online_text_entry"),
        url: str | None = Field(default=None, description="URL for online_url"),
        file_ids: list[int] | None = Field(
            default=None, description="Canvas file ids for online_upload"
        ),
    ) -> dict:
        """Submit an assignment."""
        return await do_submit_assignment(
            get_client(), course_id, assignment_id, submission_type,
            body=body, url=url, file_ids=file_ids,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all tests green

- [ ] **Step 6: Commit**

```bash
git add src/canvas_api_mcp/tools/student.py tests/test_submit.py
git commit -m "feat: submit_assignment with pre-flight payload validation"
```

---

### Task 13: Course content tools

**Files:**
- Create: `src/canvas_api_mcp/tools/content.py`
- Modify: `src/canvas_api_mcp/server.py`
- Test: `tests/test_content.py`

**Interfaces:**
- Consumes: `CanvasClient`, `CanvasError`.
- Produces:
  - `async def do_course_content(client, course_id: int) -> list[dict]` → modules with nested items
  - `async def do_list_files(client, course_id: int, search: str | None = None) -> list[dict]`
  - `async def do_get_page(client, course_id: int, page_url: str) -> dict`
  - `register(mcp, get_client) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_content.py
import httpx
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.content import do_course_content, do_get_page, do_list_files

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
API = "https://canvas.example.edu/api/v1"


@respx.mock
async def test_course_content_nests_items_under_modules():
    respx.get(f"{API}/courses/101/modules").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "Week 1", "position": 1, "items": [
                {"id": 11, "title": "Lecture 1", "type": "File", "content_id": 501,
                 "html_url": "https://c/11"},
            ]},
        ])
    )
    client = CanvasClient(CFG)
    modules = await do_course_content(client, 101)
    await client.aclose()

    assert modules[0]["name"] == "Week 1"
    assert modules[0]["items"][0] == {
        "id": 11, "title": "Lecture 1", "type": "File",
        "content_id": 501, "page_url": None, "html_url": "https://c/11",
    }


@respx.mock
async def test_course_content_requests_items_inline():
    route = respx.get(f"{API}/courses/101/modules").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    await do_course_content(client, 101)
    await client.aclose()
    assert "items" in route.calls[0].request.url.params.get_list("include[]")


@respx.mock
async def test_list_files_shapes_metadata():
    respx.get(f"{API}/courses/101/files").mock(
        return_value=httpx.Response(200, json=[
            {"id": 501, "display_name": "lec01.pdf", "content-type": "application/pdf",
             "size": 1024, "url": "https://files/501", "updated_at": "2026-08-01T00:00:00Z"},
        ])
    )
    client = CanvasClient(CFG)
    files = await do_list_files(client, 101)
    await client.aclose()

    assert files[0]["display_name"] == "lec01.pdf"
    assert files[0]["content_type"] == "application/pdf"
    assert files[0]["size"] == 1024


@respx.mock
async def test_list_files_passes_search_term():
    route = respx.get(f"{API}/courses/101/files").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CanvasClient(CFG)
    await do_list_files(client, 101, search="tutorial")
    await client.aclose()
    assert route.calls[0].request.url.params["search_term"] == "tutorial"


@respx.mock
async def test_get_page_returns_title_and_body():
    respx.get(f"{API}/courses/101/pages/syllabus").mock(
        return_value=httpx.Response(200, json={
            "title": "Syllabus", "url": "syllabus", "body": "<p>Grading: 40/60</p>",
            "updated_at": "2026-08-01T00:00:00Z",
        })
    )
    client = CanvasClient(CFG)
    page = await do_get_page(client, 101, "syllabus")
    await client.aclose()

    assert page["title"] == "Syllabus"
    assert "40/60" in page["body"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_content.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'canvas_api_mcp.tools.content'`

- [ ] **Step 3: Write `tools/content.py`**

```python
# src/canvas_api_mcp/tools/content.py
"""Course structure, files, and pages."""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import CanvasClient

READ_ONLY = dict(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)


async def do_course_content(client: CanvasClient, course_id: int) -> list[dict]:
    response = await client.request(
        "GET",
        f"courses/{course_id}/modules",
        params={"include[]": ["items"], "per_page": 100},
    )
    modules = []
    for module in response.data or []:
        modules.append(
            {
                "id": module.get("id"),
                "name": module.get("name"),
                "position": module.get("position"),
                "items": [
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "type": item.get("type"),
                        "content_id": item.get("content_id"),
                        "page_url": item.get("page_url"),
                        "html_url": item.get("html_url"),
                    }
                    for item in module.get("items", [])
                ],
            }
        )
    return modules


async def do_list_files(
    client: CanvasClient, course_id: int, search: str | None = None
) -> list[dict]:
    params: dict = {"per_page": 100}
    if search:
        params["search_term"] = search
    response = await client.request("GET", f"courses/{course_id}/files", params=params)
    return [
        {
            "id": f.get("id"),
            "display_name": f.get("display_name"),
            "content_type": f.get("content-type") or f.get("content_type"),
            "size": f.get("size"),
            "url": f.get("url"),
            "updated_at": f.get("updated_at"),
        }
        for f in response.data or []
    ]


async def do_get_page(client: CanvasClient, course_id: int, page_url: str) -> dict:
    response = await client.request("GET", f"courses/{course_id}/pages/{page_url}")
    page = response.data or {}
    return {
        "title": page.get("title"),
        "url": page.get("url"),
        "body": page.get("body"),
        "updated_at": page.get("updated_at"),
    }


def register(mcp: FastMCP, get_client) -> None:
    @mcp.tool(
        description=(
            "Map a course's structure: its modules in order, and the items inside each "
            "(files, pages, assignments, quizzes, links). Use this to find what material "
            "exists before fetching any of it."
        ),
        annotations=ToolAnnotations(title="Course Content", **READ_ONLY),
    )
    async def course_content(
        course_id: int = Field(description="Course id, from my_courses"),
    ) -> list[dict]:
        """Modules and their items."""
        return await do_course_content(get_client(), course_id)

    @mcp.tool(
        description=(
            "List files in a course — lecture slides, notes, readings — with name, type, "
            "and size. Pass search to filter by filename. Use read_file to get the text "
            "of one."
        ),
        annotations=ToolAnnotations(title="List Files", **READ_ONLY),
    )
    async def list_files(
        course_id: int = Field(description="Course id"),
        search: str | None = Field(default=None, description="Filter by filename fragment"),
    ) -> list[dict]:
        """Files in a course."""
        return await do_list_files(get_client(), course_id, search=search)

    @mcp.tool(
        description=(
            "Get the content of a Canvas page in a course, such as a syllabus or a "
            "weekly overview. page_url is the page's slug, available from course_content."
        ),
        annotations=ToolAnnotations(title="Get Page", **READ_ONLY),
    )
    async def get_page(
        course_id: int = Field(description="Course id"),
        page_url: str = Field(description="Page slug, e.g. 'syllabus' or 'week-1-overview'"),
    ) -> dict:
        """A single course page."""
        return await do_get_page(get_client(), course_id, page_url)
```

- [ ] **Step 4: Register in `server.py`**

Change the import to `from .tools import content, gateway, orientation, student` and add:

```python
content.register(mcp, get_client)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all tests green

- [ ] **Step 6: Commit**

```bash
git add src/canvas_api_mcp/tools/content.py src/canvas_api_mcp/server.py tests/test_content.py
git commit -m "feat: course content, file listing, and page tools"
```

---

### Task 14: read_file with text extraction

**Files:**
- Create: `src/canvas_api_mcp/extract.py`
- Modify: `src/canvas_api_mcp/tools/content.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: `CanvasClient`.
- Produces:
  - `extract.py`: `def extract_text(content: bytes, content_type: str, filename: str) -> str` — dispatches on type; raises `UnsupportedFileType(Exception)` for anything it cannot read.
  - `content.py`: `async def do_read_file(client, file_id: int, max_chars: int = 50_000) -> dict` returning `{"display_name", "content_type", "text", "truncated", "chars"}`.
- Supported: `application/pdf` (pypdf), `.pptx` (python-pptx), `.docx` (python-docx), and any `text/*` or JSON as UTF-8.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extract.py
import io

import httpx
import pytest
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.extract import UnsupportedFileType, extract_text
from canvas_api_mcp.tools.content import do_read_file

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
API = "https://canvas.example.edu/api/v1"


def test_plain_text_is_decoded():
    assert extract_text(b"hello world", "text/plain", "a.txt") == "hello world"


def test_docx_paragraphs_are_extracted():
    from docx import Document

    doc = Document()
    doc.add_paragraph("Lecture One")
    doc.add_paragraph("Big-O notation")
    buf = io.BytesIO()
    doc.save(buf)

    text = extract_text(
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "lec.docx",
    )
    assert "Lecture One" in text
    assert "Big-O notation" in text


def test_pptx_slide_text_is_extracted():
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Amortised Analysis"
    buf = io.BytesIO()
    prs.save(buf)

    text = extract_text(
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "wk3.pptx",
    )
    assert "Amortised Analysis" in text


def test_unsupported_type_raises():
    with pytest.raises(UnsupportedFileType) as exc:
        extract_text(b"\x00\x01", "image/png", "diagram.png")
    assert "png" in str(exc.value).lower() or "image" in str(exc.value).lower()


@respx.mock
async def test_read_file_fetches_metadata_then_content():
    respx.get(f"{API}/files/501").mock(
        return_value=httpx.Response(200, json={
            "id": 501, "display_name": "notes.txt", "content-type": "text/plain",
            "url": "https://files.example.edu/501?verifier=abc",
        })
    )
    respx.get("https://files.example.edu/501").mock(
        return_value=httpx.Response(200, content=b"Kruskal and Prim")
    )
    client = CanvasClient(CFG)
    result = await do_read_file(client, 501)
    await client.aclose()

    assert result["display_name"] == "notes.txt"
    assert result["text"] == "Kruskal and Prim"
    assert result["truncated"] is False


@respx.mock
async def test_read_file_truncates_long_text():
    respx.get(f"{API}/files/502").mock(
        return_value=httpx.Response(200, json={
            "id": 502, "display_name": "big.txt", "content-type": "text/plain",
            "url": "https://files.example.edu/502",
        })
    )
    respx.get("https://files.example.edu/502").mock(
        return_value=httpx.Response(200, content=b"x" * 200)
    )
    client = CanvasClient(CFG)
    result = await do_read_file(client, 502, max_chars=50)
    await client.aclose()

    assert len(result["text"]) == 50
    assert result["truncated"] is True
    assert result["chars"] == 200


@respx.mock
async def test_read_file_reports_unsupported_type_as_structured_error():
    respx.get(f"{API}/files/503").mock(
        return_value=httpx.Response(200, json={
            "id": 503, "display_name": "photo.png", "content-type": "image/png",
            "url": "https://files.example.edu/503",
        })
    )
    respx.get("https://files.example.edu/503").mock(
        return_value=httpx.Response(200, content=b"\x89PNG")
    )
    client = CanvasClient(CFG)
    result = await do_read_file(client, 503)
    await client.aclose()

    assert result["error"] is True
    assert "photo.png" in result["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'canvas_api_mcp.extract'`

- [ ] **Step 3: Write `extract.py`**

```python
# src/canvas_api_mcp/extract.py
"""Turn downloaded course files into plain text.

Only formats a student would actually read are supported. Anything else
fails loudly rather than returning bytes the model cannot use.
"""

from __future__ import annotations

import io


class UnsupportedFileType(Exception):
    """Raised when a file's type has no text extractor."""


PDF_TYPES = {"application/pdf"}
DOCX_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}
PPTX_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
}


def _pdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _docx(content: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs if p.text).strip()


def _pptx(content: bytes) -> str:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(content))
    chunks: list[str] = []
    for index, slide in enumerate(prs.slides, start=1):
        lines = [
            shape.text
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False) and shape.text
        ]
        if lines:
            chunks.append(f"--- Slide {index} ---\n" + "\n".join(lines))
    return "\n\n".join(chunks).strip()


def extract_text(content: bytes, content_type: str, filename: str) -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    lower_name = filename.lower()

    if ctype in PDF_TYPES or lower_name.endswith(".pdf"):
        return _pdf(content)
    if ctype in DOCX_TYPES or lower_name.endswith(".docx"):
        return _docx(content)
    if ctype in PPTX_TYPES or lower_name.endswith(".pptx"):
        return _pptx(content)
    if ctype.startswith("text/") or ctype == "application/json":
        return content.decode("utf-8", errors="replace")

    raise UnsupportedFileType(
        f"No text extractor for {filename!r} (type {content_type!r}). "
        "Supported: PDF, DOCX, PPTX, and plain text."
    )
```

- [ ] **Step 4: Append `do_read_file` to `tools/content.py`**

Add these imports at the top of `content.py`:

```python
import httpx

from ..client import CanvasError
from ..extract import UnsupportedFileType, extract_text
```

Then append before `def register`:

```python
async def do_read_file(
    client: CanvasClient, file_id: int, max_chars: int = 50_000
) -> dict:
    try:
        meta_response = await client.request("GET", f"files/{file_id}")
    except CanvasError as exc:
        return {"error": True, "status": exc.status, "message": exc.message, "hint": exc.hint}

    meta = meta_response.data or {}
    download_url = meta.get("url")
    display_name = meta.get("display_name") or f"file-{file_id}"
    content_type = meta.get("content-type") or meta.get("content_type") or ""

    if not download_url:
        return {
            "error": True,
            "status": 0,
            "message": f"Canvas returned no download URL for {display_name!r}.",
        }

    # The download URL is pre-signed and must NOT carry the Authorization header.
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as raw:
        file_response = await raw.get(download_url)
        file_response.raise_for_status()
        content = file_response.content

    try:
        text = extract_text(content, content_type, display_name)
    except UnsupportedFileType as exc:
        return {"error": True, "status": 0, "message": str(exc)}

    total = len(text)
    return {
        "display_name": display_name,
        "content_type": content_type,
        "text": text[:max_chars],
        "truncated": total > max_chars,
        "chars": total,
    }
```

- [ ] **Step 5: Register the tool**

Append inside `register` in `content.py`:

```python
    @mcp.tool(
        description=(
            "Download a Canvas file and return its text — lecture slides, notes, "
            "readings. Supports PDF, DOCX, PPTX, and plain text. Get file ids from "
            "list_files or course_content. Long files are truncated to max_chars."
        ),
        annotations=ToolAnnotations(title="Read File", **READ_ONLY),
    )
    async def read_file(
        file_id: int = Field(description="Canvas file id, from list_files"),
        max_chars: int = Field(default=50_000, description="Truncate extracted text to this length"),
    ) -> dict:
        """Extract text from a course file."""
        return await do_read_file(get_client(), file_id, max_chars=max_chars)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all tests green

- [ ] **Step 7: Commit**

```bash
git add src/canvas_api_mcp/extract.py src/canvas_api_mcp/tools/content.py tests/test_extract.py
git commit -m "feat: read_file with PDF, DOCX, PPTX, and text extraction"
```

---

### Task 15: Discussion tools

**Files:**
- Create: `src/canvas_api_mcp/tools/discussions.py`
- Modify: `src/canvas_api_mcp/server.py`
- Test: `tests/test_discussions.py`

**Interfaces:**
- Consumes: `CanvasClient`, `CanvasError`.
- Produces:
  - `async def do_read_discussion(client, course_id: int, topic_id: int | None = None) -> dict` — with no `topic_id`, lists topics; with one, returns the topic plus its flattened entries.
  - `async def do_post_discussion_reply(client, course_id: int, topic_id: int, message: str, parent_entry_id: int | None = None) -> dict`
  - `register(mcp, get_client) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discussions.py
import httpx
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.discussions import do_post_discussion_reply, do_read_discussion

CFG = Config(base_url="https://canvas.example.edu", token="tok", max_pages=10)
API = "https://canvas.example.edu/api/v1"


@respx.mock
async def test_lists_topics_when_no_topic_id():
    respx.get(f"{API}/courses/101/discussion_topics").mock(
        return_value=httpx.Response(200, json=[
            {"id": 7, "title": "PS3 clarifications", "posted_at": "2026-08-01T00:00:00Z",
             "discussion_subentry_count": 12, "html_url": "https://c/7"},
        ])
    )
    client = CanvasClient(CFG)
    result = await do_read_discussion(client, 101)
    await client.aclose()

    assert result["topics"][0]["title"] == "PS3 clarifications"
    assert result["topics"][0]["reply_count"] == 12


@respx.mock
async def test_reads_a_topic_and_flattens_nested_replies():
    respx.get(f"{API}/courses/101/discussion_topics/7").mock(
        return_value=httpx.Response(200, json={"id": 7, "title": "PS3", "message": "<p>Ask here</p>"})
    )
    respx.get(f"{API}/courses/101/discussion_topics/7/view").mock(
        return_value=httpx.Response(200, json={
            "view": [
                {"id": 1, "user_id": 42, "message": "Is Q2 recursive?",
                 "created_at": "2026-08-02T00:00:00Z",
                 "replies": [
                     {"id": 2, "user_id": 9, "message": "Yes.",
                      "created_at": "2026-08-02T01:00:00Z"},
                 ]},
            ]
        })
    )
    client = CanvasClient(CFG)
    result = await do_read_discussion(client, 101, topic_id=7)
    await client.aclose()

    assert result["title"] == "PS3"
    assert [e["id"] for e in result["entries"]] == [1, 2]
    assert result["entries"][1]["depth"] == 1


@respx.mock
async def test_post_reply_sends_message():
    route = respx.post(f"{API}/courses/101/discussion_topics/7/entries").mock(
        return_value=httpx.Response(201, json={"id": 33, "created_at": "2026-08-11T00:00:00Z"})
    )
    client = CanvasClient(CFG)
    result = await do_post_discussion_reply(client, 101, 7, "My answer")
    await client.aclose()

    assert "My answer" in route.calls[0].request.read().decode()
    assert result["id"] == 33


@respx.mock
async def test_reply_to_entry_uses_nested_endpoint():
    route = respx.post(f"{API}/courses/101/discussion_topics/7/entries/2/replies").mock(
        return_value=httpx.Response(201, json={"id": 34})
    )
    client = CanvasClient(CFG)
    await do_post_discussion_reply(client, 101, 7, "Thanks", parent_entry_id=2)
    await client.aclose()
    assert route.called


@respx.mock
async def test_empty_message_is_rejected_without_sending():
    route = respx.post(f"{API}/courses/101/discussion_topics/7/entries").mock(
        return_value=httpx.Response(201, json={})
    )
    client = CanvasClient(CFG)
    result = await do_post_discussion_reply(client, 101, 7, "   ")
    await client.aclose()

    assert route.called is False
    assert result["error"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discussions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'canvas_api_mcp.tools.discussions'`

- [ ] **Step 3: Write `tools/discussions.py`**

```python
# src/canvas_api_mcp/tools/discussions.py
"""Course discussion topics and replies."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import CanvasClient, CanvasError

READ_ONLY = dict(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)


def _flatten(entries: list[dict], depth: int = 0) -> list[dict]:
    out: list[dict] = []
    for entry in entries:
        out.append(
            {
                "id": entry.get("id"),
                "user_id": entry.get("user_id"),
                "message": entry.get("message"),
                "created_at": entry.get("created_at"),
                "depth": depth,
            }
        )
        out.extend(_flatten(entry.get("replies") or [], depth + 1))
    return out


async def do_read_discussion(
    client: CanvasClient, course_id: int, topic_id: int | None = None
) -> dict[str, Any]:
    if topic_id is None:
        response = await client.request(
            "GET", f"courses/{course_id}/discussion_topics", params={"per_page": 50}
        )
        return {
            "topics": [
                {
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "posted_at": t.get("posted_at"),
                    "reply_count": t.get("discussion_subentry_count"),
                    "html_url": t.get("html_url"),
                }
                for t in response.data or []
            ]
        }

    topic = (
        await client.request("GET", f"courses/{course_id}/discussion_topics/{topic_id}")
    ).data or {}
    view = (
        await client.request(
            "GET", f"courses/{course_id}/discussion_topics/{topic_id}/view"
        )
    ).data or {}

    return {
        "id": topic.get("id"),
        "title": topic.get("title"),
        "message": topic.get("message"),
        "entries": _flatten(view.get("view") or []),
    }


async def do_post_discussion_reply(
    client: CanvasClient,
    course_id: int,
    topic_id: int,
    message: str,
    parent_entry_id: int | None = None,
) -> dict:
    if not message or not message.strip():
        return {
            "error": True,
            "status": 0,
            "message": "Refusing to post an empty discussion reply. Nothing was sent.",
        }

    base = f"courses/{course_id}/discussion_topics/{topic_id}/entries"
    path = base if parent_entry_id is None else f"{base}/{parent_entry_id}/replies"

    try:
        response = await client.request("POST", path, json={"message": message})
    except CanvasError as exc:
        return {"error": True, "status": exc.status, "message": exc.message, "hint": exc.hint}

    entry = response.data or {}
    return {"id": entry.get("id"), "created_at": entry.get("created_at")}


def register(mcp: FastMCP, get_client) -> None:
    @mcp.tool(
        description=(
            "Read course discussions. With only course_id, lists the discussion topics. "
            "With topic_id, returns that topic and all its replies flattened in order, "
            "with a depth field showing nesting."
        ),
        annotations=ToolAnnotations(title="Read Discussion", **READ_ONLY),
    )
    async def read_discussion(
        course_id: int = Field(description="Course id"),
        topic_id: int | None = Field(default=None, description="Topic id; omit to list topics"),
    ) -> dict:
        """Discussion topics or one topic's replies."""
        return await do_read_discussion(get_client(), course_id, topic_id=topic_id)

    @mcp.tool(
        description=(
            "Posts a public reply to a course discussion. The post appears immediately "
            "under the user's name and is visible to the whole class and the instructor. "
            "It cannot be deleted from here. Show the user the exact text and get their "
            "confirmation before calling."
        ),
        annotations=ToolAnnotations(
            title="Post Discussion Reply",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def post_discussion_reply(
        course_id: int = Field(description="Course id"),
        topic_id: int = Field(description="Discussion topic id"),
        message: str = Field(description="The reply text; HTML is allowed"),
        parent_entry_id: int | None = Field(
            default=None, description="Reply to this entry instead of the topic"
        ),
    ) -> dict:
        """Post a discussion reply."""
        return await do_post_discussion_reply(
            get_client(), course_id, topic_id, message, parent_entry_id=parent_entry_id
        )
```

- [ ] **Step 4: Register in `server.py`**

Change the import to `from .tools import content, discussions, gateway, orientation, student` and add:

```python
discussions.register(mcp, get_client)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all tests green

- [ ] **Step 6: Commit**

```bash
git add src/canvas_api_mcp/tools/discussions.py src/canvas_api_mcp/server.py tests/test_discussions.py
git commit -m "feat: discussion reading and replies"
```

---

### Task 16: Resources and prompts

**Files:**
- Create: `src/canvas_api_mcp/resources.py`
- Create: `src/canvas_api_mcp/prompts.py`
- Modify: `src/canvas_api_mcp/server.py`
- Test: `tests/test_resources_prompts.py`

**Interfaces:**
- Consumes: `identity.fetch_identity`, `catalog.load_catalog`, `tools.orientation.do_my_courses`.
- Produces:
  - `resources.py`: `register(mcp, get_client) -> None` exposing `canvas://me`, `canvas://courses`, `canvas://api/catalog`.
  - `prompts.py`: `register(mcp) -> None` exposing `week_ahead`, `study_pack`, `grade_check`; each backed by a pure function `build_week_ahead(days: int) -> str`, `build_study_pack(course: str, topic: str) -> str`, `build_grade_check(course: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resources_prompts.py
from canvas_api_mcp.prompts import build_grade_check, build_study_pack, build_week_ahead


def test_week_ahead_prompt_names_the_tools_to_use():
    text = build_week_ahead(7)
    assert "whats_due" in text
    assert "7" in text


def test_study_pack_prompt_includes_course_and_topic():
    text = build_study_pack("CS3230", "amortised analysis")
    assert "CS3230" in text
    assert "amortised analysis" in text
    assert "read_file" in text


def test_grade_check_prompt_references_grade_tools():
    text = build_grade_check("CS3230")
    assert "my_grades" in text
    assert "CS3230" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_resources_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'canvas_api_mcp.prompts'`

- [ ] **Step 3: Write `prompts.py`**

```python
# src/canvas_api_mcp/prompts.py
"""Workflow prompts — the reusable multi-step procedures."""

from __future__ import annotations

from fastmcp import FastMCP
from pydantic import Field


def build_week_ahead(days: int) -> str:
    return (
        f"Plan my next {days} days of coursework.\n\n"
        f"1. Call whats_due with days={days} to get every deadline and event.\n"
        "2. Call my_courses to map course_id values to course names.\n"
        "3. For anything due whose submission state is unclear, call my_submission "
        "to check whether I have already handed it in.\n"
        "4. Present the result as a table ordered by due date: what, which course, "
        "when it is due, how many days away, and whether it is submitted.\n"
        "5. Flag anything due within 48 hours that is not yet submitted, and anything "
        "where two deadlines fall on the same day.\n"
        "Do not guess at dates — use only values returned by the tools."
    )


def build_study_pack(course: str, topic: str) -> str:
    return (
        f"Build me a study pack on '{topic}' for {course}.\n\n"
        f"1. Call my_courses to resolve {course} to its course_id.\n"
        "2. Call course_content to see the modules and what is in them.\n"
        f"3. Identify the modules and files relevant to '{topic}'. Use list_files with "
        "a search term if the module names are not descriptive enough.\n"
        "4. Call read_file on the most relevant files — prefer lecture slides and notes.\n"
        f"5. Produce a summary of '{topic}' grounded only in that material: the key "
        "definitions, the main results, and any worked examples you found.\n"
        "6. Cite which file each point came from, and say plainly if the material does "
        "not cover something rather than filling the gap from your own knowledge."
    )


def build_grade_check(course: str) -> str:
    return (
        f"Work out where I stand in {course}.\n\n"
        f"1. Call my_courses to resolve {course} to its course_id.\n"
        "2. Call my_grades for that course to get my current score.\n"
        "3. Call list_assignments for the course to get every assignment and its "
        "points_possible, along with what I have submitted.\n"
        "4. Compute how many points remain unearned and unattempted.\n"
        "5. Tell me my current standing, what is still outstanding, and what I would "
        "need on the remaining work to reach the next grade boundary.\n"
        "State your assumptions about weighting explicitly — if the grading scheme is "
        "not visible via the API, say so instead of inventing one."
    )


def register(mcp: FastMCP) -> None:
    @mcp.prompt(description="Plan the coming days of coursework by deadline and urgency.")
    def week_ahead(
        days: int = Field(default=7, description="How many days ahead to plan"),
    ) -> str:
        """Deadline planning workflow."""
        return build_week_ahead(days)

    @mcp.prompt(description="Gather and summarise course material on a topic.")
    def study_pack(
        course: str = Field(description="Course code or name, e.g. CS3230"),
        topic: str = Field(description="Topic to study, e.g. 'amortised analysis'"),
    ) -> str:
        """Study material gathering workflow."""
        return build_study_pack(course, topic)

    @mcp.prompt(description="Compute standing in a course and what remains.")
    def grade_check(
        course: str = Field(description="Course code or name, e.g. CS3230"),
    ) -> str:
        """Grade standing workflow."""
        return build_grade_check(course)
```

- [ ] **Step 4: Write `resources.py`**

```python
# src/canvas_api_mcp/resources.py
"""Read-only context the model can pull without a tool call."""

from __future__ import annotations

from fastmcp import FastMCP

from .catalog import load_catalog
from .identity import fetch_identity
from .tools.orientation import do_my_courses


def register(mcp: FastMCP, get_client) -> None:
    @mcp.resource(
        "canvas://me",
        description="The authenticated Canvas user's identity and per-course roles.",
    )
    async def me() -> dict:
        return await fetch_identity(get_client())

    @mcp.resource(
        "canvas://courses",
        description="The user's active Canvas courses with code, term, and role.",
    )
    async def courses() -> list[dict]:
        return await do_my_courses(get_client())

    @mcp.resource(
        "canvas://api/catalog",
        description=(
            "Every endpoint this Canvas instance exposes, with method, path, summary, "
            "and parameter names. Generated from the instance's own API spec."
        ),
    )
    async def api_catalog() -> dict:
        entries = load_catalog()
        return {"count": len(entries), "endpoints": entries}
```

- [ ] **Step 5: Register both in `server.py`**

Add to the imports:

```python
from . import prompts, resources
```

and add after the tool registrations:

```python
resources.register(mcp, get_client)
prompts.register(mcp)
```

- [ ] **Step 6: Run tests and verify the full surface**

Run: `uv run pytest tests/ -v`
Expected: PASS — all tests green

Then confirm all 17 tools register:

```bash
CANVAS_BASE_URL=https://canvas.example.edu CANVAS_TOKEN=dummy \
uv run python -c "
import json, subprocess, os
msgs = [
  {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'t','version':'1'}}},
  {'jsonrpc':'2.0','method':'notifications/initialized'},
  {'jsonrpc':'2.0','id':2,'method':'tools/list'},
]
p = subprocess.run(['python','-m','canvas_api_mcp.server'],
    input='\n'.join(json.dumps(m) for m in msgs), capture_output=True, text=True, timeout=20, env=os.environ)
for line in p.stdout.splitlines():
    m = json.loads(line)
    if m.get('id') == 2:
        names = sorted(t['name'] for t in m['result']['tools'])
        print(len(names), names)
"
```

Expected: `17` and the list containing `canvas_request`, `course_announcements`, `course_content`, `get_assignment`, `get_page`, `list_assignments`, `list_files`, `my_courses`, `my_grades`, `my_submission`, `post_discussion_reply`, `read_discussion`, `read_file`, `search_canvas_api`, `submit_assignment`, `whats_due`, `whoami`

- [ ] **Step 7: Commit**

```bash
git add src/canvas_api_mcp/resources.py src/canvas_api_mcp/prompts.py src/canvas_api_mcp/server.py tests/test_resources_prompts.py
git commit -m "feat: canvas:// resources and workflow prompts"
```

---

### Task 17: README, licence, and live smoke test

**Files:**
- Create: `README.md`
- Create: `LICENSE`
- Create: `env.template`
- Create: `tests/test_live.py`

**Interfaces:**
- Consumes: the complete server.
- Produces: `tests/test_live.py` guarded by `CANVAS_LIVE_TESTS=1`; read-only calls plus a `dry_run` check for the write path.

- [ ] **Step 1: Write the live smoke test**

```python
# tests/test_live.py
"""Live tests against a real Canvas account.

Skipped unless CANVAS_LIVE_TESTS=1. Never run in CI. Read-only except for a
dry_run that sends nothing.
"""

import os

import pytest

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.tools.gateway import do_request
from canvas_api_mcp.tools.orientation import do_my_courses, do_whoami
from canvas_api_mcp.tools.student import do_whats_due

pytestmark = pytest.mark.skipif(
    os.environ.get("CANVAS_LIVE_TESTS") != "1",
    reason="set CANVAS_LIVE_TESTS=1 with real CANVAS_BASE_URL and CANVAS_TOKEN",
)


@pytest.fixture
async def client():
    c = CanvasClient(Config.from_env(os.environ))
    yield c
    await c.aclose()


async def test_whoami_returns_a_real_identity(client):
    me = await do_whoami(client)
    assert isinstance(me["id"], int)
    assert me["name"]


async def test_my_courses_returns_enrolments(client):
    courses = await do_my_courses(client)
    assert isinstance(courses, list)
    for course in courses:
        assert "id" in course and "name" in course


async def test_whats_due_runs_without_error(client):
    result = await do_whats_due(client)
    assert "items" in result
    assert result["warnings"] == []


async def test_gateway_reaches_an_uncurated_endpoint(client):
    result = await do_request(client, "GET", "/v1/users/self/groups")
    assert "error" not in result


async def test_write_path_dry_run_sends_nothing(client):
    result = await do_request(
        client, "POST", "/v1/courses/1/assignments/1/submissions", dry_run=True
    )
    assert result["dry_run"] is True
```

- [ ] **Step 2: Run it both ways**

Run: `uv run pytest tests/test_live.py -v`
Expected: 5 skipped

Run: `CANVAS_LIVE_TESTS=1 CANVAS_BASE_URL=https://canvas.nus.edu.sg CANVAS_TOKEN=<your-token> uv run pytest tests/test_live.py -v`
Expected: PASS — 5 passed against the real account

- [ ] **Step 3: Write `LICENSE`**

Standard MIT licence text, copyright holder `Johannsen Lum`, year `2026`.

- [ ] **Step 4: Write `env.template`**

```bash
# Your institution's Canvas URL — no trailing slash, no /api/v1
CANVAS_BASE_URL=https://canvas.nus.edu.sg

# Personal access token.
# Canvas -> Account -> Settings -> Approved Integrations -> "+ New access token"
# Treat this like a password: it can read your grades and submit work as you.
# Set an expiry date rather than leaving it as "never".
CANVAS_TOKEN=

# Optional: maximum pages to follow when Canvas paginates a list response.
CANVAS_MAX_PAGES=10
```

- [ ] **Step 5: Write `README.md`**

````markdown
# canvas-api-mcp

An MCP server for Canvas LMS. 15 curated tools for everyday student work, plus a
gateway that reaches every endpoint your Canvas instance exposes.

> **Personal-use software.** Canvas's API Policy requires OAuth for applications used
> by multiple people, and Canvas OAuth cannot be implemented safely by locally
> installed software (no PKCE, and `client_secret` cannot be shipped in a package).
> Use this with your own token on your own account. See [Compliance](#compliance).

## Requirements

- Python 3.11+
- A Canvas personal access token. Your institution must allow students to create them:
  check **Canvas → Account → Settings → Approved Integrations** for a
  **"+ New access token"** button.

## Install

```bash
uvx canvas-api-mcp   # no install step; downloads and runs
```

Or from source:

```bash
git clone https://github.com/<you>/canvas-api-mcp
cd canvas-api-mcp
uv sync
```

## Configure

Add to your MCP client's config. **Claude Code** (`~/.claude.json`):

```jsonc
{
  "mcpServers": {
    "canvas": {
      "command": "uvx",
      "args": ["canvas-api-mcp"],
      "env": {
        "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
        "CANVAS_TOKEN": "your-token-here"
      }
    }
  }
}
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS) and **Cursor** (`~/.cursor/mcp.json`) take the same `mcpServers` block.

Your token stays on your machine, in your own config file. It is never transmitted
anywhere except directly to your Canvas instance.

## Tools

| Tool | What it does |
|---|---|
| `whoami` | Identity and your role in each course |
| `my_courses` | Active courses with code, term, role |
| `whats_due` | Everything due, soonest first |
| `my_grades` | Current score per course |
| `list_assignments` | A course's assignments and submission state |
| `get_assignment` | One assignment in full, with rubric |
| `my_submission` | Your submission, score, and feedback |
| `submit_assignment` ✏️ | Submit work |
| `course_announcements` | Recent announcements |
| `course_content` | Modules and their contents |
| `list_files` | Files in a course |
| `read_file` | Extract text from PDF/DOCX/PPTX/text |
| `get_page` | A Canvas page, e.g. the syllabus |
| `read_discussion` | Topics, or one topic's replies |
| `post_discussion_reply` ✏️ | Post to a discussion |
| `search_canvas_api` | Find any endpoint by keyword |
| `canvas_request` ✏️ | Execute any endpoint |

✏️ writes to Canvas.

`search_canvas_api` + `canvas_request` reach all ~1,100 endpoints your instance
exposes. What they may do is decided by Canvas from your token's permissions — a
teacher token unlocks educator endpoints with no change to this server.

## Prompts

`week_ahead`, `study_pack`, `grade_check`.

## Other institutions

Works with any Canvas instance — set `CANVAS_BASE_URL`. To match your deployment's
exact feature set, regenerate the endpoint catalog:

```bash
python scripts/build_catalog.py https://canvas.yourschool.edu -o data/catalog.json
```

## Compliance

- **Academic integrity.** `submit_assignment` can submit anything, including
  AI-generated work. Submitting work that is not your own breaches the academic
  integrity rules of essentially every institution, and Canvas's API Policy
  explicitly prohibits use that violates them. That is on you.
- **Rate limiting.** The client throttles against Canvas's published quota. Do not
  remove it — overloading the API is prohibited.
- **Course material.** `read_file` fetches materials for your own study. Do not
  redistribute them.
- **Your token is password-equivalent.** It can read your grades and submit work as
  you. Set an expiry. Never commit it.

## Development

```bash
uv sync
uv run pytest -v

# Live tests against your real account (read-only)
CANVAS_LIVE_TESTS=1 uv run pytest tests/test_live.py -v
```

## Licence

MIT
````

- [ ] **Step 6: Verify the full suite passes**

Run: `uv run pytest -v`
Expected: PASS — all offline tests green, live tests skipped

- [ ] **Step 7: Commit**

```bash
git add README.md LICENSE env.template tests/test_live.py
git commit -m "docs: README, licence, env template, and live smoke tests"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Three-layer architecture | 8 (gateway), 9–15 (curated) |
| `client.py` auth | 2 |
| `Link` pagination + truncation reporting | 3 |
| Error translation incl. 403 vs rate limit, 404 vs feature-off | 4 |
| Rate-limit throttling (non-optional) | 5 |
| `catalog.py` + `build_catalog.py` regeneration | 6, 7 |
| Per-course role detection, never gating | 9 |
| 15 curated tools | 9 (2), 10 (1), 11 (5), 12 (1), 13 (3), 14 (1), 15 (2) = 15 |
| 2 gateway tools with `dry_run` | 8 |
| Write annotations + effect-first descriptions | 12, 15, 8 |
| 3 resources | 16 |
| 3 prompts | 16 |
| Config via client `env` block | 1 |
| Testing: unit, catalog, tool, live-gated | 2–7, 17 |
| Compliance notes in README | 17 |
| No institution hardcoding | 1 (required `CANVAS_BASE_URL`), 17 |
| No curated educator tools | Enforced by Global Constraints |

Curated tool count verified: `whoami`, `my_courses`, `whats_due`, `my_grades`,
`list_assignments`, `get_assignment`, `my_submission`, `submit_assignment`,
`course_announcements`, `course_content`, `list_files`, `read_file`, `get_page`,
`read_discussion`, `post_discussion_reply` = **15**, plus `search_canvas_api` and
`canvas_request` = **17 total**. Matches the spec.

**Placeholder scan:** No TBDs, no "add error handling", no "similar to Task N". Every
code step carries runnable code.

**Type consistency:** `CanvasResponse(data, truncated, pages_fetched)` is constructed in
Task 2 and consumed unchanged in Tasks 3, 8–15. `CanvasError(status, message, hint)` is
raised in Tasks 2 and 4 and caught in Tasks 8, 12, 14, 15. `_normalise_path` is defined
in Task 2 and imported by Task 8. `_course_id_from_context` is defined in Task 10 and
reused in Task 11. `do_my_courses` is defined in Task 9 and reused by Task 16's
`canvas://courses` resource. `register(mcp, get_client)` is the uniform signature for
every tool module; `prompts.register(mcp)` takes only `mcp` and is called that way in
Task 16.

**Known deviation from the spec, deliberate:** the spec's module layout lists
`tests/test_tools.py` as a single file. This plan splits tool tests per module
(`test_whats_due.py`, `test_grades.py`, `test_submit.py`, `test_content.py`,
`test_extract.py`, `test_discussions.py`) so each task ends with its own independently
runnable test file. Same coverage, better task boundaries.
