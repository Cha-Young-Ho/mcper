"""SkillChunk repository — mirrors SqlAlchemySpecChunkRepository."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.rag_models import SkillChunk
from app.spec.models import ChunkRecord


def _eq_or_null(col, value):
    """SQLAlchemy helper: `col IS NULL` when value is None, otherwise `col == value`."""
    return col.is_(None) if value is None else col == value


class SqlAlchemySkillChunkRepository:
    """skill_chunks CRUD. flush/commit controlled by service."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def delete_by_section(
        self,
        skill_type: str,
        *,
        app_name: str | None,
        section_name: str,
    ) -> None:
        """같은 (type, app_name, section) 조합의 모든 버전 청크를 삭제.

        entity_id 기준이 아닌 section 기준이므로 재발행 시 이전 버전 청크가 누적되지 않는다.
        SkillChunk 는 pattern 컬럼이 없으므로 repo skill 은 skill_type='repo' + section_name 으로만 구분.
        """
        self._db.execute(
            delete(SkillChunk).where(
                SkillChunk.skill_type == skill_type,
                _eq_or_null(SkillChunk.app_name, app_name),
                SkillChunk.section_name == section_name,
            )
        )

    def save_parent(
        self,
        skill_type: str,
        skill_entity_id: int,
        record: ChunkRecord,
        *,
        app_name: str | None = None,
        domain: str | None = None,
        section_name: str = "main",
    ) -> int:
        row = SkillChunk(
            skill_type=skill_type,
            skill_entity_id=skill_entity_id,
            app_name=app_name,
            domain=domain,
            section_name=section_name,
            chunk_index=record.chunk_index,
            content=record.content,
            embedding=None,
            chunk_metadata={
                **record.metadata,
                "chunk_type": "parent",
                "section_heading": record.section_heading,
            },
            chunk_type="parent",
            parent_chunk_id=None,
        )
        self._db.add(row)
        self._db.flush()
        return row.id

    def save_children(
        self,
        skill_type: str,
        skill_entity_id: int,
        records: list[ChunkRecord],
        parent_db_ids: dict[int, int],
        embeddings: list[list[float]],
        *,
        app_name: str | None = None,
        domain: str | None = None,
        section_name: str = "main",
    ) -> None:
        for record, vec in zip(records, embeddings, strict=True):
            parent_db_id: int | None = None
            if record.parent_chunk_index is not None:
                parent_db_id = parent_db_ids.get(record.parent_chunk_index)

            self._db.add(
                SkillChunk(
                    skill_type=skill_type,
                    skill_entity_id=skill_entity_id,
                    app_name=app_name,
                    domain=domain,
                    section_name=section_name,
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

    def commit(self) -> None:
        self._db.commit()

    def rollback(self) -> None:
        self._db.rollback()
