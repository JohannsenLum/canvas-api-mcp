"""Searchable index of every endpoint in the target Canvas instance."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "data" / "catalog.json"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@lru_cache(maxsize=4)
def _load(path_str: str) -> tuple[dict, ...]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(
            f"Endpoint catalog not found at {path}. Regenerate it with: "
            "python scripts/build_catalog.py <your-canvas-base-url>"
        )
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def load_catalog(path: Path | None = None) -> list[dict]:
    return list(_load(str(path or DEFAULT_CATALOG)))


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
