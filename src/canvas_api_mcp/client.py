"""HTTP client for the Canvas REST API.

Owns authentication, pagination, rate limiting, and error translation.
No tool module should construct HTTP requests directly.
"""

from __future__ import annotations

import asyncio
import json as jsonlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Config

RATE_LIMIT_MARKER = "rate limit exceeded"
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0.5, 1.0)
LOW_QUOTA_THRESHOLD = 100.0
THROTTLE_PAUSE_SECONDS = 1.0


def _is_rate_limited(response: httpx.Response) -> bool:
    """Canvas signals throttling with a 403 whose body names the rate limit."""
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    return RATE_LIMIT_MARKER in response.text.lower()


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
    """Resolve a caller-supplied path to an absolute Canvas API path.

    Shorthand is expanded; anything already under ``/api`` is passed through
    untouched so non-versioned Canvas APIs stay reachable::

        courses           -> /api/v1/courses
        /courses          -> /api/v1/courses
        /v1/courses       -> /api/v1/courses
        /api/v1/courses   -> /api/v1/courses    (already explicit)
        /api/graphql      -> /api/graphql       (GraphQL is not under /v1)

    This is the single point where a caller-supplied string becomes the URL a
    request is sent to, so it validates rather than trusts. ``canvas_request``
    accepts arbitrary paths from a model, and a bearer token rides on every
    request, so a path that escaped to another host or smuggled a header would
    leak that token.
    """
    p = path.strip()

    if not p:
        raise CanvasError(0, "Path must not be empty.")

    # Absolute URLs would send the token wherever the caller chooses.
    if "://" in p:
        raise CanvasError(
            0,
            f"Path must be relative to the Canvas host, got a full URL: {path!r}. "
            "The base URL comes from CANVAS_BASE_URL and cannot be overridden per request.",
        )

    # CR/LF would allow request-line or header smuggling; backslashes and other
    # control characters have no legitimate place in a Canvas path.
    if any(ord(c) < 32 or c == "\x7f" for c in p) or "\\" in p:
        raise CanvasError(
            0, f"Path must not contain control characters or backslashes: {path!r}"
        )

    p = "/" + p.lstrip("/")

    # `..` could climb out of /api and reach unrelated routes on the same host.
    if ".." in p.split("/"):
        raise CanvasError(0, f"Path must not contain '..' segments: {path!r}")

    # Already explicit: /api, /api/v1/..., /api/graphql, any future /api/* surface.
    if p == "/api" or p.startswith("/api/"):
        return p

    # Versioned shorthand: /v1/courses -> /api/v1/courses
    if p == "/v1" or p.startswith("/v1/"):
        return "/api" + p

    # Bare shorthand: courses -> /api/v1/courses
    return "/api/v1" + p


def _same_origin(candidate: str, base_url: str) -> bool:
    """True if `candidate` targets the same scheme/host/port as `base_url`.

    A relative URL (no host) is same-origin by definition: httpx resolves it
    against the client's base_url.
    """
    try:
        target = httpx.URL(candidate)
    except (httpx.InvalidURL, ValueError):
        return False
    if not target.host:
        return True
    base = httpx.URL(base_url)
    # httpx normalises away default ports, so :443 and an absent port compare equal.
    return (
        target.scheme.lower() == base.scheme.lower()
        and target.host.lower() == base.host.lower()
        and target.port == base.port
    )


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


class CanvasClient:
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

    async def aclose(self) -> None:
        await self._client.aclose()

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

            try:
                response = await self._client.request(method, url, params=params, json=json)
            except httpx.HTTPError as exc:
                # Everything self._client.request can raise here is transport-level
                # (DNS, connection refused, timeout, ...). httpx only raises
                # HTTPStatusError if you ask it to via raise_for_status(), which we
                # don't. A bad CANVAS_BASE_URL is the most likely first-time mistake,
                # so name it explicitly rather than letting an errno string surface.
                raise CanvasError(
                    0,
                    f"Could not reach {self._config.base_url} ({exc}).",
                    "Check that CANVAS_BASE_URL is correct and the host is "
                    "reachable from this machine.",
                ) from exc
            self._note_quota(response)

            transient = response.status_code >= 500 or _is_rate_limited(response)
            if transient and attempt < MAX_ATTEMPTS - 1:
                await self._sleep(BACKOFF_SECONDS[attempt])
                continue
            return response

        return response  # pragma: no cover - loop always returns

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
            response = await self._send(method.upper(), url, query, json)
            self._raise_for_status(response)
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
            # The Link header is server-controlled, and every request carries the
            # Authorization header, so following an off-origin "next" would hand
            # the user's Canvas token to whatever host that header names. Stop
            # instead, and report it as truncation rather than failing the call.
            if not _same_origin(next_url, self._config.base_url):
                truncated = True
                break
            if pages >= self._config.max_pages:
                truncated = True
                break
            url, query, json = next_url, None, None

        data = merged if isinstance(first, list) else first
        return CanvasResponse(data=data, truncated=truncated, pages_fetched=pages)

    def _parse(self, response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except (jsonlib.JSONDecodeError, ValueError) as exc:
            raise CanvasError(
                response.status_code,
                "Canvas returned a response that is not valid JSON.",
                "This usually means the request was redirected to a login page. "
                "Check that CANVAS_TOKEN is set and has not expired.",
            ) from exc
