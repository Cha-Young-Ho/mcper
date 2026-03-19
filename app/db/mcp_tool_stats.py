"""MCP tool invocation counters (for admin dashboard)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class McpToolCallStat(Base):
    """One row per MCP tool name; call_count incremented on each tool execution."""

    __tablename__ = "mcp_tool_call_stats"

    tool_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    call_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
