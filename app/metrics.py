"""Prometheus metrics for MCPER.

Exposes request latency, error rates, Celery queue depth, and DB pool stats.
Enable with MCPER_METRICS_ENABLED=true (default: true).
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("mcper.metrics")

# ── Registry (isolated from default to avoid duplicates in tests) ────
registry = CollectorRegistry()

# ── Request Metrics ──────────────────────────────────────────────────
REQUEST_DURATION = Histogram(
    "mcper_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path", "status_code"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry,
)

REQUEST_TOTAL = Counter(
    "mcper_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
    registry=registry,
)

REQUEST_ERRORS = Counter(
    "mcper_http_errors_total",
    "Total HTTP error responses (4xx/5xx)",
    ["method", "path", "status_code"],
    registry=registry,
)

# ── Celery Queue Metrics ─────────────────────────────────────────────
CELERY_QUEUE_DEPTH = Gauge(
    "mcper_celery_queue_depth",
    "Number of tasks waiting in the Celery queue",
    ["queue_name"],
    registry=registry,
)

CELERY_TASK_SUCCESS = Gauge(
    "mcper_celery_task_success_total",
    "Total successful Celery tasks (from DB stats)",
    ["task_name"],
    registry=registry,
)

CELERY_TASK_FAILURE = Gauge(
    "mcper_celery_task_failure_total",
    "Total failed Celery tasks (from DB stats)",
    ["task_name"],
    registry=registry,
)

# ── DB Pool Metrics ──────────────────────────────────────────────────
DB_POOL_SIZE = Gauge(
    "mcper_db_pool_size",
    "Current DB connection pool size",
    registry=registry,
)

DB_POOL_CHECKED_IN = Gauge(
    "mcper_db_pool_checked_in",
    "DB connections currently checked in (idle)",
    registry=registry,
)

DB_POOL_CHECKED_OUT = Gauge(
    "mcper_db_pool_checked_out",
    "DB connections currently checked out (in use)",
    registry=registry,
)

DB_POOL_OVERFLOW = Gauge(
    "mcper_db_pool_overflow",
    "DB pool overflow connections",
    registry=registry,
)


def _normalize_path(path: str) -> str:
    """Collapse path parameters to reduce cardinality.

    /admin/specs/123 -> /admin/specs/{id}
    /mcp/sse/abc-def -> /mcp/sse/{session}
    """
    parts = path.strip("/").split("/")
    normalized = []
    for part in parts:
        if part.isdigit():
            normalized.append("{id}")
        elif len(part) > 20:
            normalized.append("{session}")
        else:
            normalized.append(part)
    return "/" + "/".join(normalized) if normalized else "/"


def _collect_celery_metrics() -> None:
    """Scrape Celery queue depth from Redis broker."""
    try:
        from app.config import settings
        broker = (settings.celery.broker_url or os.environ.get("CELERY_BROKER_URL") or "").strip()
        if not broker:
            return
        # redis_pool 싱글톤 재사용 — 메트릭 스크레이프마다 새 연결 생성을 피한다.
        from app.services.redis_pool import get_redis
        r = get_redis()
        if r is None:
            return
        depth = int(r.llen("celery"))
        CELERY_QUEUE_DEPTH.labels(queue_name="celery").set(depth)
    except Exception:
        pass


def _collect_celery_task_stats() -> None:
    """Pull aggregate task stats from DB."""
    try:
        from app.db.database import SessionLocal
        from app.db.celery_models import CeleryTaskStat
        db = SessionLocal()
        try:
            stats = db.query(CeleryTaskStat).all()
            for s in stats:
                CELERY_TASK_SUCCESS.labels(task_name=s.task_name).set(s.success_count)
                CELERY_TASK_FAILURE.labels(task_name=s.task_name).set(s.failure_count)
        finally:
            db.close()
    except Exception:
        pass


def _collect_db_pool_metrics() -> None:
    """Expose SQLAlchemy connection pool stats."""
    try:
        from app.db.database import engine
        pool = engine.pool
        DB_POOL_SIZE.set(pool.size())
        DB_POOL_CHECKED_IN.set(pool.checkedin())
        DB_POOL_CHECKED_OUT.set(pool.checkedout())
        DB_POOL_OVERFLOW.set(pool.overflow())
    except Exception:
        pass


def collect_all_metrics() -> None:
    """Refresh all pull-based metrics before scrape."""
    _collect_celery_metrics()
    _collect_celery_task_stats()
    _collect_db_pool_metrics()


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record request duration and count for every HTTP request."""

    # Skip metrics and health endpoints to avoid noise
    SKIP_PATHS = frozenset({"/metrics", "/health", "/health/rag"})

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if path in self.SKIP_PATHS:
            return await call_next(request)

        method = request.method
        normalized_path = _normalize_path(path)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        status_code = str(response.status_code)

        REQUEST_DURATION.labels(
            method=method,
            path=normalized_path,
            status_code=status_code,
        ).observe(duration)

        REQUEST_TOTAL.labels(
            method=method,
            path=normalized_path,
            status_code=status_code,
        ).inc()

        if response.status_code >= 400:
            REQUEST_ERRORS.labels(
                method=method,
                path=normalized_path,
                status_code=status_code,
            ).inc()

        return response
