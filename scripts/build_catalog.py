#!/usr/bin/env python3
"""Build the Canvas endpoint catalog from an instance's own Swagger spec.

Every Canvas instance serves its API docs at /doc/api/api-docs.json, so the
catalog matches that deployment's version and enabled feature set exactly.

This is a thin wrapper for source checkouts. The actual implementation lives
in canvas_api_mcp.catalog so it also ships inside the installed package:
pip/uvx installs get it as the `canvas-api-mcp-build-catalog` command with
no git checkout required (see issue #9).

Usage:
    python scripts/build_catalog.py https://canvas.nus.edu.sg
    # or, once installed:
    canvas-api-mcp-build-catalog https://canvas.nus.edu.sg
"""

from __future__ import annotations

from canvas_api_mcp.catalog import (  # noqa: F401
    build_catalog,
    fetch_raw_docs,
    main,
    parse_swagger,
    write_catalog,
)

if __name__ == "__main__":
    main()
