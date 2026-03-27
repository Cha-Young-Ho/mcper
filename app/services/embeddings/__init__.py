"""임베딩 서비스 — 설정에 따라 로컬 ST / OpenAI 호환 HTTP / Bedrock."""

from .core import (
    configure_embedding_backend,
    embed_query,
    embed_texts,
    get_embedding_backend,
    validate_vector_dim,
)
from .factory import build_embedding_backend
from .interface import EmbeddingBackend

__all__ = [
    "EmbeddingBackend",
    "build_embedding_backend",
    "configure_embedding_backend",
    "get_embedding_backend",
    "embed_texts",
    "embed_query",
    "validate_vector_dim",
]
