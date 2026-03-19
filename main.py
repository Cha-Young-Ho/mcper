"""Shim entrypoint so ``uvicorn main:app`` keeps working."""

from app.main import app

__all__ = ["app"]
