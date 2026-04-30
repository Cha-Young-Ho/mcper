"""RuleIndexingService — chunking + embedding for rule bodies."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.spec.models import ChunkRecord

logger = logging.getLogger(__name__)


@dataclass
class RuleIndexResult:
    ok: bool
    rule_type: str
    rule_entity_id: int
    parent_count: int = 0
    child_count: int = 0
    error: str | None = None


class RuleIndexingService:
    def __init__(self, strategy, repository, embedding) -> None:
        self._strategy = strategy
        self._repo = repository
        self._embedding = embedding

    def index_rule(
        self,
        rule_type: str,
        rule_entity_id: int,
        body: str,
        *,
        app_name: str | None = None,
        pattern: str | None = None,
        domain: str | None = None,
        section_name: str = "main",
    ) -> RuleIndexResult:
        base_meta: dict = {
            "rule_type": rule_type,
            "rule_entity_id": rule_entity_id,
            "app_name": app_name,
            "pattern": pattern,
            "domain": domain,
            "section_name": section_name,
        }

        records: list[ChunkRecord] = self._strategy.chunk(body, base_meta)
        if not records:
            return RuleIndexResult(
                ok=True, rule_type=rule_type, rule_entity_id=rule_entity_id
            )

        parents = [r for r in records if r.chunk_type == "parent"]
        children = [r for r in records if r.chunk_type == "child"]

        if not children:
            return RuleIndexResult(
                ok=True,
                rule_type=rule_type,
                rule_entity_id=rule_entity_id,
                parent_count=len(parents),
            )

        vectors = self._embedding.embed_texts([c.embed_text for c in children])

        self._repo.delete_by_section(
            rule_type,
            app_name=app_name,
            pattern=pattern,
            section_name=section_name,
        )

        parent_db_ids: dict[int, int] = {}
        for parent in parents:
            db_id = self._repo.save_parent(
                rule_type,
                rule_entity_id,
                parent,
                app_name=app_name,
                pattern=pattern,
                domain=domain,
                section_name=section_name,
            )
            parent_db_ids[parent.chunk_index] = db_id

        self._repo.save_children(
            rule_type,
            rule_entity_id,
            children,
            parent_db_ids,
            vectors,
            app_name=app_name,
            pattern=pattern,
            domain=domain,
            section_name=section_name,
        )

        self._repo.commit()

        logger.info(
            "rule indexed type=%s id=%s parents=%d children=%d",
            rule_type,
            rule_entity_id,
            len(parents),
            len(children),
        )
        return RuleIndexResult(
            ok=True,
            rule_type=rule_type,
            rule_entity_id=rule_entity_id,
            parent_count=len(parents),
            child_count=len(children),
        )


def make_default_rule_service(db: Session) -> RuleIndexingService:
    from app.services.embeddings import embed_texts as _embed
    from app.spec.chunking import HeadingAwareParentChildChunker
    from app.rule.repository import SqlAlchemyRuleChunkRepository

    class _EmbeddingAdapter:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return _embed(texts)

    return RuleIndexingService(
        strategy=HeadingAwareParentChildChunker(),
        repository=SqlAlchemyRuleChunkRepository(db),
        embedding=_EmbeddingAdapter(),
    )
