"""Hybrid vector + FTS search for doc_chunks (mirrors search_skills.py pattern)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.db.rag_models import DocChunk
from app.services.embeddings import embed_query
from app.services.search_hybrid import reciprocal_rank_fusion

logger = logging.getLogger(__name__)


def doc_chunk_vector_ids(
    db: Session,
    *,
    query_embedding: list[float],
    doc_type: str | None = None,
    app_name: str | None = None,
    pattern: str | None = None,
    limit: int = 40,
) -> list[int]:
    stmt = (
        select(DocChunk.id)
        .where(DocChunk.chunk_type != "parent")
        .where(DocChunk.embedding.isnot(None))
    )
    if doc_type:
        stmt = stmt.where(DocChunk.doc_type == doc_type)
    if app_name:
        stmt = stmt.where(DocChunk.app_name == app_name)
    if pattern is not None:
        stmt = stmt.where(DocChunk.pattern == pattern)
    stmt = stmt.order_by(DocChunk.embedding.cosine_distance(query_embedding)).limit(
        limit
    )
    return list(db.scalars(stmt).all())


def doc_chunk_fts_ids(
    db: Session,
    *,
    query: str,
    doc_type: str | None = None,
    app_name: str | None = None,
    pattern: str | None = None,
    limit: int = 40,
) -> list[int]:
    q = (query or "").strip()
    if not q:
        return []
    stmt = (
        select(DocChunk.id)
        .where(DocChunk.chunk_type != "parent")
        .where(
            text(
                "doc_chunks.content_tsv @@ plainto_tsquery('simple', :fts_q)"
            ).bindparams(fts_q=q)
        )
    )
    if doc_type:
        stmt = stmt.where(DocChunk.doc_type == doc_type)
    if app_name:
        stmt = stmt.where(DocChunk.app_name == app_name)
    if pattern is not None:
        stmt = stmt.where(DocChunk.pattern == pattern)
    stmt = stmt.limit(limit)
    try:
        return list(db.scalars(stmt).all())
    except Exception as exc:
        logger.warning("FTS doc_chunks failed (migration missing?): %s", exc)
        return []


def hybrid_doc_search(
    db: Session,
    *,
    query: str,
    app_name: str | None = None,
    pattern: str | None = None,
    scope: str = "all",
    top_n: int = 10,
) -> tuple[list[dict[str, Any]], str]:
    """Hybrid vector + FTS search over doc_chunks.

    Returns (results, mode):
    - no_index: no doc_chunks → empty
    - indexed_no_match: chunks exist but query matched nothing
    - hybrid_ok: results returned
    """
    doc_type_filter = None
    if scope in ("global", "app", "repo"):
        doc_type_filter = scope

    count_stmt = (
        select(func.count())
        .select_from(DocChunk)
        .where(DocChunk.chunk_type != "parent")
    )
    if doc_type_filter:
        count_stmt = count_stmt.where(DocChunk.doc_type == doc_type_filter)
    if app_name:
        count_stmt = count_stmt.where(DocChunk.app_name == app_name)
    if pattern is not None:
        count_stmt = count_stmt.where(DocChunk.pattern == pattern)

    has_chunks = bool(db.scalar(count_stmt))
    if not has_chunks:
        return [], "no_index"

    try:
        qvec = embed_query(query)
    except Exception as exc:
        logger.warning("doc query embed failed, FTS only: %s", exc)
        fts_ids = doc_chunk_fts_ids(
            db,
            query=query,
            doc_type=doc_type_filter,
            app_name=app_name,
            pattern=pattern,
            limit=top_n * 5,
        )
        if not fts_ids:
            return [], "indexed_no_match"
        ranked = fts_ids[:top_n]
    else:
        v_ids = doc_chunk_vector_ids(
            db,
            query_embedding=qvec,
            doc_type=doc_type_filter,
            app_name=app_name,
            pattern=pattern,
            limit=40,
        )
        f_ids = doc_chunk_fts_ids(
            db,
            query=query,
            doc_type=doc_type_filter,
            app_name=app_name,
            pattern=pattern,
            limit=40,
        )
        ranked = reciprocal_rank_fusion([v_ids, f_ids])[:top_n]

    if not ranked:
        return [], "indexed_no_match"

    # ORDER BY CASE 로 ranked 순서를 DB 레벨에서 유지 (P10).
    order_case = case({rid: idx for idx, rid in enumerate(ranked)}, value=DocChunk.id)
    ordered = list(
        db.scalars(
            select(DocChunk).where(DocChunk.id.in_(ranked)).order_by(order_case)
        ).all()
    )

    parent_ids = [
        ch.parent_chunk_id for ch in ordered if ch.parent_chunk_id is not None
    ]
    parents_by_id: dict[int, DocChunk] = {}
    if parent_ids:
        parents_by_id = {
            p.id: p
            for p in db.scalars(
                select(DocChunk).where(DocChunk.id.in_(parent_ids))
            ).all()
        }

    out: list[dict[str, Any]] = []
    for ch in ordered:
        parent = parents_by_id.get(ch.parent_chunk_id) if ch.parent_chunk_id else None
        out.append(
            {
                "chunk_id": ch.id,
                "doc_type": ch.doc_type,
                "doc_entity_id": ch.doc_entity_id,
                "app_name": ch.app_name,
                "pattern": ch.pattern,
                "section_name": ch.section_name,
                "chunk_index": ch.chunk_index,
                "content": ch.content,
                "parent_content": parent.content if parent else None,
                "metadata": ch.chunk_metadata,
            }
        )
    return out, "hybrid_ok"
