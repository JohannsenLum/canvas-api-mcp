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
