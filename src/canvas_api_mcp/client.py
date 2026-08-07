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

            response = await self._client.request(method, url, params=params, json=json)
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
                "This usually means the request was redirected to a login page — "
                "check that CANVAS_TOKEN is set and has not expired.",
            ) from exc
