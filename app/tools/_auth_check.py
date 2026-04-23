"""Shared permission check helpers for MCP tools.

Usage in tool functions:
    from app.tools._auth_check import check_read, check_write

    result = check_read(db, app_name=app_name, domain=domain)
    if result is not None:
        return result  # JSON error string
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.auth.context import get_current_user
from app.auth.permissions import check_permission


def check_read(
    db: Session,
    *,
    app_name: str | None = None,
    domain: str | None = None,
) -> str | None:
    """Return None if allowed, or JSON error string if denied."""
    user = get_current_user()
    if user is None:
        return None  # Auth disabled — allow all
    if not check_permission(db, user, domain, app_name, "read"):
        return json.dumps(
            {"ok": False, "error": "Permission denied: read access required"},
            ensure_ascii=False,
        )
    return None


def check_write(
    db: Session,
    *,
    app_name: str | None = None,
    domain: str | None = None,
) -> str | None:
    """Return None if allowed, or JSON error string if denied."""
    user = get_current_user()
    if user is None:
        return None  # Auth disabled — allow all
    if not check_permission(db, user, domain, app_name, "write"):
        return json.dumps(
            {"ok": False, "error": "Permission denied: write access required"},
            ensure_ascii=False,
        )
    return None
