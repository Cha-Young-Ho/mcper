"""부트 시 `configure_embedding_backend` 로 조립된 어댑터로 임베딩."""

from __future__ import annotations

from typing import Sequence

from app.config import EmbeddingSettings, settings
from .factory import build_embedding_backend
from .interface import EmbeddingBackend

_backend: EmbeddingBackend | None = None


def configure_embedding_backend(cfg: EmbeddingSettings | None = None) -> None:
    """앱·Celery 워커 기동 시 한 번 호출. ``cfg`` 생략 시 전역 ``settings.embedding`` 사용."""
    global _backend
    emb = cfg if cfg is not None else settings.embedding
    _backend = build_embedding_backend(emb)


def get_embedding_backend() -> EmbeddingBackend:
    """첫 호출 시 아직 조립되지 않았으면 ``settings.embedding`` 으로 조립한다."""
    global _backend
    if _backend is None:
        configure_embedding_backend(settings.embedding)
    assert _backend is not None
    return _backend


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    backend = get_embedding_backend()
    vectors = backend.embed_texts(texts)
    dim = settings.embedding.dim
    for i, vec in enumerate(vectors):
        if len(vec) != dim:
            raise ValueError(
                f"임베딩 길이 {len(vec)} != 설정 embedding.dim {dim} "
                f"(provider={settings.embedding.provider}, 청크 인덱스 {i})"
            )
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def validate_vector_dim(vec: Sequence[float]) -> None:
    if len(vec) != settings.embedding.dim:
        raise ValueError(
            f"Embedding length {len(vec)} != embedding.dim {settings.embedding.dim}"
        )
