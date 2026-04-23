"""RuleChunk repository — mirrors SqlAlchemySkillChunkRepository."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.rag_models import RuleChunk
from app.spec.models import ChunkRecord


class SqlAlchemyRuleChunkRepository:

    def __init__(self, db: Session) -> None:
        self._db = db

    def delete_by_rule(self, rule_type: str, rule_entity_id: int) -> None:
        self._db.execute(
            delete(RuleChunk).where(
                RuleChunk.rule_type == rule_type,
                RuleChunk.rule_entity_id == rule_entity_id,
            )
        )

    def save_parent(
        self,
        rule_type: str,
        rule_entity_id: int,
        record: ChunkRecord,
        *,
        app_name: str | None = None,
        pattern: str | None = None,
        domain: str | None = None,
        section_name: str = "main",
    ) -> int:
        row = RuleChunk(
            rule_type=rule_type,
            rule_entity_id=rule_entity_id,
            app_name=app_name,
            pattern=pattern,
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
        rule_type: str,
        rule_entity_id: int,
        records: list[ChunkRecord],
        parent_db_ids: dict[int, int],
        embeddings: list[list[float]],
        *,
        app_name: str | None = None,
        pattern: str | None = None,
        domain: str | None = None,
        section_name: str = "main",
    ) -> None:
        for record, vec in zip(records, embeddings, strict=True):
            parent_db_id: int | None = None
            if record.parent_chunk_index is not None:
                parent_db_id = parent_db_ids.get(record.parent_chunk_index)

            self._db.add(RuleChunk(
                rule_type=rule_type,
                rule_entity_id=rule_entity_id,
                app_name=app_name,
                pattern=pattern,
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
            ))

    def commit(self) -> None:
        self._db.commit()

    def rollback(self) -> None:
        self._db.rollback()
