"""MCP tools: document upload and search."""

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


def upload_document_impl(
    content: str,
    app_target: str,
    base_branch: str,
    related_files: Any,
    title: str | None = None,
) -> str:
    """Insert one document row. Returns JSON message with new id."""
    record_mcp_tool_call("upload_document")
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


def search_documents_impl(query: str, app_target: str) -> str:
    """Hybrid vector + FTS (RRF) when document chunks exist; else legacy ILIKE on documents."""
    record_mcp_tool_call("search_documents")
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


def register_document_tools(mcp: FastMCP) -> None:
    """Register upload / search tools on a FastMCP instance."""

    @mcp.tool()
    def upload_document(
        content: str,
        app_target: str,
        base_branch: str,
        related_files: list[str] | str | None = None,
        title: str | None = None,
    ) -> str:
        """Insert document with optional chunking and embedding indexing. related_files can be a list or JSON array string."""
        return upload_document_impl(
            content=content,
            app_target=app_target,
            base_branch=base_branch,
            related_files=related_files,
            title=title,
        )

    @mcp.tool()
    def search_documents(query: str, app_target: str) -> str:
        """Search documents by app target. Uses vector+FTS (RRF) if indexed chunks exist, otherwise ILIKE fallback. Returns JSON."""
        return search_documents_impl(query=query, app_target=app_target)

    @mcp.tool()
    def upload_documents_batch(documents: list[dict]) -> dict:
        """
        Upload multiple documents in a single batch.

        Each document dict should contain:
          - title (str): Document title
          - content (str): Document content text
          - app_target (str, optional): App identifier
          - base_branch (str, optional): Base branch name (default: main)
          - related_files (list[str] | str | None, optional): Related file paths

        Returns counts of succeeded and failed uploads, plus error list.
        """
        succeeded = 0
        failed = 0
        errors: list[dict] = []
        for doc in documents:
            content = doc.get("content", "")
            app_target = doc.get("app_target", "")
            base_branch = doc.get("base_branch", "main") or "main"
            related_files = doc.get("related_files")
            title = doc.get("title")
            result_str = upload_document_impl(
                content=content,
                app_target=app_target,
                base_branch=base_branch,
                related_files=related_files,
                title=title,
            )
            result = json.loads(result_str)
            if result.get("ok"):
                succeeded += 1
            else:
                failed += 1
                errors.append({"title": title, "error": result.get("error", "unknown")})
        return {"succeeded": succeeded, "failed": failed, "errors": errors}


# Deprecated aliases — kept for backward compatibility
upload_spec_to_db = upload_document
search_spec_and_code = search_documents
register_spec_tools = register_document_tools
