"""SkillIndexingService — chunking + embedding for skill bodies."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.spec.models import ChunkRecord

logger = logging.getLogger(__name__)


@dataclass
class SkillIndexResult:
    ok: bool
    skill_type: str
    skill_entity_id: int
    parent_count: int = 0
    child_count: int = 0
    error: str | None = None


class SkillIndexingService:
    """Skill body indexing orchestrator.

    Mirrors SpecIndexingService but targets skill_chunks table.
    """

    def __init__(self, strategy, repository, embedding) -> None:
        self._strategy = strategy
        self._repo = repository
        self._embedding = embedding

    def index_skill(
        self,
        skill_type: str,
        skill_entity_id: int,
        body: str,
        *,
        app_name: str | None = None,
        domain: str | None = None,
        section_name: str = "main",
    ) -> SkillIndexResult:
        base_meta: dict = {
            "skill_type": skill_type,
            "skill_entity_id": skill_entity_id,
            "app_name": app_name,
            "domain": domain,
            "section_name": section_name,
        }

        records: list[ChunkRecord] = self._strategy.chunk(body, base_meta)
        if not records:
            return SkillIndexResult(
                ok=True, skill_type=skill_type, skill_entity_id=skill_entity_id
            )

        parents = [r for r in records if r.chunk_type == "parent"]
        children = [r for r in records if r.chunk_type == "child"]

        if not children:
            return SkillIndexResult(
                ok=True,
                skill_type=skill_type,
                skill_entity_id=skill_entity_id,
                parent_count=len(parents),
            )

        vectors = self._embedding.embed_texts([c.embed_text for c in children])

        self._repo.delete_by_section(
            skill_type,
            app_name=app_name,
            section_name=section_name,
        )

        parent_db_ids: dict[int, int] = {}
        for parent in parents:
            db_id = self._repo.save_parent(
                skill_type,
                skill_entity_id,
                parent,
                app_name=app_name,
                domain=domain,
                section_name=section_name,
            )
            parent_db_ids[parent.chunk_index] = db_id

        self._repo.save_children(
            skill_type,
            skill_entity_id,
            children,
            parent_db_ids,
            vectors,
            app_name=app_name,
            domain=domain,
            section_name=section_name,
        )

        self._repo.commit()

        logger.info(
            "skill indexed type=%s id=%s parents=%d children=%d",
            skill_type,
            skill_entity_id,
            len(parents),
            len(children),
        )
        return SkillIndexResult(
            ok=True,
            skill_type=skill_type,
            skill_entity_id=skill_entity_id,
            parent_count=len(parents),
            child_count=len(children),
        )


def make_default_skill_service(db: Session) -> SkillIndexingService:
    """Factory: HeadingAwareParentChildChunker + Postgres + local embedding."""
    from app.services.embeddings import embed_texts as _embed
    from app.spec.chunking import HeadingAwareParentChildChunker
    from app.skill.repository import SqlAlchemySkillChunkRepository

    class _EmbeddingAdapter:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return _embed(texts)

    return SkillIndexingService(
        strategy=HeadingAwareParentChildChunker(),
        repository=SqlAlchemySkillChunkRepository(db),
        embedding=_EmbeddingAdapter(),
    )
