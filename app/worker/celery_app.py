"""Celery application instance."""

from __future__ import annotations

import os

from celery import Celery

_broker = (os.environ.get("CELERY_BROKER_URL") or "").strip() or "redis://localhost:6379/0"
_backend = (os.environ.get("CELERY_RESULT_BACKEND") or "").strip() or _broker

celery_app = Celery(
    "mcper",
    broker=_broker,
    backend=_backend,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

from app.worker import tasks as _tasks  # noqa: E402, F401 — register task decorators

