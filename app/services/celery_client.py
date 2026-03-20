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
