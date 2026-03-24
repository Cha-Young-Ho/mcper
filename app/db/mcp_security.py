"""MCP Streamable HTTP TransportSecurity allowlist (Host 헤더 등)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class McpAllowedHost(Base):
    """클라이언트가 보내는 ``Host`` 값과 일치해야 함 (예: ``3.4.5.6:8001``)."""

    __tablename__ = "mcp_allowed_hosts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host_entry: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
