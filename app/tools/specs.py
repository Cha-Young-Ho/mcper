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
from app.services.celery_client import enqueue_index_spec
from app.services.mcp_tool_stats import record_mcp_tool_call
from app.services.search_hybrid import hybrid_spec_search


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
        queued = enqueue_index_spec(row.id)
        return json.dumps(
            {
                "ok": True,
                "id": row.id,
                "message": "inserted",
                "chunk_index_queued": queued,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        db.rollback()
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


def search_spec_and_code_impl(query: str, app_target: str) -> str:
    """Hybrid vector + FTS (RRF) when spec_chunks exist; else legacy ILIKE on specs."""
    record_mcp_tool_call("search_spec_and_code")
    db: Session = SessionLocal()
    try:
        chunks, mode = hybrid_spec_search(db, query=query, app_target=app_target, top_n=15)
        if mode == "hybrid_ok" and chunks:
            return json.dumps(
                {
                    "ok": True,
                    "search_mode": "hybrid_rrf",
                    "count": len(chunks),
                    "chunks": chunks,
                },
                ensure_ascii=False,
            )

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
        legacy = [
            {
                "id": r.id,
                "title": r.title,
                "content": r.content,
                "related_files": r.related_files,
                "base_branch": r.base_branch,
            }
            for r in rows
        ]
        if mode == "indexed_no_match":
            sm = "legacy_ilike_supplement"
        else:
            sm = "legacy_ilike"
        return json.dumps(
            {
                "ok": True,
                "search_mode": sm,
                "count": len(legacy),
                "results": legacy,
                "chunks": [],
                "hybrid_note": mode,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "error": str(exc),
                "action_required": "check DB, EMBEDDING_DIM vs LOCAL_EMBEDDING_MODEL, sentence-transformers",
            },
            ensure_ascii=False,
        )
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
        """specs INSERT 후 Celery가 있으면 청크·임베딩 인덱싱 큐(index_spec). related_files는 리스트 또는 JSON 배열 문자열."""
        return upload_spec_to_db_impl(
            content=content,
            app_target=app_target,
            base_branch=base_branch,
            related_files=related_files,
            title=title,
        )

    @mcp.tool()
    def search_spec_and_code(query: str, app_target: str) -> str:
        """앱 단위 검색. spec_chunks 인덱스가 있으면 벡터+FTS(RRF), 없으면 specs ILIKE. JSON."""
        return search_spec_and_code_impl(query=query, app_target=app_target)
