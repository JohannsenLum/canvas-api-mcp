"""Configuration loading and validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

SETUP_GUIDE_URL = "https://mcp.johannsenlum.com/canvas-lms/install"


def token_help(base_url: str | None = None) -> str:
    """Explain how to get a token, pointing at the user's own Canvas when known."""
    settings = f"{base_url}/profile/settings" if base_url else "<your-canvas>/profile/settings"
    return (
        f"Create one at {settings} -> Approved Integrations -> '+ New access token'. "
        "Set an expiry rather than leaving it blank, and copy the token immediately — "
        "Canvas shows it only once. Then put it in your MCP client config, e.g. "
        '"env": {"CANVAS_TOKEN": "..."}. '
        f"Full walkthrough: {SETUP_GUIDE_URL}"
    )


# Kept for callers that have no base URL to hand.
TOKEN_HELP = token_help()


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
            raise ConfigError(f"CANVAS_TOKEN is not set. {token_help(base_url)}")

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
