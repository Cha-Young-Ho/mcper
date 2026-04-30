"""ISpecChunkRepository 의 PostgreSQL + SQLAlchemy 구현체."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.rag_models import SpecChunk
from app.spec.interfaces import ISpecChunkRepository
from app.spec.models import ChunkRecord


class SqlAlchemySpecChunkRepository(ISpecChunkRepository):
    """spec_chunks 테이블 CRUD. flush/commit 은 Service 가 제어."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── 삭제 ─────────────────────────────────────────────────────────────────

    def delete_by_spec(self, spec_id: int) -> None:
        self._db.execute(delete(SpecChunk).where(SpecChunk.spec_id == spec_id))

    # ── 저장 ─────────────────────────────────────────────────────────────────

    def save_parent(self, spec_id: int, record: ChunkRecord) -> int:
        """Parent 청크 저장 후 flush() → DB id 반환."""
        row = SpecChunk(
            spec_id=spec_id,
            chunk_index=record.chunk_index,  # 음수
            content=record.content,
            embedding=None,  # parent 는 임베딩 없음
            chunk_metadata={
                **record.metadata,
                "chunk_type": "parent",
                "section_heading": record.section_heading,
            },
            chunk_type="parent",
            parent_chunk_id=None,
        )
        self._db.add(row)
        self._db.flush()  # id 를 얻기 위해 flush (commit 아님)
        return row.id

    def save_children(
        self,
        spec_id: int,
        records: list[ChunkRecord],
        parent_db_ids: dict[int, int],
        embeddings: list[list[float]],
    ) -> None:
        """Child 청크 배치 저장. parent_chunk_index → DB id 매핑을 parent_db_ids 로 수신."""
        for record, vec in zip(records, embeddings, strict=True):
            parent_db_id: int | None = None
            if record.parent_chunk_index is not None:
                parent_db_id = parent_db_ids.get(record.parent_chunk_index)

            self._db.add(
                SpecChunk(
                    spec_id=spec_id,
                    chunk_index=record.chunk_index,
                    content=record.content,
                    embedding=list(vec),
                    chunk_metadata={
                        **record.metadata,
                        "chunk_type": "child",
                        "section_heading": record.section_heading,
                        "chunk_index": record.chunk_index,
                    },
                    chunk_type="child",
                    parent_chunk_id=parent_db_id,
                )
            )

    # ── 트랜잭션 ─────────────────────────────────────────────────────────────

    def commit(self) -> None:
        self._db.commit()

    def rollback(self) -> None:
        self._db.rollback()
