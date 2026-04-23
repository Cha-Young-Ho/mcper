"""FastAPI Depends: get_current_user_optional, require_admin_user."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials, HTTPBasic
from jose import ExpiredSignatureError, JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth.service import decode_token
from app.db.auth_models import ApiKey, User
from app.db.database import get_db


def _raise_redirect(url: str) -> None:
    """Dependency에서 리다이렉트를 트리거. Starlette HTTPException + 303 + Location 헤더."""
    raise StarletteHTTPException(
        status_code=303,
        headers={"Location": url},
    )

logger = logging.getLogger(__name__)

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

    # JWT 검증 시도 (만료 시 401 반환)
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if user_id is not None:
            user = db.get(User, int(user_id))
            if user and user.is_active:
                return user
    except ExpiredSignatureError:
        logger.info("Expired JWT token used")
        return None
    except JWTError:
        pass

    # API 키 검증 (Bearer 헤더만)
    if credentials and credentials.credentials:
        key_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        api_key = db.scalar(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        if api_key:
            # API 키 만료 검증
            if api_key.expires_at is not None:
                now = datetime.now(timezone.utc)
                if api_key.expires_at < now:
                    logger.warning(f"Expired API key used: {api_key.id}")
                    return None

            # 마지막 사용 시간 업데이트
            api_key.last_used_at = datetime.now(timezone.utc)
            db.add(api_key)
            db.commit()

            user = db.get(User, api_key.user_id)
            if user and user.is_active:
                return user

    return None


async def require_admin_user(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    basic_credentials: HTTPBasicCredentials | None = Depends(basic_scheme),
) -> str:
    """
    AUTH_ENABLED=false → 기존 HTTP Basic 방식.
    AUTH_ENABLED=true  → JWT 쿠키/Bearer, is_admin=True 필요.
    만료된 토큰 → 401 "Token expired" 응답.
    """
    if not _auth_enabled:
        return _check_basic_auth(basic_credentials)

    if user is None:
        # 토큰이 있지만 만료된 경우 명시적 메시지
        token = request.cookies.get("mcper_token")
        if not token and request.headers.get("authorization"):
            token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()

        if token:
            try:
                decode_token(token)
            except ExpiredSignatureError:
                accept = request.headers.get("accept", "")
                if "text/html" in accept:
                    _raise_redirect("/auth/login")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token expired",
                )
            except JWTError:
                pass

        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            _raise_redirect("/auth/login")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    # 패스워드 미변경 체크 (초기 관리자 강제 변경)
    if user.password_changed_at is None:
        # 이미 /auth/change-password-forced 페이지인지 확인
        if not request.url.path.startswith("/auth/change-password-forced"):
            _raise_redirect("/auth/change-password-forced")

    return user.username
