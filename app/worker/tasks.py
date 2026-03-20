"""Background indexing: spec chunks and code graph (embeddings off the FastAPI event loop)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, select

from app.db.database import SessionLocal
from app.db.models import Spec
from app.db.rag_models import CodeEdge, CodeNode, SpecChunk
from app.services.chunking import chunk_spec_text
from app.services.embeddings import embed_texts
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="index_spec", bind=True, max_retries=3)
def index_spec_task(self, spec_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        spec = db.get(Spec, spec_id)
        if spec is None:
            return {"ok": False, "error": "spec not found", "spec_id": spec_id}
        db.execute(delete(SpecChunk).where(SpecChunk.spec_id == spec_id))
        db.commit()

        pairs = [
            (t, m)
            for t, m in chunk_spec_text(
                spec.content,
                base_metadata={
                    "app_target": spec.app_target,
                    "base_branch": spec.base_branch,
                    "spec_title": spec.title,
                    "spec_id": spec.id,
                },
            )
            if (t or "").strip()
        ]
        if not pairs:
            return {"ok": True, "spec_id": spec_id, "chunks": 0}

        texts = [p[0] for p in pairs]
        try:
            vectors = embed_texts(texts)
        except Exception as exc:
            logger.exception("embed failed spec_id=%s", spec_id)
            raise self.retry(exc=exc, countdown=10) from exc

        for i, ((text, meta), vec) in enumerate(zip(pairs, vectors, strict=True)):
            meta = dict(meta)
            meta["chunk_index"] = i
            db.add(
                SpecChunk(
                    spec_id=spec_id,
                    chunk_index=i,
                    content=text,
                    embedding=list(vec),
                    chunk_metadata=meta,
                )
            )
        db.commit()
        return {"ok": True, "spec_id": spec_id, "chunks": len(pairs)}
    except Exception as exc:
        db.rollback()
        logger.exception("index_spec_task failed spec_id=%s", spec_id)
        return {"ok": False, "error": str(exc), "spec_id": spec_id}
    finally:
        db.close()


@celery_app.task(name="index_code_batch", bind=True, max_retries=3)
def index_code_batch_task(self, app_target: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    payload: {
      "file_paths": ["src/a.py"],  # nodes under these paths are removed first (incident edges)
      "nodes": [{"stable_id","file_path","symbol_name","kind","content","metadata"?}, ...],
      "edges": [{"source_stable_id","target_stable_id","relation"}, ...]
    }
    """
    db = SessionLocal()
    try:
        app_key = (app_target or "").strip().lower()
        if not app_key:
            return {"ok": False, "error": "app_target required"}

        file_paths = payload.get("file_paths")
        nodes_raw = payload.get("nodes") or []
        edges_raw = payload.get("edges") or []

        if isinstance(file_paths, list) and file_paths:
            fps = [str(f) for f in file_paths if str(f).strip()]
            if fps:
                node_ids = list(
                    db.scalars(
                        select(CodeNode.id).where(
                            CodeNode.app_target == app_key,
                            CodeNode.file_path.in_(fps),
                        )
                    ).all()
                )
                if node_ids:
                    db.execute(
                        delete(CodeEdge).where(
                            (CodeEdge.source_id.in_(node_ids))
                            | (CodeEdge.target_id.in_(node_ids))
                        )
                    )
                    db.execute(delete(CodeNode).where(CodeNode.id.in_(node_ids)))
                db.commit()

        if not nodes_raw:
            return {"ok": True, "app_target": app_key, "nodes": 0, "edges": 0}

        texts = [str(n.get("content") or "") for n in nodes_raw]
        try:
            vectors = embed_texts(texts)
        except Exception as exc:
            logger.exception("embed code nodes failed app=%s", app_key)
            raise self.retry(exc=exc, countdown=10) from exc

        for n, vec in zip(nodes_raw, vectors, strict=True):
            sid = str(n.get("stable_id") or "").strip()
            if not sid:
                continue
            fp = str(n.get("file_path") or "").strip()
            row = db.scalars(
                select(CodeNode).where(
                    CodeNode.app_target == app_key,
                    CodeNode.stable_id == sid,
                )
            ).first()
            if row is None:
                row = CodeNode(
                    app_target=app_key,
                    stable_id=sid,
                    file_path=fp,
                    symbol_name=str(n.get("symbol_name") or ""),
                    kind=str(n.get("kind") or "fragment"),
                    content=str(n.get("content") or ""),
                    embedding=list(vec),
                    node_metadata=dict(n.get("metadata") or {}),
                )
                db.add(row)
            else:
                row.file_path = fp
                row.symbol_name = str(n.get("symbol_name") or "")
                row.kind = str(n.get("kind") or "fragment")
                row.content = str(n.get("content") or "")
                row.embedding = list(vec)
                row.node_metadata = dict(n.get("metadata") or {})
        db.commit()

        def node_id_for_stable(stable: str) -> int | None:
            r = db.scalars(
                select(CodeNode).where(
                    CodeNode.app_target == app_key,
                    CodeNode.stable_id == stable.strip(),
                )
            ).first()
            return r.id if r else None

        n_edges = 0
        for e in edges_raw:
            ss = str(e.get("source_stable_id") or "").strip()
            ts = str(e.get("target_stable_id") or "").strip()
            rel = str(e.get("relation") or "REL").strip()
            si = node_id_for_stable(ss)
            ti = node_id_for_stable(ts)
            if si is None or ti is None:
                continue
            db.add(
                CodeEdge(
                    app_target=app_key,
                    source_id=si,
                    target_id=ti,
                    relation=rel,
                )
            )
            n_edges += 1
        db.commit()
        return {
            "ok": True,
            "app_target": app_key,
            "nodes": len(nodes_raw),
            "edges": n_edges,
        }
    except Exception as exc:
        db.rollback()
        logger.exception("index_code_batch_task failed app=%s", app_target)
        return {"ok": False, "error": str(exc), "app_target": app_target}
    finally:
        db.close()
