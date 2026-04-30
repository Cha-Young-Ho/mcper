"""로컬 Sentence Transformers 백엔드."""

from __future__ import annotations

import logging
from typing import Any

from app.config import EmbeddingSettings
from .utils import norm_inputs

logger = logging.getLogger(__name__)


class LocalSentenceTransformerBackend:
    """``sentence-transformers`` 인프로세스."""

    def __init__(self, cfg: EmbeddingSettings) -> None:
        self._cfg = cfg
        self._model: Any = None

    def _model_or_load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers 가 필요합니다: pip install sentence-transformers"
                ) from exc
            mid = self._cfg.local_model
            self._model = SentenceTransformer(mid)
            logger.info("Loaded embedding model (local): %s", mid)
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._model_or_load()
        vecs = model.encode(
            norm_inputs(texts),
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return [v.tolist() for v in vecs]
