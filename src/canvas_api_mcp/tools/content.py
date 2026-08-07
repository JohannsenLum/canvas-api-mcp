# src/canvas_api_mcp/tools/content.py
"""Course structure, files, and pages."""

from __future__ import annotations

import httpx
from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import CanvasClient, CanvasError
from ..extract import UnsupportedFileType, extract_text

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
                    for item in module.get("items") or []
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

    # Pre-signed download links are short-lived; do_read_file re-fetches metadata on every
    # call, so a fresh link is one retry away.
    _DOWNLOAD_HINTS = {
        403: "The download link has expired. Call read_file again to get a fresh one.",
        410: "The download link has expired. Call read_file again to get a fresh one.",
        404: "The file may have been deleted from Canvas since it was listed.",
    }
    
    # The download URL is pre-signed and must NOT carry the Authorization header.
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as raw:
        try:
            file_response = await raw.get(download_url)
            file_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Report the status, never the exception: httpx puts the failing URL in
            # its message, and that URL's `verifier` param is a credential in its own
            # right — anyone holding it can fetch the file without authenticating.
            status = exc.response.status_code
            return {
                "error": True,
                "status": status,
                "message": f"Could not download {display_name!r} (HTTP {status}).",
                "hint": _DOWNLOAD_HINTS.get(status, "This is a Canvas-side storage failure."),
            }
        except httpx.HTTPError:
            return {
                "error": True,
                "status": 0,
                "message": f"Could not reach Canvas file storage for {display_name!r}.",
                "hint": "Check your network connection, then try again.",
            }
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
