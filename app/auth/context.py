"""Thread-safe user context for MCP tools via contextvars.

ASGI gate (mcp_host_gate.py) sets the contextvar after Bearer token validation.
MCP tools call get_current_user() to retrieve it — None when auth is disabled.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentUser:
    """Immutable snapshot of the authenticated user."""

    user_id: int
    username: str
    is_admin: bool


current_user_var: contextvars.ContextVar[CurrentUser | None] = contextvars.ContextVar(
    "current_user", default=None
)


def get_current_user() -> CurrentUser | None:
    """Return the current user, or None if auth is disabled / unauthenticated."""
    return current_user_var.get()


def require_current_user() -> CurrentUser:
    """Return the current user, or raise PermissionError."""
    user = current_user_var.get()
    if user is None:
        raise PermissionError("Authentication required")
    return user
