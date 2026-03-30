"""FastAPI Depends: get_current_user_optional, require_admin_user."""

from __future__ import annotations

import hashlib
import os
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials, HTTPBasic
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.service import decode_token
from app.db.auth_models import ApiKey, User
from app.db.database import get_db

_auth_enabled = os.environ.get("MCPER_AUTH_ENABLED", "false").lower() in ("1", "true", "yes")

bearer_scheme = HTTPBearer(auto_error=False)
basic_scheme = HTTPBasic(auto_error=False)


def _admin_creds() -> tuple[str, str]:
    user = os.environ.get("ADMIN_USER", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "changeme")
    return user, password


def _check_basic_auth(credentials: HTTPBasicCredentials | None) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Basic"},
        )
    expected_user, expected_password = _admin_creds()
    ok_user = secrets.compare_digest(credentials.username, expected_user)
    ok_pass = secrets.compare_digest(credentials.password, expected_password)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """
    MCPER_AUTH_ENABLED=false → 항상 None 반환 (인증 생략).
    MCPER_AUTH_ENABLED=true  → JWT 쿠키 → Bearer 헤더 → API 키 순으로 검증.
    """
    if not _auth_enabled:
        return None

    # 1) JWT 쿠키
    token = request.cookies.get("mcper_token")

    # 2) Bearer 헤더
    if not token and credentials:
        token = credentials.credentials

    if not token:
        return None

    # JWT 검증 시도
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if user_id is not None:
            return db.get(User, int(user_id))
    except JWTError:
        pass

    # API 키 검증 (Bearer 헤더만)
    if credentials and credentials.credentials:
        key_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        api_key = db.scalar(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        if api_key:
            return db.get(User, api_key.user_id)

    return None


async def require_admin_user(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    basic_credentials: HTTPBasicCredentials | None = Depends(basic_scheme),
) -> str:
    """
    AUTH_ENABLED=false → 기존 HTTP Basic 방식.
    AUTH_ENABLED=true  → JWT 쿠키/Bearer, is_admin=True 필요.
    """
    if not _auth_enabled:
        return _check_basic_auth(basic_credentials)

    if user is None:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/auth/login", status_code=303)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return user.username
