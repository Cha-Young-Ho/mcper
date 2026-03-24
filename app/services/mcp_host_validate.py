"""MCP 앞단 Host / Origin 검사 (SDK TransportSecurityMiddleware 와 동일 규칙)."""

from __future__ import annotations


def host_header_allowed(host: str | None, allowed_hosts: list[str]) -> bool:
    if not host:
        return False
    if host in allowed_hosts:
        return True
    for allowed in allowed_hosts:
        if allowed.endswith(":*"):
            base = allowed[:-2]
            if host.startswith(base + ":"):
                return True
    return False


def origin_header_allowed(origin: str | None, allowed_origins: list[str]) -> bool:
    """Origin 이 없으면 통과. allowed_origins 가 비어 있으면 Origin 제한 없음."""
    if not origin:
        return True
    if not allowed_origins:
        return True
    if origin in allowed_origins:
        return True
    for allowed in allowed_origins:
        if allowed.endswith(":*"):
            base = allowed[:-2]
            if origin.startswith(base + ":"):
                return True
    return False


def content_type_ok_for_mcp_post(content_type: str | None) -> bool:
    """Streamable HTTP POST 는 application/json 기대 (SDK 와 동일)."""
    if not content_type:
        return False
    return content_type.lower().startswith("application/json")
