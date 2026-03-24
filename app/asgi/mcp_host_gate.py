"""MCP 마운트 앞단: 매 요청 DB에서 허용 Host 조회 후 통과/421/403."""

from __future__ import annotations

import asyncio
import logging
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


def _header(scope: dict[str, Any], name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k.lower() == name.lower():
            return v.decode("latin-1")
    return None


def _sync_validate(
    app_settings: AppSettings,
    host: str | None,
    origin: str | None,
    method: str,
    content_type: str | None,
) -> tuple[bool, int, bytes]:
    """(통과 여부, 실패 시 status, body)."""
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

        ok, status, body = await asyncio.to_thread(
            _sync_validate,
            self.app_settings,
            host,
            origin,
            method,
            ct,
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
