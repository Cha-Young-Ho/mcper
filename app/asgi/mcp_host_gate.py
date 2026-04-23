"""MCP 마운트 앞단: 매 요청 DB에서 허용 Host 조회 후 통과/421/403.

인증 검사 순서 (MCPER_AUTH_ENABLED=true 시):
  1. Authorization: Bearer <JWT or API 키> 헤더 검증
  2. 실패 시 401 + login_url JSON 반환
  3. 성공 시 CurrentUser를 contextvars에 저장 → MCP 도구에서 권한 체크용
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Callable
from typing import Any

from app.auth.context import CurrentUser, current_user_var
from app.config import AppSettings
from app.db.database import SessionLocal
from app.services.mcp_host_validate import (
    content_type_ok_for_mcp_post,
    host_header_allowed,
    origin_header_allowed,
)
from app.services.mcp_transport_config import effective_allowed_hosts

logger = logging.getLogger(__name__)

ASGIApp = Callable[[dict[str, Any], Callable, Callable], Any]

_auth_enabled = os.environ.get("MCPER_AUTH_ENABLED", "false").lower() in ("1", "true", "yes")

# SDK OAuth가 활성이면 Bearer 인증은 SDK가 처리 → 게이트는 Host/Origin만 검사
_sdk_auth_active = _auth_enabled  # SDK auth = auth enabled (mcp_app.py에서 동일 조건)


def _mcp_transport_gate_bypassed() -> bool:
    """Host/Origin 앱 레벨 검사 생략 — 네트워크는 SG·ALB 등에서 제어할 때 ``MCP_BYPASS_TRANSPORT_GATE=1``."""
    v = (os.environ.get("MCP_BYPASS_TRANSPORT_GATE") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _header(scope: dict[str, Any], name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k.lower() == name.lower():
            return v.decode("latin-1")
    return None


def _resolve_user_from_jwt(token: str) -> CurrentUser | None:
    """JWT payload에서 user_id를 추출하고 DB에서 User 조회 → CurrentUser."""
    try:
        from app.auth.service import decode_token
        payload = decode_token(token)
        user_id_str = payload.get("sub")
        if not user_id_str:
            return None
        from sqlalchemy import select
        from app.db.auth_models import User
        db = SessionLocal()
        try:
            user = db.scalar(select(User).where(User.id == int(user_id_str)))
            if user and user.is_active:
                return CurrentUser(
                    user_id=user.id,
                    username=user.username,
                    is_admin=user.is_admin,
                )
        finally:
            db.close()
    except Exception:
        pass
    return None


def _resolve_user_from_api_key(token: str) -> CurrentUser | None:
    """API 키 hash로 ApiKey 조회 → User 조회 → CurrentUser."""
    try:
        from sqlalchemy import select
        from app.db.auth_models import ApiKey, User
        from datetime import datetime, timezone

        key_hash = hashlib.sha256(token.encode()).hexdigest()
        db = SessionLocal()
        try:
            api_key = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
            if api_key is None:
                return None
            # 만료 체크
            if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
                return None
            # last_used_at 업데이트
            api_key.last_used_at = datetime.now(timezone.utc)
            user = db.scalar(select(User).where(User.id == api_key.user_id))
            if user and user.is_active:
                db.commit()
                return CurrentUser(
                    user_id=user.id,
                    username=user.username,
                    is_admin=user.is_admin,
                )
        finally:
            db.close()
    except Exception as exc:
        logger.exception("MCP API key auth failed: %s", exc)
    return None


def _check_bearer_auth(auth_header: str | None) -> tuple[bool, int, bytes, CurrentUser | None]:
    """MCPER_AUTH_ENABLED=true 시 Bearer 토큰(JWT or API 키) 검증 + 유저 추출."""
    if not _auth_enabled:
        return True, 0, b"", None
    if not auth_header or not auth_header.startswith("Bearer "):
        return False, 401, b"Authorization required", None

    token_or_key = auth_header[7:]

    # JWT 검증 시도
    user = _resolve_user_from_jwt(token_or_key)
    if user is not None:
        return True, 0, b"", user

    # API 키 검증 시도
    user = _resolve_user_from_api_key(token_or_key)
    if user is not None:
        return True, 0, b"", user

    return False, 401, b"Invalid token", None


# SDK OAuth 엔드포인트 경로 (content-type 검사 제외, 인증 검사 제외)
_OAUTH_PATHS = {"/authorize", "/token", "/register", "/revoke",
                "/.well-known/oauth-authorization-server",
                "/.well-known/oauth-protected-resource"}


def _is_oauth_endpoint(path: str | None) -> bool:
    """SDK가 처리하는 OAuth 엔드포인트인지 판별."""
    if not path:
        return False
    return path.rstrip("/") in _OAUTH_PATHS or path.startswith("/.well-known/")


def _sync_validate(
    app_settings: AppSettings,
    host: str | None,
    origin: str | None,
    method: str,
    content_type: str | None,
    auth_header: str | None = None,
    path: str | None = None,
) -> tuple[bool, int, bytes, CurrentUser | None]:
    """(통과 여부, 실패 시 status, body, 인증된 유저 or None)."""
    is_oauth = _sdk_auth_active and _is_oauth_endpoint(path)

    # SDK OAuth가 활성이면 Bearer 인증은 SDK 미들웨어가 처리 → 게이트는 건너뜀
    user: CurrentUser | None = None
    if _sdk_auth_active:
        # SDK가 인증 처리. 게이트에서는 Host/Origin만 검사.
        # Bearer 토큰이 있으면 CurrentUser 추출만 시도 (실패해도 통과 — SDK가 거부)
        if auth_header and auth_header.startswith("Bearer "):
            token_or_key = auth_header[7:]
            user = _resolve_user_from_jwt(token_or_key) or _resolve_user_from_api_key(token_or_key)
    else:
        # 기존: 게이트가 직접 Bearer 인증 검사
        ok, status, body, user = _check_bearer_auth(auth_header)
        if not ok:
            return ok, status, body, None

    if _mcp_transport_gate_bypassed():
        # OAuth 엔드포인트는 content-type 검사 불필요 (form-urlencoded 등 사용)
        if not is_oauth and method.upper() == "POST" and not content_type_ok_for_mcp_post(content_type):
            return False, 400, b"Invalid Content-Type header", None
        return True, 0, b"", user

    db = SessionLocal()
    try:
        allowed_hosts = effective_allowed_hosts(db, app_settings.server.port)
    finally:
        db.close()

    origins = list(dict.fromkeys(app_settings.security.allowed_origins))

    if not host_header_allowed(host, allowed_hosts):
        logger.warning("MCP gate: invalid Host %r (allowed=%s)", host, allowed_hosts)
        return False, 421, b"Invalid Host header", None

    if not origin_header_allowed(origin, origins):
        logger.warning("MCP gate: invalid Origin %r (allowed=%s)", origin, origins)
        return False, 403, b"Invalid Origin header", None

    if not is_oauth and method.upper() == "POST" and not content_type_ok_for_mcp_post(content_type):
        return False, 400, b"Invalid Content-Type header", None

    return True, 0, b"", user


def _build_login_url(scope: dict) -> str:
    """요청의 Host 헤더로부터 브라우저 로그인 URL 생성. 로그인 후 API 키 페이지로 이동."""
    host = _header(scope, b"host") or "localhost:8001"
    scheme = "https" if "443" in host else "http"
    return f"{scheme}://{host}/auth/login?next=/admin/api-keys"


class McpHostGateASGI:
    def __init__(self, inner: ASGIApp, app_settings: AppSettings) -> None:
        self.inner = inner
        self.app_settings = app_settings

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return

        host = _header(scope, b"host")
        origin = _header(scope, b"origin")
        method = scope.get("method") or "GET"
        ct = _header(scope, b"content-type")
        auth_header = _header(scope, b"authorization")
        # Starlette Mount sets root_path to the mount prefix; strip it for route-relative path
        raw_path = scope.get("path") or "/"
        root_path = scope.get("root_path") or ""
        path = raw_path[len(root_path):] if root_path and raw_path.startswith(root_path) else raw_path
        path = path or "/"

        ok, status_code, body, user = await asyncio.to_thread(
            _sync_validate,
            self.app_settings,
            host,
            origin,
            method,
            ct,
            auth_header,
            path,
        )
        if not ok:
            # 401: 인증 실패 → login_url을 포함한 JSON 응답
            if status_code == 401:
                login_url = _build_login_url(scope)
                error_body = json.dumps({
                    "error": "authentication_required",
                    "message": body.decode("utf-8"),
                    "login_url": login_url,
                }).encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json; charset=utf-8"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": error_body})
            else:
                await send(
                    {
                        "type": "http.response.start",
                        "status": status_code,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                    }
                )
                await send({"type": "http.response.body", "body": body})
            return

        # Set user context for MCP tools (reset after request completes)
        token = current_user_var.set(user)
        try:
            await self.inner(scope, receive, send)
        finally:
            current_user_var.reset(token)
