"""Background indexing: spec chunks and code graph (embeddings off the FastAPI event loop)."""

from __future__ import annotations

import logging
import traceback
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.database import SessionLocal
from app.db.models import Spec
from app.db.rag_models import CodeEdge, CodeNode
from app.services.document_parser import parse_uploaded_file
from app.services.embeddings import embed_texts
from app.services.celery_monitoring import CeleryMonitoring
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="index_spec", bind=True, max_retries=3)
def index_spec_task(self, spec_id: int) -> dict[str, Any]:
    """기획서 청킹·임베딩·저장 — SpecIndexingService 로 위임."""
    from app.spec.service import make_default_service

    db = SessionLocal()
    try:
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
    except Exception as exc:
        db.rollback()
        CeleryMonitoring.log_task_failure(
            db,
            task_id=self.request.id,
            entity_type="spec",
            entity_id=spec_id,
            error_message=str(exc),
            traceback=traceback.format_exc(),
            max_retries=self.max_retries,
        )
        logger.exception("index_spec_task failed spec_id=%s", spec_id)
        if self.request.retries < self.max_retries:
            raise self.retry(
                exc=exc, countdown=10 * (self.request.retries + 1)
            ) from exc
        return {"ok": False, "error": str(exc), "spec_id": spec_id}
    finally:
        db.close()


@celery_app.task(name="parse_and_index_upload", bind=True, max_retries=3)
def parse_and_index_upload_task(
    self,
    filename: str,
    redis_key: str,
    app_target: str,
    base_branch: str,
) -> dict[str, Any]:
    """
    파일 파싱 + DB 저장 + 임베딩을 Celery worker에서 처리.

    파일 바이너리는 Redis에 TTL로 보관. Celery 메시지엔 Redis key만 전달.
    - base64 직렬화 오버헤드 없음
    - 대용량 파일도 메시지 큐 부담 없음
    - 재시도 시 Redis에서 재조회 (TTL 내에서만)
    """
    import redis as redis_lib

    from app.config import settings

    db = SessionLocal()
    raw: bytes | None = None
    try:
        rdb = redis_lib.from_url(settings.celery.broker_url)
        raw = rdb.get(redis_key)
        if raw is None:
            return {
                "ok": False,
                "filename": filename,
                "error": "파일 키 만료 (Redis TTL 초과 또는 이미 처리됨)",
            }

        from pathlib import Path

        text = parse_uploaded_file(filename, raw)
        if not text.strip():
            rdb.delete(redis_key)
            return {
                "ok": False,
                "filename": filename,
                "error": "파일 내용이 비어 있습니다",
            }

        title = Path(filename).stem
        app_key = (app_target or "").strip().lower()
        branch = (base_branch or "main").strip() or "main"

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

        # 청킹·임베딩은 SpecIndexingService 로 위임 (Spec 행은 이미 flush 완료)
        from app.spec.service import make_default_service

        try:
            result = make_default_service(db).index(
                spec_id=spec_id,
                content=text,
                title=title,
                app_target=app_key,
                base_branch=branch,
            )
        except Exception as exc:
            logger.exception("embed failed filename=%s", filename)
            db.rollback()
            raise self.retry(exc=exc, countdown=10) from exc
        rdb.delete(redis_key)  # 성공 시 정리
        return {
            "ok": True,
            "filename": filename,
            "spec_id": spec_id,
            "chunks": result.child_count,
        }

    except Exception as exc:
        db.rollback()
        CeleryMonitoring.log_task_failure(
            db,
            task_id=self.request.id,
            entity_type="upload",
            entity_id=0,
            error_message=str(exc),
            traceback=traceback.format_exc(),
            max_retries=self.max_retries,
        )
        logger.exception("parse_and_index_upload_task failed filename=%s", filename)
        if self.request.retries < self.max_retries:
            countdown = 10 * (self.request.retries + 1)
            raise self.retry(exc=exc, countdown=countdown) from exc
        return {"ok": False, "filename": filename, "error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="index_code_batch", bind=True, max_retries=3)
def index_code_batch_task(
    self, app_target: str, payload: dict[str, Any]
) -> dict[str, Any]:
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

        edge_values = []
        for e in edges_raw:
            ss = str(e.get("source_stable_id") or "").strip()
            ts = str(e.get("target_stable_id") or "").strip()
            rel = str(e.get("relation") or "REL").strip()
            si = node_id_for_stable(ss)
            ti = node_id_for_stable(ts)
            if si is None or ti is None:
                continue
            edge_values.append(
                {
                    "app_target": app_key,
                    "source_id": si,
                    "target_id": ti,
                    "relation": rel,
                }
            )

        n_edges = len(edge_values)
        if edge_values:
            # 배치 INSERT + ON CONFLICT DO NOTHING (중복 edge 방지)
            db.execute(pg_insert(CodeEdge).values(edge_values).on_conflict_do_nothing())
        db.commit()
        return {
            "ok": True,
            "app_target": app_key,
            "nodes": len(nodes_raw),
            "edges": n_edges,
        }
    except Exception as exc:
        db.rollback()

        # Log failure for monitoring
        CeleryMonitoring.log_task_failure(
            db,
            task_id=self.request.id,
            entity_type="code_index",
            entity_id=0,  # app_target is string, use 0 as placeholder
            error_message=str(exc),
            traceback=traceback.format_exc(),
            max_retries=self.max_retries,
        )

        logger.exception("index_code_batch_task failed app=%s", app_target)

        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            countdown = 10 * (self.request.retries + 1)
            raise self.retry(exc=exc, countdown=countdown) from exc

        return {"ok": False, "error": str(exc), "app_target": app_target}
    finally:
        db.close()
