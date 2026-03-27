"""RAG/백그라운드 큐 상태 — 헬스 엔드포인트용 (K8s/ALB 프로브 보조)."""

from __future__ import annotations

import os
from typing import Any

from app.config import settings


def rag_health_payload() -> dict[str, Any]:
    """Celery 브로커(Redis) ping + 기본 큐 ``celery`` 대기 길이."""
    out: dict[str, Any] = {
        "celery_configured": bool(settings.celery_enabled),
        "celery_broker_reachable": None,
        "celery_queue_depth": None,
    }
    if not settings.celery_enabled:
        out["celery_note"] = "CELERY_BROKER_URL unset — no background index queue"
        return out

    broker = (settings.celery.broker_url or os.environ.get("CELERY_BROKER_URL") or "").strip()
    if not broker:
        out["celery_error"] = "broker URL empty"
        return out

    try:
        import redis

        r = redis.from_url(broker)
        r.ping()
        out["celery_broker_reachable"] = True
        # Celery 기본 큐 이름 (task_routes 미사용 시)
        out["celery_queue_depth"] = int(r.llen("celery"))
    except Exception as exc:
        out["celery_broker_reachable"] = False
        out["celery_error"] = str(exc)
    return out
