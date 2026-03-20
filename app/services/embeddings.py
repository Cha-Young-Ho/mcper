"""Local embeddings via sentence-transformers (web query + Celery worker indexing)."""

from __future__ import annotations

import logging
from typing import Sequence

from app.config import settings

logger = logging.getLogger(__name__)

_local_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers 가 필요합니다: pip install sentence-transformers"
            ) from exc
        _local_model = SentenceTransformer(settings.local_embedding_model)
        logger.info("Loaded embedding model: %s", settings.local_embedding_model)
    return _local_model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_local_model()
    vecs = model.encode(
        [t if (t or "").strip() else " " for t in texts],
        convert_to_numpy=True,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return [v.tolist() for v in vecs]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def validate_vector_dim(vec: Sequence[float]) -> None:
    if len(vec) != settings.embedding_dim:
        raise ValueError(
            f"Embedding length {len(vec)} != EMBEDDING_DIM {settings.embedding_dim}"
        )
