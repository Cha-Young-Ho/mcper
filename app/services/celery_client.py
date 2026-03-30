"""Enqueue Celery tasks when broker is configured."""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def enqueue_index_spec(spec_id: int) -> bool:
    if not settings.celery_enabled:
        logger.warning(
            "CELERY_BROKER_URL unset — spec %s not auto-indexed (add Redis + worker)",
            spec_id,
        )
        return False
    try:
        from app.worker.tasks import index_spec_task

        index_spec_task.delay(spec_id)
        return True
    except Exception as exc:
        logger.exception("enqueue index_spec failed: %s", exc)
        return False


def enqueue_index_code_batch(app_target: str, payload: dict) -> bool:
    if not settings.celery_enabled:
        logger.warning("CELERY_BROKER_URL unset — code index not enqueued")
        return False
    try:
        from app.worker.tasks import index_code_batch_task

        index_code_batch_task.delay(app_target, payload)
        return True
    except Exception as exc:
        logger.exception("enqueue index_code_batch failed: %s", exc)
        return False


def enqueue_or_index_sync(spec_id: int) -> dict:
    """
    Celery가 있으면 비동기 큐에 추가, 없으면 동기 인덱싱으로 폴백.
    반환: {"queued": bool, "indexed": bool, "chunks": int | None}
    """
    if settings.celery_enabled:
        queued = enqueue_index_spec(spec_id)
        return {"queued": queued, "indexed": False, "chunks": None}

    # 동기 폴백: Celery 없이 직접 인덱싱
    logger.info("Celery unavailable — indexing spec %s synchronously", spec_id)
    try:
        from app.db.database import SessionLocal
        from app.db.models import Spec
        from app.db.rag_models import SpecChunk
        from app.services.chunking import chunk_spec_text
        from app.services.embeddings import embed_texts
        from sqlalchemy import delete

        db = SessionLocal()
        try:
            spec = db.get(Spec, spec_id)
            if spec is None:
                return {"queued": False, "indexed": False, "error": "spec not found"}
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
                return {"queued": False, "indexed": True, "chunks": 0}

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
            return {"queued": False, "indexed": True, "chunks": len(pairs)}
        finally:
            db.close()
    except Exception as exc:
        logger.exception("sync indexing failed spec_id=%s: %s", spec_id, exc)
        return {"queued": False, "indexed": False, "error": str(exc)}
