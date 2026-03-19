"""MCP tools: spec upload and search."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy import cast, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.types import String

from app.db.database import SessionLocal
from app.db.models import Spec
from app.services.mcp_tool_stats import record_mcp_tool_call


def _normalize_related_files(related_files: Any) -> list[str]:
    """Accept list, JSON string, or comma-separated paths from MCP clients."""
    if related_files is None:
        return []
    if isinstance(related_files, list):
        return [str(x) for x in related_files]
    if isinstance(related_files, str):
        s = related_files.strip()
        if not s:
            return []
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [str(x) for x in data]
        except json.JSONDecodeError:
            pass
        return [p.strip() for p in s.split(",") if p.strip()]
    return [str(related_files)]


def _ilike_pattern(term: str) -> str:
    """Build ILIKE pattern with % / _ escaped (PostgreSQL backslash escape)."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def upload_spec_to_db_impl(
    content: str,
    app_target: str,
    base_branch: str,
    related_files: Any,
    title: str | None = None,
) -> str:
    """Insert one spec row. Returns JSON message with new id."""
    record_mcp_tool_call("upload_spec_to_db")
    paths = _normalize_related_files(related_files)
    t = (title or "").strip() or None
    row = Spec(
        title=t,
        content=content,
        app_target=app_target,
        base_branch=base_branch,
        related_files=paths,
    )
    db: Session = SessionLocal()
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return json.dumps(
            {"ok": True, "id": row.id, "message": "inserted"},
            ensure_ascii=False,
        )
    except Exception as exc:
        db.rollback()
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


def search_spec_and_code_impl(query: str, app_target: str) -> str:
    """Search by app and text in content or related_files paths."""
    record_mcp_tool_call("search_spec_and_code")
    db: Session = SessionLocal()
    try:
        pattern = _ilike_pattern(query)
        json_text = cast(Spec.related_files, String)
        stmt = (
            select(Spec)
            .where(Spec.app_target == app_target)
            .where(
                or_(
                    Spec.content.ilike(pattern, escape="\\"),
                    json_text.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Spec.id.desc())
            .limit(50)
        )
        rows = list(db.scalars(stmt).all())
        out = [
            {
                "id": r.id,
                "title": r.title,
                "content": r.content,
                "related_files": r.related_files,
                "base_branch": r.base_branch,
            }
            for r in rows
        ]
        return json.dumps({"ok": True, "count": len(out), "results": out}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


def register_spec_tools(mcp: FastMCP) -> None:
    """Register upload / search tools on a FastMCP instance."""

    @mcp.tool()
    def upload_spec_to_db(
        content: str,
        app_target: str,
        base_branch: str,
        related_files: list[str] | str | None = None,
        title: str | None = None,
    ) -> str:
        """Insert a planning spec into Postgres (specs table). related_files can be a list or JSON array string. title은 어드민 목록용(선택)."""
        return upload_spec_to_db_impl(
            content=content,
            app_target=app_target,
            base_branch=base_branch,
            related_files=related_files,
            title=title,
        )

    @mcp.tool()
    def search_spec_and_code(query: str, app_target: str) -> str:
        """Search specs for an app: matches query in content or related file paths. Returns JSON with results."""
        return search_spec_and_code_impl(query=query, app_target=app_target)
