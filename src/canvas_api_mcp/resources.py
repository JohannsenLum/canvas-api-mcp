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
