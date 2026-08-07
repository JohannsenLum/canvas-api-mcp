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
