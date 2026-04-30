"""임베딩 백엔드 팩토리."""

import os

from app.config import EmbeddingSettings
from .backends import (
    BedrockBackend,
    LocalSentenceTransformerBackend,
    OpenAICompatibleBackend,
    SidecarEmbeddingBackend,
)
from .interface import EmbeddingBackend


def build_embedding_backend(cfg: EmbeddingSettings) -> EmbeddingBackend:
    """``EmbeddingSettings.provider`` 에 맞는 단일 백엔드 인스턴스."""
    p = cfg.provider
    if p == "local":
        return LocalSentenceTransformerBackend(cfg)
    if p == "openai":
        key = (cfg.openai_api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
        if not key:
            raise RuntimeError(
                "OpenAI 임베딩: embedding.openai_api_key 또는 OPENAI_API_KEY 가 필요합니다"
            )
        base = (cfg.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        return OpenAICompatibleBackend(
            base_url=base,
            api_key=key,
            model=cfg.openai_model,
            dim=cfg.dim,
        )
    if p == "localhost":
        base = (cfg.localhost_base_url or "http://127.0.0.1:11434/v1").rstrip("/")
        model = (cfg.localhost_model or "").strip()
        if not model:
            raise RuntimeError(
                "localhost 임베딩: embedding.localhost_model(또는 LOCALHOST_EMBEDDING_MODEL) 을 설정하세요"
            )
        key = (
            cfg.localhost_api_key or os.environ.get("LOCALHOST_EMBEDDING_API_KEY") or ""
        ).strip() or None
        return OpenAICompatibleBackend(
            base_url=base,
            api_key=key,
            model=model,
            dim=cfg.dim,
        )
    if p == "bedrock":
        return BedrockBackend(cfg)
    if p == "sidecar":
        url = (
            os.environ.get("EMBEDDING_SIDECAR_URL")
            or cfg.sidecar_url
            or "http://embed:8000"
        ).strip()
        return SidecarEmbeddingBackend(url)
    raise RuntimeError(f"알 수 없는 embedding.provider: {p}")
