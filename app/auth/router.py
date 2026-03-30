"""Auth 라우터: /auth/login, /auth/logout, /auth/me, /auth/api-keys."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_optional, require_admin_user
from app.auth.service import create_access_token, decode_token, hash_api_key, hash_password, validate_password, verify_password
from app.config import settings
from app.db.auth_models import ApiKey, User
from app.db.database import get_db

logger = logging.getLogger(__name__)

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
    if not user or not user.is_active or not verify_password(password, user.hashed_password or ""):
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

    # Access 토큰 (15분)
    access_token = create_access_token(
        {"sub": str(user.id), "type": "access"},
        expires_delta=timedelta(minutes=15),
    )
    # Refresh 토큰 (7일)
    refresh_token = create_access_token(
        {"sub": str(user.id), "type": "refresh"},
        expires_delta=timedelta(days=7),
    )

    # 마지막 로그인 시간 업데이트
    user.last_login = datetime.now(timezone.utc)
    db.add(user)
    db.commit()

    response = RedirectResponse("/admin", status_code=303)
    # Access 토큰 (httponly)
    response.set_cookie(
        "mcper_token",
        access_token,
        httponly=True,
        samesite="lax",
        max_age=900,  # 15분
    )
    # Refresh 토큰 (JS에서 필요하면 접근 가능)
    response.set_cookie(
        "mcper_refresh_token",
        refresh_token,
        httponly=False,
        samesite="lax",
        max_age=604800,  # 7일
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


# ── 강제 패스워드 변경 (초기 관리자) ────────────────────────────────


@router.get("/change-password-forced")
async def change_password_forced_form(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    """기본 패스워드 변경 강제 폼 (password_changed_at is NULL일 때만)."""
    if not _auth_enabled or user is None:
        return RedirectResponse(url="/auth/login", status_code=303)

    if user.password_changed_at is not None:
        # 이미 변경함 → 대시보드로
        return RedirectResponse(url="/admin", status_code=303)

    # is_admin=True 확인
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    return templates.TemplateResponse(
        "auth/change_password_forced.html",
        {"request": request, "username": user.username}
    )


@router.post("/change-password-forced")
async def change_password_forced_submit(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """패스워드 변경 제출."""
    if not _auth_enabled or user is None:
        return RedirectResponse(url="/auth/login", status_code=303)

    if user.password_changed_at is not None:
        return RedirectResponse(url="/admin", status_code=303)

    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    form = await request.form()
    password = form.get("password", "").strip()
    password_confirm = form.get("password_confirm", "").strip()

    # 검증: 패스워드 정책 (12자 이상, 특수문자 포함)
    if not password:
        return templates.TemplateResponse(
            "auth/change_password_forced.html",
            {
                "request": request,
                "username": user.username,
                "error": "Password is required",
            },
            status_code=400,
        )

    pw_error = validate_password(password)
    if pw_error:
        return templates.TemplateResponse(
            "auth/change_password_forced.html",
            {
                "request": request,
                "username": user.username,
                "error": pw_error,
            },
            status_code=400,
        )

    if password != password_confirm:
        return templates.TemplateResponse(
            "auth/change_password_forced.html",
            {
                "request": request,
                "username": user.username,
                "error": "Passwords do not match",
            },
            status_code=400,
        )

    # 기본 패스워드와 동일하지 않은지 확인
    default_password = os.environ.get("ADMIN_PASSWORD", "changeme")
    if secrets.compare_digest(password, default_password):
        return templates.TemplateResponse(
            "auth/change_password_forced.html",
            {
                "request": request,
                "username": user.username,
                "error": "Password cannot be the default password",
            },
            status_code=400,
        )

    # 업데이트
    user.hashed_password = hash_password(password)
    user.password_changed_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()

    return RedirectResponse(url="/admin", status_code=303)


# ── 토큰 갱신 및 검증 ───────────────────────────────────────────────


@router.post("/token/refresh")
async def refresh_access_token(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Refresh 토큰으로 새 Access 토큰 발급.
    Request: { "refresh_token": "..." }
    Response: { "access_token": "...", "token_type": "bearer" }
    """
    if not _auth_enabled:
        raise HTTPException(status_code=400, detail="Auth not enabled")

    try:
        data = await request.json()
        refresh_token = data.get("refresh_token", "").strip()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not refresh_token:
        raise HTTPException(status_code=400, detail="refresh_token required")

    # 만료된 토큰도 payload 추출 가능하게
    try:
        payload = decode_token(refresh_token, allow_expired=True)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = payload.get("sub")
    token_type = payload.get("type")

    # refresh 토큰만 수락
    if token_type != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user = db.get(User, int(user_id)) if user_id else None
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # 새 access 토큰 발급 (짧은 수명)
    access_token = create_access_token(
        {"sub": str(user.id), "type": "access"},
        expires_delta=timedelta(minutes=15)
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/token/validate")
async def validate_token(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    """
    토큰 유효성 확인.
    Response: { "valid": true, "user_id": 1, "expires_at": "2026-03-31T12:00:00Z" }
    """
    if not _auth_enabled:
        raise HTTPException(status_code=400, detail="Auth not enabled")

    if user is None:
        raise HTTPException(status_code=401, detail="No valid token")

    # JWT 쿠키에서 exp 추출
    token = request.cookies.get("mcper_token")
    expires_at = None
    if token:
        try:
            payload = decode_token(token)
            if "exp" in payload:
                expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        except Exception:
            pass

    return {
        "valid": True,
        "user_id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
