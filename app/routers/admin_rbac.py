"""Admin REST API: Domain-based RBAC management.

Endpoints:
  GET    /admin/api/domains
  GET    /admin/api/users/{user_id}/permissions
  POST   /admin/api/users/{user_id}/permissions
  DELETE /admin/api/users/{user_id}/permissions/{perm_id}
  GET    /admin/api/content-restrictions
  POST   /admin/api/content-restrictions
  DELETE /admin/api/content-restrictions/{restriction_id}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.db.rbac_models import ContentRestriction, Domain, UserPermission

router = APIRouter(prefix="/admin/api", tags=["admin-rbac"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class PermissionCreate(BaseModel):
    domain_slug: str | None = None
    app_name: str | None = None
    role: str = "viewer"


class ContentRestrictionCreate(BaseModel):
    domain_slug: str | None = None
    app_name: str | None = None
    section_name: str
    restricted_role: str = "viewer"


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------


@router.get("/domains")
def list_domains(
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Domain).order_by(Domain.id)).all()
    return {
        "domains": [
            {
                "id": d.id,
                "slug": d.slug,
                "display_name": d.display_name,
                "description": d.description,
            }
            for d in rows
        ]
    }


# ---------------------------------------------------------------------------
# User Permissions
# ---------------------------------------------------------------------------


@router.get("/users/{user_id}/permissions")
def get_user_permissions(
    user_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(UserPermission)
        .where(UserPermission.user_id == user_id)
        .order_by(UserPermission.id)
    ).all()
    return {
        "user_id": user_id,
        "permissions": [
            {
                "id": p.id,
                "domain_slug": p.domain_slug,
                "app_name": p.app_name,
                "role": p.role,
                "created_at": str(p.created_at),
            }
            for p in rows
        ],
    }


@router.post("/users/{user_id}/permissions", status_code=status.HTTP_201_CREATED)
def create_user_permission(
    user_id: int,
    body: PermissionCreate,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    if body.role not in ("admin", "editor", "viewer"):
        raise HTTPException(400, f"Invalid role: {body.role}")
    perm = UserPermission(
        user_id=user_id,
        domain_slug=body.domain_slug or None,
        app_name=body.app_name or None,
        role=body.role,
    )
    db.add(perm)
    try:
        db.commit()
        db.refresh(perm)
    except Exception:
        db.rollback()
        raise HTTPException(
            409, "Permission already exists for this user/domain/app combination"
        )
    return {
        "id": perm.id,
        "user_id": perm.user_id,
        "domain_slug": perm.domain_slug,
        "app_name": perm.app_name,
        "role": perm.role,
    }


@router.delete("/users/{user_id}/permissions/{perm_id}")
def delete_user_permission(
    user_id: int,
    perm_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    perm = db.get(UserPermission, perm_id)
    if perm is None or perm.user_id != user_id:
        raise HTTPException(404, "Permission not found")
    db.delete(perm)
    db.commit()
    return {"ok": True, "deleted_id": perm_id}


# ---------------------------------------------------------------------------
# Content Restrictions
# ---------------------------------------------------------------------------


@router.get("/content-restrictions")
def list_content_restrictions(
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(ContentRestriction).order_by(ContentRestriction.id)).all()
    return {
        "restrictions": [
            {
                "id": r.id,
                "domain_slug": r.domain_slug,
                "app_name": r.app_name,
                "section_name": r.section_name,
                "restricted_role": r.restricted_role,
                "created_at": str(r.created_at),
            }
            for r in rows
        ]
    }


@router.post("/content-restrictions", status_code=status.HTTP_201_CREATED)
def create_content_restriction(
    body: ContentRestrictionCreate,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    if body.restricted_role not in ("viewer", "editor"):
        raise HTTPException(400, f"Invalid restricted_role: {body.restricted_role}")
    cr = ContentRestriction(
        domain_slug=body.domain_slug or None,
        app_name=body.app_name or None,
        section_name=body.section_name,
        restricted_role=body.restricted_role,
    )
    db.add(cr)
    try:
        db.commit()
        db.refresh(cr)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Content restriction already exists")
    return {
        "id": cr.id,
        "domain_slug": cr.domain_slug,
        "app_name": cr.app_name,
        "section_name": cr.section_name,
        "restricted_role": cr.restricted_role,
    }


@router.delete("/content-restrictions/{restriction_id}")
def delete_content_restriction(
    restriction_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    cr = db.get(ContentRestriction, restriction_id)
    if cr is None:
        raise HTTPException(404, "Content restriction not found")
    db.delete(cr)
    db.commit()
    return {"ok": True, "deleted_id": restriction_id}
