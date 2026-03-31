"""Enqueue Celery tasks when broker is configured."""

from __future__ import annotations

import logging
import uuid

from app.config import settings

logger = logging.getLogger(__name__)

# Redis 파일 스테이징: 파일 바이너리를 TTL로 보관하고, Celery 메시지엔 key만 전달.
# Worker가 key로 Redis에서 직접 바이너리를 조회하므로 base64 오버헤드가 없음.
_UPLOAD_KEY_PREFIX = "mcper:upload:"
_UPLOAD_FILE_TTL_SECONDS = 1800  # 30분 (재시도 포함 충분한 여유)


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


def enqueue_parse_and_index_upload(
    filename: str,
    raw: bytes,
    app_target: str,
    base_branch: str,
) -> dict:
    """
    파일 파싱 + DB 저장 + 임베딩을 Celery worker에 위임.

    파일 바이너리는 Redis에 TTL로 저장하고, Celery 메시지엔 Redis key만 포함.
    - base64 직렬화 없음 — 바이너리 그대로 Redis에 저장
    - 대용량 파일도 메시지 큐 부담 없음
    - Celery 미설정 시 동기 fallback

    반환: {"queued": bool, "ok": bool | None, "error": str | None}
    """
    if not settings.celery_enabled:
        logger.info("Celery 미설정 — %s 동기 처리", filename)
        return _parse_and_index_sync(filename, raw, app_target, base_branch)

    try:
        import redis as redis_lib

        from app.worker.tasks import parse_and_index_upload_task

        rdb = redis_lib.from_url(settings.celery.broker_url)
        file_key = f"{_UPLOAD_KEY_PREFIX}{uuid.uuid4().hex}"
        rdb.setex(file_key, _UPLOAD_FILE_TTL_SECONDS, raw)

        parse_and_index_upload_task.delay(filename, file_key, app_target, base_branch)
        logger.info(
            "업로드 큐 등록: filename=%s key=%s size=%.1fKB",
            filename,
            file_key,
            len(raw) / 1024,
        )
        return {"queued": True, "ok": None, "error": None}
    except Exception as exc:
        logger.exception("enqueue_parse_and_index_upload 실패: %s", exc)
        return {"queued": False, "ok": False, "error": str(exc)}


def _parse_and_index_sync(
    filename: str,
    raw: bytes,
    app_target: str,
    base_branch: str,
) -> dict:
    """Celery 없이 동기로 파싱 + 저장 + 인덱싱 (개발/테스트 환경 fallback)."""
    from pathlib import Path

    from sqlalchemy import delete

    from app.db.database import SessionLocal
    from app.db.models import Spec
    from app.db.rag_models import SpecChunk
    from app.services.chunking import chunk_spec_text
    from app.services.document_parser import parse_uploaded_file
    from app.services.embeddings import embed_texts

    try:
        text = parse_uploaded_file(filename, raw)
        if not text.strip():
            return {"queued": False, "ok": False, "error": "파일 내용이 비어 있습니다"}

        title = Path(filename).stem
        app_key = (app_target or "").strip().lower()
        branch = (base_branch or "main").strip() or "main"

        db = SessionLocal()
        try:
            spec = Spec(
                title=title,
                content=text,
                app_target=app_key,
                base_branch=branch,
                related_files=[],
            )
            db.add(spec)
            db.flush()
            spec_id = spec.id

            db.execute(delete(SpecChunk).where(SpecChunk.spec_id == spec_id))
            pairs = [
                (t, m)
                for t, m in chunk_spec_text(
                    text,
                    base_metadata={
                        "app_target": app_key,
                        "base_branch": branch,
                        "spec_title": title,
                        "spec_id": spec_id,
                    },
                )
                if (t or "").strip()
            ]
            if pairs:
                vectors = embed_texts([p[0] for p in pairs])
                for i, ((chunk_text, meta), vec) in enumerate(zip(pairs, vectors, strict=True)):
                    meta = dict(meta)
                    meta["chunk_index"] = i
                    db.add(
                        SpecChunk(
                            spec_id=spec_id,
                            chunk_index=i,
                            content=chunk_text,
                            embedding=list(vec),
                            chunk_metadata=meta,
                        )
                    )
            db.commit()
            return {"queued": False, "ok": True, "spec_id": spec_id, "chunks": len(pairs)}
        finally:
            db.close()
    except Exception as exc:
        logger.exception("동기 parse_and_index 실패 filename=%s: %s", filename, exc)
        return {"queued": False, "ok": False, "error": str(exc)}


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
