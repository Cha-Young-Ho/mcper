"""Google / GitHub OAuth 콜백 (opt-in).

AUTH_GOOGLE_CLIENT_ID / AUTH_GITHUB_CLIENT_ID 환경변수가 설정된 경우에만 라우터 등록.
로컬 테스트 시 httpx로 OAuth 토큰 교환을 직접 구현 (authlib 없이도 동작).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.service import create_access_token
from app.config import settings
from app.db.auth_models import User
from app.db.database import get_db

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/auth/oauth", tags=["oauth"])


# ── Google OAuth ───────────────────────────────────────────────

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


@router.get("/google")
def google_login(request: Request):
    """Google OAuth 로그인 시작."""
    client_id = settings.auth.google_client_id
    if not client_id:
        raise HTTPException(status_code=404, detail="Google OAuth not configured")
    redirect_uri = str(request.url_for("google_callback"))
    url = (
        f"{GOOGLE_AUTH_URL}"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=openid+email+profile"
    )
    return RedirectResponse(url)


@router.get("/google/callback", name="google_callback")
async def google_callback(code: str, db: Session = Depends(get_db)):
    """
    Google OAuth 콜백.
    1. code → access_token (Google API)
    2. access_token → userinfo (email, sub)
    3. DB에 없으면 User 생성 (oauth_provider="google", hashed_password=None)
    4. JWT 발급 → 쿠키 설정 → /admin 리다이렉트
    """
    client_id = settings.auth.google_client_id
    client_secret = settings.auth.google_client_secret
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": os.environ.get(
                    "OAUTH_REDIRECT_BASE", "http://localhost:8001"
                )
                + "/auth/oauth/google/callback",
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            logger.error("Google token exchange failed: %s", token_resp.text)
            raise HTTPException(status_code=400, detail="OAuth token exchange failed")

        access_token = token_resp.json().get("access_token")
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo = userinfo_resp.json()

    sub = userinfo.get("sub")
    email = userinfo.get("email")
    name = userinfo.get("name") or (email.split("@")[0] if email else f"google_{sub}")

    user = db.scalar(
        select(User).where(User.oauth_provider == "google", User.oauth_sub == sub)
    )
    if user is None:
        user = User(
            username=name,
            email=email,
            oauth_provider="google",
            oauth_sub=sub,
            is_admin=False,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    jwt_token = create_access_token({"sub": str(user.id)})
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie("mcper_token", jwt_token, httponly=True, samesite="lax")
    return response


# ── GitHub OAuth ───────────────────────────────────────────────

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USERINFO_URL = "https://api.github.com/user"


@router.get("/github")
def github_login(request: Request):
    """GitHub OAuth 로그인 시작."""
    client_id = settings.auth.github_client_id
    if not client_id:
        raise HTTPException(status_code=404, detail="GitHub OAuth not configured")
    redirect_uri = str(request.url_for("github_callback"))
    url = (
        f"{GITHUB_AUTH_URL}"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=user:email"
    )
    return RedirectResponse(url)


@router.get("/github/callback", name="github_callback")
async def github_callback(code: str, db: Session = Depends(get_db)):
    """
    GitHub OAuth 콜백.
    """
    client_id = settings.auth.github_client_id
    client_secret = settings.auth.github_client_secret
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            logger.error("GitHub token exchange failed: %s", token_resp.text)
            raise HTTPException(status_code=400, detail="OAuth token exchange failed")

        access_token = token_resp.json().get("access_token")
        userinfo_resp = await client.get(
            GITHUB_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo = userinfo_resp.json()

    sub = str(userinfo.get("id"))
    login = userinfo.get("login") or f"github_{sub}"
    email = userinfo.get("email")

    user = db.scalar(
        select(User).where(User.oauth_provider == "github", User.oauth_sub == sub)
    )
    if user is None:
        user = User(
            username=login,
            email=email,
            oauth_provider="github",
            oauth_sub=sub,
            is_admin=False,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    jwt_token = create_access_token({"sub": str(user.id)})
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie("mcper_token", jwt_token, httponly=True, samesite="lax")
    return response
