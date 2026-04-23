"""Domain-based RBAC permission checking.

Roles: VIEWER (read) < EDITOR (read+write) < ADMIN (all).
Permission resolution priority: exact (domain+app) > domain-wide > global > None.
System admins (User.is_admin=True) bypass all checks.
"""

from __future__ import annotations

import logging
from enum import IntEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.context import CurrentUser
from app.db.rbac_models import ContentRestriction, UserPermission

logger = logging.getLogger(__name__)


class Role(IntEnum):
    VIEWER = 1
    EDITOR = 2
    ADMIN = 3


_ROLE_MAP = {"viewer": Role.VIEWER, "editor": Role.EDITOR, "admin": Role.ADMIN}


def _parse_role(role_str: str) -> Role:
    return _ROLE_MAP.get(role_str.lower(), Role.VIEWER)


def get_effective_role(
    db: Session,
    user: CurrentUser,
    domain_slug: str | None = None,
    app_name: str | None = None,
) -> Role | None:
    """Resolve the highest-priority role for (user, domain, app).

    Resolution order (most specific wins):
      1. Exact match: (domain_slug, app_name)
      2. Domain-wide: (domain_slug, NULL)
      3. Global: (NULL, NULL)

    Returns None if user has no applicable permission.
    """
    if user.is_admin:
        return Role.ADMIN

    rows = db.scalars(
        select(UserPermission).where(UserPermission.user_id == user.user_id)
    ).all()

    if not rows:
        return None

    best: Role | None = None

    for perm in rows:
        # Exact match (highest priority)
        if perm.domain_slug == domain_slug and perm.app_name == app_name:
            role = _parse_role(perm.role)
            if best is None or role > best:
                best = role
            continue

        # Domain-wide (matches if app_name is NULL in permission)
        if (
            perm.domain_slug == domain_slug
            and perm.app_name is None
            and app_name is not None
        ):
            role = _parse_role(perm.role)
            if best is None or role > best:
                best = role
            continue

        # Global (both NULL in permission)
        if perm.domain_slug is None and perm.app_name is None:
            role = _parse_role(perm.role)
            if best is None or role > best:
                best = role

    return best


def check_permission(
    db: Session,
    user: CurrentUser,
    domain_slug: str | None,
    app_name: str | None,
    action: str,
) -> bool:
    """Check if user can perform action on (domain, app).

    Args:
        action: "read" (VIEWER+), "write" (EDITOR+), "admin" (ADMIN only)
    """
    role = get_effective_role(db, user, domain_slug, app_name)
    if role is None:
        return False
    if action == "read":
        return role >= Role.VIEWER
    if action == "write":
        return role >= Role.EDITOR
    return role >= Role.ADMIN


def filter_restricted_sections(
    db: Session,
    user: CurrentUser,
    domain_slug: str | None,
    app_name: str | None,
    sections: list[str],
) -> list[str]:
    """Remove sections the user's role is blocked from viewing.

    A ContentRestriction with restricted_role='viewer' blocks viewers.
    A ContentRestriction with restricted_role='editor' blocks viewers AND editors.
    """
    if user.is_admin:
        return sections

    role = get_effective_role(db, user, domain_slug, app_name)
    if role is None:
        return []

    # Fetch restrictions for this domain/app
    stmt = select(ContentRestriction).where(
        ContentRestriction.section_name.in_(sections)
    )
    # Filter by matching domain/app (NULL = applies to all)
    restrictions = db.scalars(stmt).all()

    blocked: set[str] = set()
    for r in restrictions:
        # Check if restriction applies to this domain/app
        if r.domain_slug is not None and r.domain_slug != domain_slug:
            continue
        if r.app_name is not None and r.app_name != app_name:
            continue
        # Block if user's role is at or below the restricted_role
        restricted_level = _parse_role(r.restricted_role)
        if role <= restricted_level:
            blocked.add(r.section_name)

    return [s for s in sections if s not in blocked]
