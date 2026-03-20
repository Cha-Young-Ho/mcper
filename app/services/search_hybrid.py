"""Hybrid vector + FTS search with reciprocal rank fusion (RRF)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import Spec
from app.db.rag_models import CodeEdge, CodeNode, SpecChunk
from app.services.embeddings import embed_query

logger = logging.getLogger(__name__)

RRF_K = 60


def reciprocal_rank_fusion(rank_lists: list[list[int]], k: int = RRF_K) -> list[int]:
    scores: dict[int, float] = {}
    for ranks in rank_lists:
        for rank, doc_id in enumerate(ranks, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.keys(), key=lambda x: scores[x], reverse=True)


def spec_chunk_vector_ids(
    db: Session,
    *,
    app_target: str,
    query_embedding: list[float],
    limit: int = 40,
) -> list[int]:
    stmt = (
        select(SpecChunk.id)
        .join(Spec, Spec.id == SpecChunk.spec_id)
        .where(Spec.app_target == app_target)
        .order_by(SpecChunk.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def spec_chunk_fts_ids(
    db: Session,
    *,
    app_target: str,
    query: str,
    limit: int = 40,
) -> list[int]:
    q = (query or "").strip()
    if not q:
        return []
    stmt = (
        select(SpecChunk.id)
        .join(Spec, Spec.id == SpecChunk.spec_id)
        .where(Spec.app_target == app_target)
        .where(
            text("spec_chunks.content_tsv @@ plainto_tsquery('simple', :fts_q)").bindparams(
                fts_q=q
            )
        )
        .limit(limit)
    )
    try:
        return list(db.scalars(stmt).all())
    except Exception as exc:
        logger.warning("FTS spec_chunks failed (migration missing?): %s", exc)
        return []


def hybrid_spec_search(
    db: Session,
    *,
    query: str,
    app_target: str,
    top_n: int = 10,
) -> tuple[list[dict[str, Any]], str]:
    """
    Returns (results, mode):
    - no_index: no spec_chunks for this app → caller may use ILIKE on specs
    - indexed_no_match: index exists but query matched nothing → optional ILIKE supplement
    - hybrid: vector+FTS hits returned in results (non-empty)
    """
    has_chunks = bool(
        db.scalar(
            select(func.count())
            .select_from(SpecChunk)
            .join(Spec, Spec.id == SpecChunk.spec_id)
            .where(Spec.app_target == app_target)
        )
    )
    if not has_chunks:
        return [], "no_index"

    try:
        qvec = embed_query(query)
    except Exception as exc:
        logger.warning("query embed failed, FTS only: %s", exc)
        fts_ids = spec_chunk_fts_ids(db, app_target=app_target, query=query, limit=top_n * 5)
        if not fts_ids:
            return [], "indexed_no_match"
        ranked = fts_ids[:top_n]
    else:
        v_ids = spec_chunk_vector_ids(db, app_target=app_target, query_embedding=qvec, limit=40)
        f_ids = spec_chunk_fts_ids(db, app_target=app_target, query=query, limit=40)
        ranked = reciprocal_rank_fusion([v_ids, f_ids])[: max(top_n, 20)]
        ranked = ranked[:top_n]

    if not ranked:
        return [], "indexed_no_match"

    rows = db.scalars(select(SpecChunk).where(SpecChunk.id.in_(ranked))).all()
    by_id = {r.id: r for r in rows}
    ordered = [by_id[i] for i in ranked if i in by_id]
    spec_ids = {r.spec_id for r in ordered}
    specs = {s.id: s for s in db.scalars(select(Spec).where(Spec.id.in_(spec_ids))).all()}

    out: list[dict[str, Any]] = []
    for ch in ordered:
        sp = specs.get(ch.spec_id)
        out.append(
            {
                "chunk_id": ch.id,
                "spec_id": ch.spec_id,
                "chunk_index": ch.chunk_index,
                "content": ch.content,
                "metadata": ch.chunk_metadata,
                "spec_title": sp.title if sp else None,
                "related_files": sp.related_files if sp else [],
                "base_branch": sp.base_branch if sp else None,
            }
        )
    return out, "hybrid_ok"


def code_node_vector_ids(
    db: Session,
    *,
    app_target: str,
    query_embedding: list[float],
    limit: int = 20,
) -> list[int]:
    stmt = (
        select(CodeNode.id)
        .where(CodeNode.app_target == app_target)
        .order_by(CodeNode.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def code_node_fts_ids(
    db: Session,
    *,
    app_target: str,
    query: str,
    limit: int = 20,
) -> list[int]:
    q = (query or "").strip()
    if not q:
        return []
    stmt = (
        select(CodeNode.id)
        .where(CodeNode.app_target == app_target)
        .where(
            text("code_nodes.content_tsv @@ plainto_tsquery('simple', :fts_q)").bindparams(fts_q=q)
        )
        .limit(limit)
    )
    try:
        return list(db.scalars(stmt).all())
    except Exception as exc:
        logger.warning("FTS code_nodes failed: %s", exc)
        return []


def hybrid_code_seed_ids(
    db: Session,
    *,
    query: str,
    app_target: str,
    top_n: int = 5,
) -> list[int]:
    has_nodes = bool(
        db.scalar(
            select(func.count()).select_from(CodeNode).where(CodeNode.app_target == app_target)
        )
    )
    if not has_nodes:
        return []
    try:
        qvec = embed_query(query)
    except Exception:
        return code_node_fts_ids(db, app_target=app_target, query=query, limit=top_n)
    v_ids = code_node_vector_ids(db, app_target=app_target, query_embedding=qvec, limit=25)
    f_ids = code_node_fts_ids(db, app_target=app_target, query=query, limit=25)
    return reciprocal_rank_fusion([v_ids, f_ids])[:top_n]


def traverse_code_graph(
    db: Session,
    *,
    app_target: str,
    seed_ids: list[int],
    max_depth_down: int = 4,
    max_depth_up: int = 2,
    max_nodes: int = 40,
) -> dict[str, Any]:
    """BFS on CodeEdge: callees (down) and callers (up)."""
    if not seed_ids:
        return {
            "seed_nodes": [],
            "downstream_nodes": [],
            "upstream_nodes": [],
            "edges": [],
        }

    down: set[int] = set()
    up: set[int] = set()
    frontier_down = list(seed_ids)
    frontier_up = list(seed_ids)
    depth_d = 0
    depth_u = 0
    while frontier_down and depth_d < max_depth_down and len(down) < max_nodes:
        nxt: set[int] = set()
        for sid in frontier_down:
            targets = db.scalars(
                select(CodeEdge.target_id).where(
                    CodeEdge.app_target == app_target,
                    CodeEdge.source_id == sid,
                )
            ).all()
            for t in targets:
                if t not in down and t not in seed_ids:
                    nxt.add(t)
        down.update(nxt)
        frontier_down = list(nxt)
        depth_d += 1

    while frontier_up and depth_u < max_depth_up and len(up) < max_nodes:
        nxt: set[int] = set()
        for tid in frontier_up:
            sources = db.scalars(
                select(CodeEdge.source_id).where(
                    CodeEdge.app_target == app_target,
                    CodeEdge.target_id == tid,
                )
            ).all()
            for s in sources:
                if s not in up and s not in seed_ids:
                    nxt.add(s)
        up.update(nxt)
        frontier_up = list(nxt)
        depth_u += 1

    all_ids = set(seed_ids) | down | up
    nodes = db.scalars(select(CodeNode).where(CodeNode.id.in_(all_ids))).all()
    node_by_id = {n.id: n for n in nodes}

    def node_dict(nid: int) -> dict[str, Any]:
        n = node_by_id.get(nid)
        if not n:
            return {"id": nid}
        return {
            "id": n.id,
            "stable_id": n.stable_id,
            "file_path": n.file_path,
            "symbol_name": n.symbol_name,
            "kind": n.kind,
            "content": n.content[:8000],
            "metadata": n.node_metadata,
        }

    edge_rows = db.scalars(
        select(CodeEdge).where(
            CodeEdge.app_target == app_target,
            (CodeEdge.source_id.in_(all_ids)) & (CodeEdge.target_id.in_(all_ids)),
        )
    ).all()
    edges_out = [
        {"source_id": e.source_id, "target_id": e.target_id, "relation": e.relation}
        for e in edge_rows
    ]
    return {
        "seed_nodes": [node_dict(i) for i in seed_ids if i in node_by_id],
        "downstream_nodes": [node_dict(i) for i in sorted(down) if i in node_by_id],
        "upstream_nodes": [node_dict(i) for i in sorted(up) if i in node_by_id],
        "edges": edges_out,
    }
