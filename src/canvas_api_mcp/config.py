"""Configuration loading and validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

TOKEN_HELP = (
    "Create one in Canvas: Account -> Settings -> Approved Integrations -> "
    "'+ New access token'. Then set it in your MCP client config, e.g. "
    '"env": {"CANVAS_TOKEN": "..."} in ~/.claude.json. '
    "See <your-canvas>/profile/settings"
)


class ConfigError(Exception):
    """Raised when environment configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    base_url: str
    token: str
    max_pages: int = 10

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Config:
        base_url = (env.get("CANVAS_BASE_URL") or "").strip()
        if not base_url:
            raise ConfigError(
                "CANVAS_BASE_URL is not set. Set it to your institution's Canvas "
                "URL, e.g. https://canvas.nus.edu.sg"
            )

        # Accept a pasted API URL and normalise it back to the site root.
        base_url = base_url.rstrip("/")
        for suffix in ("/api/v1", "/api"):
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]
        base_url = base_url.rstrip("/")

        if not base_url.startswith("https://"):
            raise ConfigError(
                f"CANVAS_BASE_URL must use https, got: {base_url}. "
                "Access tokens are password-equivalent and must not travel over http."
            )

        token = (env.get("CANVAS_TOKEN") or "").strip()
        if not token:
            raise ConfigError(f"CANVAS_TOKEN is not set. {TOKEN_HELP}")

        raw_pages = (env.get("CANVAS_MAX_PAGES") or "10").strip()
        try:
            max_pages = int(raw_pages)
        except ValueError as exc:
            raise ConfigError(
                f"CANVAS_MAX_PAGES must be an integer, got: {raw_pages!r}"
            ) from exc
        if max_pages < 1:
            raise ConfigError("CANVAS_MAX_PAGES must be at least 1")

        return cls(base_url=base_url, token=token, max_pages=max_pages)

    @property
    def api_root(self) -> str:
        return f"{self.base_url}/api"
