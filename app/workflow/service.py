"""WorkflowIndexingService — chunking + embedding for workflow bodies."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.spec.models import ChunkRecord

logger = logging.getLogger(__name__)


@dataclass
class WorkflowIndexResult:
    ok: bool
    workflow_type: str
    workflow_entity_id: int
    parent_count: int = 0
    child_count: int = 0
    error: str | None = None


class WorkflowIndexingService:
    def __init__(self, strategy, repository, embedding) -> None:
        self._strategy = strategy
        self._repo = repository
        self._embedding = embedding

    def index_workflow(
        self,
        workflow_type: str,
        workflow_entity_id: int,
        body: str,
        *,
        app_name: str | None = None,
        pattern: str | None = None,
        domain: str | None = None,
        section_name: str = "main",
    ) -> WorkflowIndexResult:
        base_meta: dict = {
            "workflow_type": workflow_type,
            "workflow_entity_id": workflow_entity_id,
            "app_name": app_name,
            "pattern": pattern,
            "domain": domain,
            "section_name": section_name,
        }

        records: list[ChunkRecord] = self._strategy.chunk(body, base_meta)
        if not records:
            return WorkflowIndexResult(
                ok=True,
                workflow_type=workflow_type,
                workflow_entity_id=workflow_entity_id,
            )

        parents = [r for r in records if r.chunk_type == "parent"]
        children = [r for r in records if r.chunk_type == "child"]

        if not children:
            return WorkflowIndexResult(
                ok=True,
                workflow_type=workflow_type,
                workflow_entity_id=workflow_entity_id,
                parent_count=len(parents),
            )

        vectors = self._embedding.embed_texts([c.embed_text for c in children])

        self._repo.delete_by_section(
            workflow_type,
            app_name=app_name,
            pattern=pattern,
            section_name=section_name,
        )

        parent_db_ids: dict[int, int] = {}
        for parent in parents:
            db_id = self._repo.save_parent(
                workflow_type,
                workflow_entity_id,
                parent,
                app_name=app_name,
                pattern=pattern,
                domain=domain,
                section_name=section_name,
            )
            parent_db_ids[parent.chunk_index] = db_id

        self._repo.save_children(
            workflow_type,
            workflow_entity_id,
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
            "workflow indexed type=%s id=%s parents=%d children=%d",
            workflow_type,
            workflow_entity_id,
            len(parents),
            len(children),
        )
        return WorkflowIndexResult(
            ok=True,
            workflow_type=workflow_type,
            workflow_entity_id=workflow_entity_id,
            parent_count=len(parents),
            child_count=len(children),
        )


def make_default_workflow_service(db: Session) -> WorkflowIndexingService:
    from app.services.embeddings import embed_texts as _embed
    from app.spec.chunking import HeadingAwareParentChildChunker
    from app.workflow.repository import SqlAlchemyWorkflowChunkRepository

    class _EmbeddingAdapter:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return _embed(texts)

    return WorkflowIndexingService(
        strategy=HeadingAwareParentChildChunker(),
        repository=SqlAlchemyWorkflowChunkRepository(db),
        embedding=_EmbeddingAdapter(),
    )
