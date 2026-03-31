"""spec 도메인 인터페이스 — 구현체 교체 시 이 파일만 알면 된다."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from app.spec.models import ChunkRecord, IndexResult


@runtime_checkable
class IChunkingStrategy(Protocol):
    """텍스트를 ChunkRecord 목록으로 변환하는 전략.

    구현체 예:
        HeadingAwareParentChildChunker — 헤딩 경계 + Parent-Child
        FixedSizeChunker               — 고정 크기 단순 분할 (기존 방식)
    """

    def chunk(
        self,
        text: str,
        base_metadata: dict[str, Any],
    ) -> list[ChunkRecord]: ...


class ISpecChunkRepository(ABC):
    """spec_chunks 테이블에 대한 CRUD. 트랜잭션 경계는 호출자(Service) 책임."""

    @abstractmethod
    def delete_by_spec(self, spec_id: int) -> None:
        """해당 spec 의 모든 청크 삭제 (commit 은 호출자 책임)."""

    @abstractmethod
    def save_parent(self, spec_id: int, record: ChunkRecord) -> int:
        """Parent 청크를 저장하고 flush() 후 DB-assigned id 를 반환."""

    @abstractmethod
    def save_children(
        self,
        spec_id: int,
        records: list[ChunkRecord],
        parent_db_ids: dict[int, int],
        embeddings: list[list[float]],
    ) -> None:
        """Child 청크 목록을 임베딩 벡터와 함께 저장.

        parent_db_ids: {parent_chunk_index(음수) → DB id} 매핑.
        parent_chunk_index 가 None 인 child 는 parent_chunk_id = NULL 로 저장.
        """

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...


@runtime_checkable
class IEmbeddingPort(Protocol):
    """임베딩 엔진 포트. 구현체를 교체해도 Service 는 변경 없음."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class ISpecIndexingService(Protocol):
    """외부에서 사용하는 인덱싱 서비스 진입점."""

    def index(
        self,
        spec_id: int,
        content: str,
        title: str | None,
        app_target: str,
        base_branch: str,
    ) -> IndexResult: ...
