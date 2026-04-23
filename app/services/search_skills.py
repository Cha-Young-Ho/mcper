"""Hybrid vector + FTS search for skill_chunks (mirrors search_hybrid.py pattern)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.rag_models import SkillChunk
from app.services.embeddings import embed_query
from app.services.search_hybrid import reciprocal_rank_fusion

logger = logging.getLogger(__name__)


def skill_chunk_vector_ids(
    db: Session,
    *,
    query_embedding: list[float],
    skill_type: str | None = None,
    app_name: str | None = None,
    limit: int = 40,
) -> list[int]:
    stmt = (
        select(SkillChunk.id)
        .where(SkillChunk.chunk_type != "parent")
        .where(SkillChunk.embedding.isnot(None))
    )
    if skill_type:
        stmt = stmt.where(SkillChunk.skill_type == skill_type)
    if app_name:
        stmt = stmt.where(SkillChunk.app_name == app_name)
    stmt = stmt.order_by(SkillChunk.embedding.cosine_distance(query_embedding)).limit(limit)
    return list(db.scalars(stmt).all())


def skill_chunk_fts_ids(
    db: Session,
    *,
    query: str,
    skill_type: str | None = None,
    app_name: str | None = None,
    limit: int = 40,
) -> list[int]:
    q = (query or "").strip()
    if not q:
        return []
    stmt = (
        select(SkillChunk.id)
        .where(SkillChunk.chunk_type != "parent")
        .where(
            text("skill_chunks.content_tsv @@ plainto_tsquery('simple', :fts_q)").bindparams(
                fts_q=q
            )
        )
    )
    if skill_type:
        stmt = stmt.where(SkillChunk.skill_type == skill_type)
    if app_name:
        stmt = stmt.where(SkillChunk.app_name == app_name)
    stmt = stmt.limit(limit)
    try:
        return list(db.scalars(stmt).all())
    except Exception as exc:
        logger.warning("FTS skill_chunks failed (migration missing?): %s", exc)
        return []


def hybrid_skill_search(
    db: Session,
    *,
    query: str,
    app_name: str | None = None,
    scope: str = "all",
    top_n: int = 10,
) -> tuple[list[dict[str, Any]], str]:
    """Hybrid vector + FTS search over skill_chunks.

    Returns (results, mode):
    - no_index: no skill_chunks → empty
    - indexed_no_match: chunks exist but query matched nothing
    - hybrid_ok: results returned
    """
    skill_type_filter = None
    if scope in ("global", "app", "repo"):
        skill_type_filter = scope

    # Check if any chunks exist
    count_stmt = (
        select(func.count())
        .select_from(SkillChunk)
        .where(SkillChunk.chunk_type != "parent")
    )
    if skill_type_filter:
        count_stmt = count_stmt.where(SkillChunk.skill_type == skill_type_filter)
    if app_name:
        count_stmt = count_stmt.where(SkillChunk.app_name == app_name)

    has_chunks = bool(db.scalar(count_stmt))
    if not has_chunks:
        return [], "no_index"

    try:
        qvec = embed_query(query)
    except Exception as exc:
        logger.warning("skill query embed failed, FTS only: %s", exc)
        fts_ids = skill_chunk_fts_ids(
            db, query=query, skill_type=skill_type_filter, app_name=app_name,
            limit=top_n * 5,
        )
        if not fts_ids:
            return [], "indexed_no_match"
        ranked = fts_ids[:top_n]
    else:
        v_ids = skill_chunk_vector_ids(
            db, query_embedding=qvec, skill_type=skill_type_filter,
            app_name=app_name, limit=40,
        )
        f_ids = skill_chunk_fts_ids(
            db, query=query, skill_type=skill_type_filter,
            app_name=app_name, limit=40,
        )
        ranked = reciprocal_rank_fusion([v_ids, f_ids])[:top_n]

    if not ranked:
        return [], "indexed_no_match"

    rows = db.scalars(select(SkillChunk).where(SkillChunk.id.in_(ranked))).all()
    by_id = {r.id: r for r in rows}
    ordered = [by_id[i] for i in ranked if i in by_id]

    # Fetch parents for context
    parent_ids = [ch.parent_chunk_id for ch in ordered if ch.parent_chunk_id is not None]
    parents_by_id: dict[int, SkillChunk] = {}
    if parent_ids:
        parents_by_id = {
            p.id: p
            for p in db.scalars(select(SkillChunk).where(SkillChunk.id.in_(parent_ids))).all()
        }

    out: list[dict[str, Any]] = []
    for ch in ordered:
        parent = parents_by_id.get(ch.parent_chunk_id) if ch.parent_chunk_id else None
        out.append({
            "chunk_id": ch.id,
            "skill_type": ch.skill_type,
            "skill_entity_id": ch.skill_entity_id,
            "app_name": ch.app_name,
            "section_name": ch.section_name,
            "chunk_index": ch.chunk_index,
            "content": ch.content,
            "parent_content": parent.content if parent else None,
            "metadata": ch.chunk_metadata,
        })
    return out, "hybrid_ok"
