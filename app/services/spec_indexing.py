"""기획서 spec → spec_chunks 동기 인덱싱 (Celery 워커·로컬 스크립트 공용)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Spec
from app.db.rag_models import SpecChunk
from app.services.chunking import chunk_spec_text
from app.services.embeddings import embed_texts

logger = logging.getLogger(__name__)


def index_spec_synchronously(db: Session, spec_id: int) -> dict[str, Any]:
    """spec_id 에 대해 청크 삭제 후 재생성·임베딩·INSERT. 호출측에서 commit/rollback 관리 없음(내부 처리)."""
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
    vectors = embed_texts(texts)

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


def insert_spec_chunks_with_embeddings(
    db: Session,
    spec_id: int,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """클라이언트가 이미 계산한 벡터로 spec_chunks 교체. ``chunks`` 는 content, embedding, (선택) metadata."""
    spec = db.get(Spec, spec_id)
    if spec is None:
        return {"ok": False, "error": "spec not found", "spec_id": spec_id}

    dim = settings.embedding_dim
    db.execute(delete(SpecChunk).where(SpecChunk.spec_id == spec_id))
    try:
        for i, ch in enumerate(chunks):
            emb = ch.get("embedding")
            if not isinstance(emb, list) or len(emb) != dim:
                db.rollback()
                return {
                    "ok": False,
                    "error": f"chunk {i}: embedding must be list[float] of length {dim}",
                    "spec_id": spec_id,
                }
            content = (ch.get("content") or "").strip()
            if not content:
                db.rollback()
                return {"ok": False, "error": f"chunk {i}: content empty", "spec_id": spec_id}
            raw_meta = ch.get("metadata")
            if raw_meta is None:
                raw_meta = ch.get("chunk_metadata")
            meta: dict[str, Any] = dict(raw_meta) if isinstance(raw_meta, dict) else {}
            meta["chunk_index"] = i
            db.add(
                SpecChunk(
                    spec_id=spec_id,
                    chunk_index=i,
                    content=content,
                    embedding=list(float(x) for x in emb),
                    chunk_metadata=meta,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "spec_id": spec_id, "chunks": len(chunks)}
