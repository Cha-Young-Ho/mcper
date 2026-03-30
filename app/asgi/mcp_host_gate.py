"""MCP 마운트 앞단: 매 요청 DB에서 허용 Host 조회 후 통과/421/403.

인증 검사 순서 (MCPER_AUTH_ENABLED=true 시):
  1. Authorization: Bearer <JWT or API 키> 헤더 검증
  2. 실패 시 401 반환
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Callable
from typing import Any

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


def _mcp_transport_gate_bypassed() -> bool:
    """Host/Origin 앱 레벨 검사 생략 — 네트워크는 SG·ALB 등에서 제어할 때 ``MCP_BYPASS_TRANSPORT_GATE=1``."""
    v = (os.environ.get("MCP_BYPASS_TRANSPORT_GATE") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _header(scope: dict[str, Any], name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k.lower() == name.lower():
            return v.decode("latin-1")
    return None


def _check_bearer_auth(auth_header: str | None) -> tuple[bool, int, bytes]:
    """MCPER_AUTH_ENABLED=true 시 Bearer 토큰(JWT or API 키) 검증."""
    if not _auth_enabled:
        return True, 0, b""
    if not auth_header or not auth_header.startswith("Bearer "):
        return False, 401, b"Authorization required"

    token_or_key = auth_header[7:]

    # JWT 검증 시도
    try:
        from app.auth.service import decode_token
        decode_token(token_or_key)
        return True, 0, b""
    except Exception:
        pass

    # API 키 검증 시도
    try:
        from sqlalchemy import select
        from app.db.auth_models import ApiKey

        key_hash = hashlib.sha256(token_or_key.encode()).hexdigest()
        db = SessionLocal()
        try:
            row = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
            if row is not None:
                return True, 0, b""
        finally:
            db.close()
    except Exception as exc:
        logger.exception("MCP auth check failed: %s", exc)

    return False, 401, b"Invalid token"


def _sync_validate(
    app_settings: AppSettings,
    host: str | None,
    origin: str | None,
    method: str,
    content_type: str | None,
    auth_header: str | None = None,
) -> tuple[bool, int, bytes]:
    """(통과 여부, 실패 시 status, body)."""
    # Auth 검사 (MCPER_AUTH_ENABLED=true 시)
    ok, status, body = _check_bearer_auth(auth_header)
    if not ok:
        return ok, status, body

    if _mcp_transport_gate_bypassed():
        if method.upper() == "POST" and not content_type_ok_for_mcp_post(content_type):
            return False, 400, b"Invalid Content-Type header"
        return True, 0, b""

    db = SessionLocal()
    try:
        allowed_hosts = effective_allowed_hosts(db, app_settings.server.port)
    finally:
        db.close()

    origins = list(dict.fromkeys(app_settings.security.allowed_origins))

    if not host_header_allowed(host, allowed_hosts):
        logger.warning("MCP gate: invalid Host %r (allowed=%s)", host, allowed_hosts)
        return False, 421, b"Invalid Host header"

    if not origin_header_allowed(origin, origins):
        logger.warning("MCP gate: invalid Origin %r (allowed=%s)", origin, origins)
        return False, 403, b"Invalid Origin header"

    if method.upper() == "POST" and not content_type_ok_for_mcp_post(content_type):
        return False, 400, b"Invalid Content-Type header"

    return True, 0, b""


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

        ok, status, body = await asyncio.to_thread(
            _sync_validate,
            self.app_settings,
            host,
            origin,
            method,
            ct,
            auth_header,
        )
        if not ok:
            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        await self.inner(scope, receive, send)
