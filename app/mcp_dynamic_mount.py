"""MCP 마운트: 게이트(DB Host/Origin) + FastMCP streamable_http ASGI."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import PlainTextResponse

from app.asgi.mcp_host_gate import McpHostGateASGI
from app.config import AppSettings
from app.services.mcp_transport_config import build_streamable_http_app

ASGIApp = Callable[[dict[str, Any], Callable, Callable], Awaitable[None]]


class McpDynamicASGI:
    def __init__(self) -> None:
        self.inner: ASGIApp | None = None

    def init(self, app_settings: AppSettings) -> None:
        """기동 시 한 번: 내부 MCP ASGI + 매 요청 DB 검사 게이트."""
        mcp_asgi = build_streamable_http_app(app_settings)
        self.inner = McpHostGateASGI(mcp_asgi, app_settings)

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        inner = self.inner
        if inner is None:
            res = PlainTextResponse("MCP transport not initialized", status_code=503)
            await res(scope, receive, send)
            return
        await inner(scope, receive, send)


mcp_dynamic_asgi = McpDynamicASGI()
