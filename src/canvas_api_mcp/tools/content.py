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
