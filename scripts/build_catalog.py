#!/usr/bin/env python3
"""Build the Canvas endpoint catalog from an instance's own Swagger spec.

Every Canvas instance serves its API docs at /doc/api/api-docs.json, so the
catalog matches that deployment's version and enabled feature set exactly.

Usage:
    python scripts/build_catalog.py https://canvas.nus.edu.sg -o data/catalog.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

DOC_ROOT = "/doc/api"


def build_catalog(base_url: str, timeout: float = 40.0) -> list[dict]:
    base = base_url.rstrip("/")
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        index = client.get(f"{base}{DOC_ROOT}/api-docs.json").raise_for_status().json()

        entries: list[dict] = []
        for resource in index.get("apis", []):
            rel = resource.get("path", "")
            if not rel:
                continue
            family = rel.lstrip("/").removesuffix(".json")
            spec = client.get(f"{base}{DOC_ROOT}{rel}").raise_for_status().json()

            for api in spec.get("apis", []):
                path = api.get("path", "")
                for op in api.get("operations", []):
                    entries.append(
                        {
                            "family": family,
                            "method": op.get("method", "").upper(),
                            "path": path,
                            "nickname": op.get("nickname", ""),
                            "summary": (op.get("summary") or "").strip(),
                            "parameters": [
                                p.get("name", "")
                                for p in op.get("parameters", [])
                                if p.get("name")
                            ],
                        }
                    )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="e.g. https://canvas.nus.edu.sg")
    parser.add_argument("-o", "--output", default="data/catalog.json")
    args = parser.parse_args()

    entries = build_catalog(args.base_url)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    print(f"wrote {len(entries)} endpoints to {out}")


if __name__ == "__main__":
    main()
