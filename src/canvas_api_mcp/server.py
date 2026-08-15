# src/canvas_api_mcp/server.py
"""FastMCP server entrypoint."""

from __future__ import annotations

import asyncio
import os
import sys

from fastmcp import FastMCP

from . import prompts, resources
from .client import CanvasClient, CanvasError
from .config import Config, ConfigError
from .tools import content, discussions, gateway, orientation, student

mcp = FastMCP(
    "Canvas",
    instructions=(
        "You are a Canvas LMS assistant operating on the user's own account via the "
        "Canvas REST API. Prefer the curated tools for everyday questions: whats_due, "
        "my_courses, my_grades. For anything they do not cover, use search_canvas_api "
        "to find the right endpoint and canvas_request to execute it. "
        "Permissions are enforced by Canvas per access token: a 403 means the account "
        "lacks that role, not that the request was malformed. Never guess at grades or "
        "deadlines. Always read them from a tool result."
    ),
)

_client: CanvasClient | None = None


def get_client() -> CanvasClient:
    """Lazily build the shared client so config errors surface on first tool use."""
    global _client
    if _client is None:
        _client = CanvasClient(Config.from_env(os.environ))
    return _client


content.register(mcp, get_client)
discussions.register(mcp, get_client)
gateway.register(mcp, get_client)
orientation.register(mcp, get_client)
student.register(mcp, get_client)
resources.register(mcp, get_client)
prompts.register(mcp)


def _redact_token(token: str) -> str:
    """Report presence and length only — never a slice, hash, or anything else
    derived from the token. A prefix is still a leak."""
    return f"set ({len(token)} chars)" if token else "not set"


def _print_config(config: Config) -> None:
    print(f"CANVAS_BASE_URL: {config.base_url}")
    print(f"CANVAS_TOKEN: {_redact_token(config.token)}")
    print(f"CANVAS_MAX_PAGES: {config.max_pages}")


def cmd_config() -> int:
    """Print resolved config with the token redacted. Does not touch Canvas."""
    try:
        config = Config.from_env(os.environ)
    except ConfigError as exc:
        # ConfigError text (see config.py) is guidance only and never contains
        # the token itself, so it's safe to print as-is.
        print(str(exc), file=sys.stderr)
        return 1
    _print_config(config)
    return 0


async def _run_test(config: Config) -> int:
    client = CanvasClient(config)
    try:
        me = await client.request("GET", "users/self")
        courses = await client.request("GET", "courses")
    except CanvasError as exc:
        # Reuse client.py's own translated message rather than writing new
        # error text — this is what already handles 401/403/404/5xx and
        # transport failures.
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        await client.aclose()

    name = me.data.get("name", "?") if isinstance(me.data, dict) else "?"
    course_count = len(courses.data) if isinstance(courses.data, list) else 0
    print(f"Connected as: {name}")
    print(f"Courses visible: {course_count}")
    if courses.truncated:
        print("(course list truncated by CANVAS_MAX_PAGES — raise it for a full count)")
    return 0


def cmd_test() -> int:
    """Call whoami, print account name and course count. Does not write to Canvas."""
    try:
        config = Config.from_env(os.environ)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return asyncio.run(_run_test(config))


def main() -> None:
    argv = sys.argv[1:]

    # These branch before mcp.run() and never touch stdio, so a client
    # spawning the server with no arguments is unaffected.
    if "--config" in argv:
        raise SystemExit(cmd_config())
    if "--test" in argv:
        raise SystemExit(cmd_test())

    mcp.run()


if __name__ == "__main__":
    main()