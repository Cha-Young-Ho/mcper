"""MCP ``streamable_http_app`` 빌드. Host/Origin 은 ``mcp_host_gate`` 에서 DB 매 요청 검사."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.db.mcp_security import McpAllowedHost
from app.mcp_app import mcp
from mcp.server.transport_security import TransportSecuritySettings

logger = logging.getLogger(__name__)


def _default_hosts(listen_port: int) -> list[str]:
    p = int(listen_port)
    return [f"127.0.0.1:{p}", f"localhost:{p}"]


def list_allowed_hosts_from_db(session: Session) -> list[str]:
    rows = session.scalars(
        select(McpAllowedHost.host_entry).order_by(McpAllowedHost.id)
    ).all()
    return [str(h).strip() for h in rows if str(h).strip()]


def effective_allowed_hosts(session: Session, listen_port: int) -> list[str]:
    hosts = list_allowed_hosts_from_db(session)
    if hosts:
        return list(dict.fromkeys(hosts))
    return _default_hosts(listen_port)


def build_streamable_http_app(app_settings: AppSettings) -> Callable:
    """SDK 쪽 DNS 리바인딩 검사는 끄고, Host/Origin 은 ``McpHostGateASGI`` 가 DB로 검사한다."""
    ts = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
        allowed_hosts=[],
        allowed_origins=[],
    )

    stream_sig = inspect.signature(type(mcp).streamable_http_app)
    params = set(stream_sig.parameters) - {"self"}

    logger.info(
        "MCP: SDK transport_security 는 비활성, Host/Origin 은 게이트에서 DB 조회",
    )

    if "transport_security" in params:
        kwargs: dict = {}
        kwargs["transport_security"] = ts
        if "host" in params and app_settings.server.host == "0.0.0.0":
            kwargs["host"] = "0.0.0.0"
        call_kw = {k: v for k, v in kwargs.items() if k in params}
        return mcp.streamable_http_app(**call_kw)

    if not hasattr(mcp.settings, "transport_security"):
        logger.warning(
            "mcp FastMCP.settings 에 transport_security 가 없어. 패키지를 올려줘.",
        )
        return mcp.streamable_http_app()

    _apply_transport_security_to_mcp(ts)
    return mcp.streamable_http_app()


def _apply_transport_security_to_mcp(ts: TransportSecuritySettings) -> None:
    s = mcp.settings
    if hasattr(s, "model_copy"):
        mcp.settings = s.model_copy(update={"transport_security": ts})
    else:
        mcp.settings.transport_security = ts
    sm = getattr(mcp, "_session_manager", None)
    if sm is not None:
        sm.security_settings = ts
