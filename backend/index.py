"""Vercel entrypoint (see [tool.vercel] in pyproject.toml): the ASGI app lives in app/main.py."""

from app.main import app

__all__ = ["app"]
