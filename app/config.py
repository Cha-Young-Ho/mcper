"""Runtime configuration from environment (local embedding, Celery)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Immutable settings snapshot at import time."""

    embedding_dim: int
    local_embedding_model: str
    celery_broker_url: str
    celery_result_backend: str

    @property
    def celery_enabled(self) -> bool:
        return bool(self.celery_broker_url.strip())


def load_settings() -> Settings:
    # all-MiniLM-L6-v2 → 384 dims (normalized); 모델 바꾸면 EMBEDDING_DIM을 모델 출력에 맞출 것
    dim = _env_int("EMBEDDING_DIM", 384)
    broker = (os.environ.get("CELERY_BROKER_URL") or "").strip()
    result = (os.environ.get("CELERY_RESULT_BACKEND") or broker).strip()
    return Settings(
        embedding_dim=dim,
        local_embedding_model=(
            os.environ.get("LOCAL_EMBEDDING_MODEL") or "sentence-transformers/all-MiniLM-L6-v2"
        ).strip(),
        celery_broker_url=broker,
        celery_result_backend=result,
    )


settings = load_settings()
