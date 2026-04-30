"""기획서 spec → spec_chunks 동기 인덱싱 (Celery 워커·로컬 스크립트 공용).

실제 로직은 app.spec.service.SpecIndexingService 로 위임.
이 모듈은 기존 호출 시그니처 유지를 위한 어댑터 레이어.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Spec
from app.db.rag_models import SpecChunk

logger = logging.getLogger(__name__)


def index_spec_synchronously(db: Session, spec_id: int) -> dict[str, Any]:
    """spec_id 에 대해 청크 삭제 후 재생성·임베딩·INSERT.

    내부적으로 SpecIndexingService (app.spec.service) 로 위임한다.
    """
    from app.spec.service import make_default_service

    spec = db.get(Spec, spec_id)
    if spec is None:
        return {"ok": False, "error": "spec not found", "spec_id": spec_id}

    result = make_default_service(db).index(
        spec_id=spec_id,
        content=spec.content,
        title=spec.title,
        app_target=spec.app_target,
        base_branch=spec.base_branch,
    )
    return {
        "ok": result.ok,
        "spec_id": result.spec_id,
        "chunks": result.child_count,
        "parents": result.parent_count,
        "error": result.error,
    }


def insert_spec_chunks_with_embeddings(
    db: Session,
    spec_id: int,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """클라이언트가 이미 계산한 벡터로 spec_chunks 교체 (push_spec_chunks_with_embeddings MCP 도구용).

    이 경로는 외부 벡터를 직접 주입하는 폴백 경로이므로 서비스 위임 없이 직접 처리.
    모든 청크는 chunk_type='child', parent_chunk_id=NULL 로 저장.
    """
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
                return {
                    "ok": False,
                    "error": f"chunk {i}: content empty",
                    "spec_id": spec_id,
                }
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
                    chunk_type="child",
                    parent_chunk_id=None,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "spec_id": spec_id, "chunks": len(chunks)}
