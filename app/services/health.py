"""헬스 체크 로직 — liveness/readiness/startup 분리 (L09).

LB/K8s probe 용 3단계:
- liveness: 프로세스 응답만 확인 (의존 없음)
- readiness: DB + Redis + 임베딩 backend 준비 확인
- startup: lifespan 완료 여부

각 체크는 2초 타임아웃. 블로킹 호출은 ``asyncio.to_thread`` 로 격리.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from app.config import settings

_CHECK_TIMEOUT_SEC = 2.0


async def _with_timeout(coro, timeout: float = _CHECK_TIMEOUT_SEC) -> tuple[bool, str | None]:
    """Coroutine 을 타임아웃과 함께 실행. (성공여부, 에러메시지) 반환."""
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return (bool(result), None)
    except asyncio.TimeoutError:
        return (False, f"timeout>{timeout}s")
    except Exception as exc:
        return (False, str(exc))


async def _check_db() -> tuple[bool, str | None]:
    """DB 연결 확인 (blocking → thread)."""
    from app.db.database import check_db_connection

    return await _with_timeout(asyncio.to_thread(check_db_connection))


async def _check_redis() -> tuple[str, str | None]:
    """Redis 브로커 ping. 미설정이면 'skip'."""
    if not settings.celery_enabled:
        return ("skip", "celery not configured")

    broker = (settings.celery.broker_url or os.environ.get("CELERY_BROKER_URL") or "").strip()
    if not broker:
        return ("skip", "broker URL empty")

    def _ping() -> bool:
        import redis

        r = redis.from_url(broker, socket_connect_timeout=_CHECK_TIMEOUT_SEC)
        try:
            return bool(r.ping())
        finally:
            try:
                r.close()
            except Exception:
                pass

    ok, err = await _with_timeout(asyncio.to_thread(_ping))
    return ("up" if ok else "down", err)


async def _check_embedding() -> tuple[bool, str | None]:
    """임베딩 backend 가 초기화됐는지 확인 (ENV 의존 — 가벼움)."""

    def _ready() -> bool:
        from app.services.embeddings.core import _backend  # type: ignore[attr-defined]

        return _backend is not None

    return await _with_timeout(asyncio.to_thread(_ready))


async def liveness_payload() -> dict[str, Any]:
    """Liveness — 프로세스 응답성만 확인. 의존 검사 없음."""
    return {"status": "ok", "checks": {}, "latency_ms": 0}


async def readiness_payload(startup_done: bool = True) -> tuple[dict[str, Any], int]:
    """Readiness — DB + Redis + 임베딩 backend 준비 확인.

    반환: (payload, http_status). 하나라도 실패 시 503.
    """
    t0 = time.monotonic()

    # 병렬 실행
    db_task = asyncio.create_task(_check_db())
    redis_task = asyncio.create_task(_check_redis())
    emb_task = asyncio.create_task(_check_embedding())

    db_ok, db_err = await db_task
    redis_state, redis_err = await redis_task
    emb_ok, emb_err = await emb_task

    checks: dict[str, str] = {
        "db": "up" if db_ok else "down",
        "redis": redis_state,
        "embedding": "ready" if emb_ok else "not_ready",
        "startup": "done" if startup_done else "pending",
    }
    errors: dict[str, str] = {}
    if db_err:
        errors["db"] = db_err
    if redis_err and redis_state != "skip":
        errors["redis"] = redis_err
    if emb_err:
        errors["embedding"] = emb_err

    # readiness 판정: DB up + embedding ready + startup done.
    # Redis 는 skip 허용 (celery 비활성 환경), down 은 실패.
    healthy = (
        db_ok
        and emb_ok
        and startup_done
        and redis_state in ("up", "skip")
    )

    latency_ms = int((time.monotonic() - t0) * 1000)
    payload: dict[str, Any] = {
        "status": "ok" if healthy else "unhealthy",
        "checks": checks,
        "latency_ms": latency_ms,
    }
    if errors:
        payload["errors"] = errors

    return (payload, 200 if healthy else 503)


async def startup_payload(startup_done: bool) -> tuple[dict[str, Any], int]:
    """Startup probe — lifespan 완료 여부. 완료 후에는 readiness 로직 실행."""
    if not startup_done:
        return (
            {
                "status": "unhealthy",
                "checks": {"startup": "pending"},
                "latency_ms": 0,
            },
            503,
        )
    # startup 완료 후에는 readiness 와 동일 로직
    return await readiness_payload(startup_done=True)
