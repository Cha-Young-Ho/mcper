"""Auth 라우터: /auth/login, /auth/logout, /auth/me, /auth/api-keys."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.auth.service import create_access_token, hash_api_key, verify_password
from app.config import settings
from app.db.auth_models import ApiKey, User
from app.db.database import get_db

_auth_enabled = os.environ.get("MCPER_AUTH_ENABLED", "false").lower() in ("1", "true", "yes")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
def login_page(request: Request):
    """로그인 폼 페이지. MCPER_AUTH_ENABLED=false면 /admin으로 리다이렉트."""
    if not _auth_enabled:
        return RedirectResponse("/admin")
    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "google_enabled": bool(settings.auth.google_client_id),
            "github_enabled": bool(settings.auth.github_client_id),
        },
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """ID/PW 폼 로그인 → JWT 쿠키 설정 → /admin 리다이렉트."""
    if not _auth_enabled:
        return RedirectResponse("/admin", status_code=303)

    user = db.scalar(select(User).where(User.username == username))
    if not user or not verify_password(password, user.hashed_password or ""):
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "error": "아이디 또는 비밀번호가 올바르지 않습니다.",
                "google_enabled": bool(settings.auth.google_client_id),
                "github_enabled": bool(settings.auth.github_client_id),
            },
            status_code=400,
        )

    token = create_access_token(
        {"sub": str(user.id)},
        expires_delta=timedelta(minutes=settings.auth.token_expire_minutes),
    )
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        "mcper_token",
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.auth.token_expire_minutes * 60,
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie("mcper_token")
    return response


@router.get("/me")
def me(
    username: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        return {"username": username, "email": None, "is_admin": True}
    return {"username": user.username, "email": user.email, "is_admin": user.is_admin}


# ── API 키 관리 (어드민 전용) ──────────────────────────────────────

@router.post("/api-keys")
def create_api_key(
    name: str = Form(...),
    username: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """새 API 키 발급. 원본 키는 이 응답에서 한 번만 노출."""
    raw_key = secrets.token_urlsafe(32)
    key_hash = hash_api_key(raw_key)
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    db.add(ApiKey(user_id=user.id, key_hash=key_hash, name=name))
    db.commit()
    return {"key": raw_key, "name": name, "note": "이 키는 한 번만 표시됩니다. 안전하게 보관하세요."}


@router.get("/api-keys")
def list_api_keys(
    username: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        return []
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id)).all()
    return [
        {"id": k.id, "name": k.name, "created_at": k.created_at, "last_used_at": k.last_used_at}
        for k in keys
    ]


@router.delete("/api-keys/{key_id}")
def revoke_api_key(
    key_id: int,
    username: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    db.execute(delete(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id))
    db.commit()
    return {"ok": True}
