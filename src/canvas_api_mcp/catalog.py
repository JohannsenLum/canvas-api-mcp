"""Searchable index of every endpoint in the target Canvas instance."""

from __future__ import annotations

import argparse
import json
import os
import re
from functools import lru_cache
from pathlib import Path

import httpx

def _default_catalog_path() -> Path:
    """Locate data/catalog.json in either of the two layouts it can be in.

    - Installed from a wheel: hatchling's force-include config packages it
      at canvas_api_mcp/data/catalog.json, right next to this file.
    - Running from a source checkout (editable install, `uv run`, etc.):
      it lives at the repo root's data/catalog.json, outside src/, since
      force-include only rewrites the built artifact, not the source tree.
    """
    here = Path(__file__).resolve()
    installed = here.parent / "data" / "catalog.json"
    if installed.exists():
        return installed
    return here.parents[2] / "data" / "catalog.json"


DEFAULT_CATALOG = _default_catalog_path()

# Where `main()` writes to by default, and where load_catalog() looks if
# CANVAS_CATALOG_PATH isn't set, so `canvas-api-mcp-build-catalog <url>`
# with no flags is enough to make a school's own catalog take over with
# zero extra configuration (see issue #9).
CACHE_CATALOG_PATH = Path.home() / ".cache" / "canvas-api-mcp" / "catalog.json"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@lru_cache(maxsize=4)
def _load(path_str: str) -> tuple[dict, ...]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(
            f"Endpoint catalog not found at {path}. Regenerate it against your "
            "own Canvas instance with: canvas-api-mcp-build-catalog <your-canvas-base-url> "
            "(or `python scripts/build_catalog.py <url>` from a source checkout)."
        )
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def _resolve_catalog_path(path: Path | None) -> Path:
    """Priority: explicit arg > CANVAS_CATALOG_PATH > user cache dir > bundled default."""
    if path is not None:
        return path
    env_path = (os.environ.get("CANVAS_CATALOG_PATH") or "").strip()
    if env_path:
        return Path(env_path)
    if CACHE_CATALOG_PATH.exists():
        return CACHE_CATALOG_PATH
    return DEFAULT_CATALOG


def load_catalog(path: Path | None = None) -> list[dict]:
    return list(_load(str(_resolve_catalog_path(path))))


def _score(entry: dict, terms: list[str]) -> int:
    """Weight nickname matches highest, then summary, then path."""
    nickname = " ".join(_tokens(entry.get("nickname", "")))
    summary = " ".join(_tokens(entry.get("summary", "")))
    path = " ".join(_tokens(entry.get("path", "")))
    family = " ".join(_tokens(entry.get("family", "")))

    total = 0
    for term in terms:
        if term in nickname.split():
            total += 5
        elif term in nickname:
            total += 3
        if term in summary.split():
            total += 3
        if term in path.split():
            total += 2
        if term in family.split():
            total += 2
    return total


def search(
    query: str,
    method: str | None = None,
    limit: int = 10,
    entries: list[dict] | None = None,
) -> list[dict]:
    pool = entries if entries is not None else load_catalog()
    if method:
        wanted = method.upper()
        pool = [e for e in pool if e.get("method", "").upper() == wanted]

    terms = _tokens(query)
    if not terms:
        return []

    scored = [(s, e) for e in pool if (s := _score(e, terms)) > 0]
    scored.sort(key=lambda pair: (-pair[0], len(pair[1].get("path", ""))))
    return [entry for _, entry in scored[:limit]]


# --- Catalog regeneration -------------------------------------------------
#
# Lives here, not in scripts/build_catalog.py, so it ships inside the wheel:
# pyproject.toml only packages src/canvas_api_mcp, and scripts/ never makes
# it into a pip/uvx install. scripts/build_catalog.py is kept as a thin
# wrapper around this for source checkouts (see that file).
#
# fetch/parse/write are kept separate so parse_swagger() (the part with
# actual logic) can be tested against a plain fixture, with no network
# and no respx involved.

DOC_ROOT = "/doc/api"


def fetch_raw_docs(base_url: str, timeout: float = 40.0) -> dict:
    """Fetch the Swagger index and every resource family doc it references.

    Every Canvas instance serves this at /doc/api/api-docs.json, so the
    result reflects that deployment's version and enabled feature set
    exactly. Network-only. Feed the result to parse_swagger() for entries.
    """
    base = base_url.rstrip("/")
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        index = client.get(f"{base}{DOC_ROOT}/api-docs.json").raise_for_status().json()

        families: dict[str, dict] = {}
        for resource in index.get("apis", []):
            rel = resource.get("path", "")
            if not rel:
                continue
            family = rel.lstrip("/").removesuffix(".json")
            families[family] = client.get(f"{base}{DOC_ROOT}{rel}").raise_for_status().json()
    return {"families": families}


def parse_swagger(raw: dict) -> list[dict]:
    """Flatten fetched Swagger family docs into catalog entries. Pure, no network."""
    entries: list[dict] = []
    for family, spec in raw.get("families", {}).items():
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


def write_catalog(entries: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(entries, indent=1), encoding="utf-8")


def build_catalog(base_url: str, timeout: float = 40.0) -> list[dict]:
    """Fetch + parse in one call: the convenience path most callers want."""
    return parse_swagger(fetch_raw_docs(base_url, timeout=timeout))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the Canvas endpoint catalog from an instance's own Swagger spec."
    )
    parser.add_argument("base_url", help="e.g. https://canvas.nus.edu.sg")
    parser.add_argument(
        "-o",
        "--output",
        default=str(CACHE_CATALOG_PATH),
        help=f"defaults to {CACHE_CATALOG_PATH}, which load_catalog() checks automatically",
    )
    args = parser.parse_args()

    entries = build_catalog(args.base_url)
    out = Path(args.output)
    write_catalog(entries, out)
    print(f"wrote {len(entries)} endpoints to {out}")


if __name__ == "__main__":
    main()
