"""임베딩 백엔드 인터페이스 — 모든 구현체는 이를 만족해야 함."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingBackend(Protocol):
    """임베딩 구현체 — ``embed_texts`` 만 맞추면 교체 가능."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """텍스트 목록을 임베딩 벡터로 변환."""
        ...
