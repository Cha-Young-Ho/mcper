"""Admin 유저 관리 — 유저 CRUD + 도메인/앱 권한 관리."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.auth.service import hash_password
from app.db.auth_models import User
from app.db.database import get_db
from app.db.rbac_models import Domain, UserPermission
from app.routers.admin_base import templates

router = APIRouter(prefix="/admin", tags=["admin-users"])

VALID_ROLES = {"admin", "editor", "viewer"}


# ── 유저 목록 ────────────────────────────────────────────────────────────────


@router.get("/users")
def user_list(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    users = db.scalars(select(User).order_by(User.id)).all()
    return templates.TemplateResponse(
        request,
        "admin/users/user_list.html",
        {"request": request, "title": "유저 관리", "users": users},
    )


# ── 유저 생성 ────────────────────────────────────────────────────────────────


@router.get("/users/new")
def user_new_form(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    return templates.TemplateResponse(
        request,
        "admin/users/user_form.html",
        {
            "request": request,
            "title": "유저 생성",
            "mode": "create",
            "user_obj": None,
            "error": None,
        },
    )


@router.post("/users/new")
def user_new_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(""),
    is_admin: str = Form(""),
):
    key = username.strip()
    if not key:
        return _form_error(request, None, "사용자 이름은 필수입니다.")
    if db.scalars(select(User).where(User.username == key).limit(1)).first():
        return _form_error(request, None, f"이미 존재하는 사용자: {key}")
    if not password.strip():
        return _form_error(request, None, "비밀번호는 필수입니다.")

    u = User(
        username=key,
        email=email.strip() or None,
        hashed_password=hash_password(password),
        is_admin=is_admin == "on",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return RedirectResponse(f"/admin/users/{u.id}", status_code=303)


# ── 유저 상세 (+ 권한 관리) ───────────────────────────────────────────────────


@router.get("/users/{user_id}")
def user_detail(
    request: Request,
    user_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "유저를 찾을 수 없습니다.")
    permissions = db.scalars(
        select(UserPermission)
        .where(UserPermission.user_id == user_id)
        .order_by(UserPermission.id)
    ).all()
    domains = db.scalars(select(Domain).order_by(Domain.id)).all()
    return templates.TemplateResponse(
        request,
        "admin/users/user_detail.html",
        {
            "request": request,
            "title": f"유저: {u.username}",
            "user_obj": u,
            "permissions": permissions,
            "domains": domains,
            "roles": sorted(VALID_ROLES),
        },
    )


# ── 유저 수정 ────────────────────────────────────────────────────────────────


@router.post("/users/{user_id}/edit")
def user_edit_submit(
    request: Request,
    user_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    email: str = Form(""),
    password: str = Form(""),
    is_admin: str = Form(""),
):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "유저를 찾을 수 없습니다.")
    u.email = email.strip() or None
    u.is_admin = is_admin == "on"
    if password.strip():
        u.hashed_password = hash_password(password)
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


# ── 유저 활성/비활성 토글 ─────────────────────────────────────────────────────


@router.post("/users/{user_id}/toggle-active")
def user_toggle_active(
    user_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "유저를 찾을 수 없습니다.")
    u.is_active = not u.is_active
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


# ── 유저 삭제 ────────────────────────────────────────────────────────────────


@router.post("/users/{user_id}/delete")
def user_delete(
    user_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "유저를 찾을 수 없습니다.")
    db.delete(u)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


# ── 권한 추가 ────────────────────────────────────────────────────────────────


@router.post("/users/{user_id}/permissions/add")
def permission_add(
    user_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    domain_slug: str = Form(""),
    app_name: str = Form(""),
    role: str = Form("viewer"),
):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "유저를 찾을 수 없습니다.")
    if role not in VALID_ROLES:
        raise HTTPException(400, f"유효하지 않은 역할: {role}")
    ds = domain_slug.strip() or None
    an = app_name.strip().lower() or None
    existing = db.scalars(
        select(UserPermission).where(
            UserPermission.user_id == user_id,
            UserPermission.domain_slug == ds,
            UserPermission.app_name == an,
        )
    ).first()
    if existing:
        existing.role = role
    else:
        db.add(UserPermission(user_id=user_id, domain_slug=ds, app_name=an, role=role))
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


# ── 권한 삭제 ────────────────────────────────────────────────────────────────


@router.post("/users/{user_id}/permissions/{perm_id}/delete")
def permission_delete(
    user_id: int,
    perm_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    db.execute(
        delete(UserPermission).where(
            UserPermission.id == perm_id, UserPermission.user_id == user_id
        )
    )
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _form_error(request: Request, user_obj, error: str):
    return templates.TemplateResponse(
        request,
        "admin/users/user_form.html",
        {
            "request": request,
            "title": "유저 생성"
            if user_obj is None
            else f"유저 수정: {user_obj.username}",
            "mode": "create" if user_obj is None else "edit",
            "user_obj": user_obj,
            "error": error,
        },
        status_code=400,
    )
