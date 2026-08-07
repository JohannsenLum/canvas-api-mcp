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
