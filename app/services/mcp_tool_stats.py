"""Record MCP tool invocations for the admin dashboard."""

from __future__ import annotations

import logging

from app.db.database import SessionLocal
from app.db.mcp_tool_stats import McpToolCallStat

logger = logging.getLogger(__name__)


def record_mcp_tool_call(tool_name: str) -> None:
    """Best-effort increment; never raises to callers."""
    try:
        db = SessionLocal()
        try:
            row = db.get(McpToolCallStat, tool_name)
            if row is None:
                db.add(McpToolCallStat(tool_name=tool_name, call_count=1))
            else:
                row.call_count = int(row.call_count) + 1
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        logger.exception("mcp_tool_stats: failed to record %s", tool_name)
