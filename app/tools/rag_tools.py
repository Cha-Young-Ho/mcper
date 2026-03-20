"""MCP tools: code graph push, impact analysis, historical spec reference."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import Spec
from app.db.rag_models import SpecChunk
from app.services.celery_client import enqueue_index_code_batch
from app.services.mcp_tool_stats import record_mcp_tool_call
from app.services.search_hybrid import (
    hybrid_code_seed_ids,
    spec_chunk_vector_ids,
    traverse_code_graph,
)
from app.services.embeddings import embed_query


def _parse_json_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            data = json.loads(s)
            return list(data) if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
    return []


def push_code_index_impl(
    app_target: str,
    file_paths: list[str] | str,
    nodes: list[dict[str, Any]] | str,
    edges: list[dict[str, Any]] | str,
) -> str:
    record_mcp_tool_call("push_code_index")
    if isinstance(file_paths, list):
        fps = [str(x).strip() for x in file_paths if str(x).strip()]
    else:
        fps = [str(x).strip() for x in _parse_json_list(file_paths) if str(x).strip()]
    nodes_l = nodes if isinstance(nodes, list) else _parse_json_list(nodes)
    edges_l = edges if isinstance(edges, list) else _parse_json_list(edges)
    payload = {"file_paths": fps, "nodes": nodes_l, "edges": edges_l}
    ok = enqueue_index_code_batch(app_target.strip().lower(), payload)
    if not ok:
        return json.dumps(
            {
                "ok": False,
                "error": "Celery broker not configured or enqueue failed",
                "action_required": "Set CELERY_BROKER_URL and run worker container",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "ok": True,
            "message": "index_code_batch enqueued",
            "app_target": app_target.strip().lower(),
            "nodes_queued": len(nodes_l),
            "edges_queued": len(edges_l),
        },
        ensure_ascii=False,
    )


def analyze_code_impact_impl(query: str, app_target: str) -> str:
    record_mcp_tool_call("analyze_code_impact")
    db: Session = SessionLocal()
    try:
        seeds = hybrid_code_seed_ids(db, query=query, app_target=app_target, top_n=5)
        if not seeds:
            return json.dumps(
                {
                    "ok": True,
                    "message": "no code nodes indexed for this app (use push_code_index first)",
                    "graph": None,
                },
                ensure_ascii=False,
            )
        graph = traverse_code_graph(
            db,
            app_target=app_target,
            seed_ids=seeds,
        )
        return json.dumps({"ok": True, "seed_ids": seeds, "graph": graph}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "error": str(exc),
                "action_required": "check EMBEDDING_DIM, LOCAL_EMBEDDING_MODEL, code index",
            },
            ensure_ascii=False,
        )
    finally:
        db.close()


def find_historical_reference_impl(new_spec_text: str, app_target: str, top_n: int = 5) -> str:
    record_mcp_tool_call("find_historical_reference")
    db: Session = SessionLocal()
    try:
        snippet = (new_spec_text or "")[:8000]
        if not snippet.strip():
            return json.dumps(
                {"ok": False, "error": "new_spec_text empty", "action_required": "pass spec body"},
                ensure_ascii=False,
            )
        try:
            qvec = embed_query(snippet)
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"embed failed: {exc}",
                    "action_required": "install sentence-transformers and match EMBEDDING_DIM to model",
                },
                ensure_ascii=False,
            )
        v_ids = spec_chunk_vector_ids(
            db, app_target=app_target, query_embedding=qvec, limit=30
        )
        ranked = v_ids[:top_n]
        if not ranked:
            return json.dumps(
                {
                    "ok": True,
                    "message": "no similar chunks (index specs with Celery worker first)",
                    "matches": [],
                },
                ensure_ascii=False,
            )
        chunks = db.scalars(select(SpecChunk).where(SpecChunk.id.in_(ranked))).all()
        by_id = {c.id: c for c in chunks}
        spec_ids = {c.spec_id for c in chunks}
        specs = {s.id: s for s in db.scalars(select(Spec).where(Spec.id.in_(spec_ids))).all()}
        matches: list[dict[str, Any]] = []
        for cid in ranked:
            ch = by_id.get(cid)
            if not ch:
                continue
            sp = specs.get(ch.spec_id)
            matches.append(
                {
                    "chunk_id": ch.id,
                    "spec_id": ch.spec_id,
                    "chunk_excerpt": ch.content[:2000],
                    "metadata": ch.chunk_metadata,
                    "spec_title": sp.title if sp else None,
                    "related_files": sp.related_files if sp else [],
                    "base_branch": sp.base_branch if sp else None,
                }
            )
        return json.dumps({"ok": True, "matches": matches}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


def register_rag_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def push_code_index(
        app_target: str,
        file_paths: list[str] | str,
        nodes: list[dict[str, Any]] | str,
        edges: list[dict[str, Any]] | str,
    ) -> str:
        """
        Enqueue AST/symbol code index for an app. nodes need stable_id, file_path, symbol_name, kind, content.
        edges: source_stable_id, target_stable_id, relation (e.g. CALLS). file_paths: replace index for these paths first.
        """
        return push_code_index_impl(app_target, file_paths, nodes, edges)

    @mcp.tool()
    def analyze_code_impact(query: str, app_target: str) -> str:
        """Hybrid search seed + graph traversal (upstream/downstream) over indexed code_nodes/code_edges."""
        return analyze_code_impact_impl(query, app_target)

    @mcp.tool()
    def find_historical_reference(new_spec_text: str, app_target: str, top_n: int = 5) -> str:
        """Find similar past spec chunks and linked related_files for few-shot / Spec-to-Code context."""
        return find_historical_reference_impl(new_spec_text, app_target, top_n)
