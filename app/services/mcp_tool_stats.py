"""Record MCP tool invocations for the admin dashboard."""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.database import SessionLocal
from app.db.mcp_tool_stats import McpToolCallStat

logger = logging.getLogger(__name__)


def record_mcp_tool_call(tool_name: str) -> None:
    """Best-effort increment; never raises to callers."""
    try:
        db = SessionLocal()
        try:
            stmt = (
                pg_insert(McpToolCallStat)
                .values(tool_name=tool_name, call_count=1)
                .on_conflict_do_update(
                    index_elements=["tool_name"],
                    set_={"call_count": McpToolCallStat.call_count + 1},
                )
            )
            db.execute(stmt)
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        logger.exception("mcp_tool_stats: failed to record %s", tool_name)
