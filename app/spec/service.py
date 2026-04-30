"""SpecIndexingService — 청킹 전략·레포지터리·임베딩 포트를 DI 로 조합."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.spec.interfaces import IChunkingStrategy, IEmbeddingPort, ISpecChunkRepository
from app.spec.models import IndexResult

logger = logging.getLogger(__name__)


class SpecIndexingService:
    """기획서 인덱싱 오케스트레이터.

    의존성은 생성자 주입 — 전략·레포지터리·임베딩 엔진 모두 교체 가능.

    실행 순서:
        1. 전략으로 text → ChunkRecord 목록 생성
        2. child 청크 embed_text 를 배치 임베딩 (실패 시 기존 데이터 보존)
        3. 기존 청크 삭제 (임베딩 성공 후)
        4. parent 저장 (flush → id 획득)
        5. child 저장 (parent_db_ids 매핑 포함)
        6. 단일 트랜잭션 commit (삭제+삽입 원자적)
    """

    def __init__(
        self,
        strategy: IChunkingStrategy,
        repository: ISpecChunkRepository,
        embedding: IEmbeddingPort,
    ) -> None:
        self._strategy = strategy
        self._repo = repository
        self._embedding = embedding

    def index(
        self,
        spec_id: int,
        content: str,
        title: str | None,
        app_target: str,
        base_branch: str,
    ) -> IndexResult:
        base_meta: dict = {
            "spec_id": spec_id,
            "spec_title": title,
            "app_target": app_target,
            "base_branch": base_branch,
        }

        # 1. 청킹
        records = self._strategy.chunk(content, base_meta)
        if not records:
            return IndexResult(ok=True, spec_id=spec_id)

        parents = [r for r in records if r.chunk_type == "parent"]
        children = [r for r in records if r.chunk_type == "child"]

        if not children:
            # 극단적으로 빈 문서 등 child 가 없는 경우
            return IndexResult(ok=True, spec_id=spec_id, parent_count=len(parents))

        # 2. 배치 임베딩 — embed 성공 이후에만 DB 변경 (실패 시 기존 청크 보존)
        vectors = self._embedding.embed_texts([c.embed_text for c in children])

        # 3. 기존 청크 삭제 (임베딩 성공 후 삭제 → 장애 시 롤백 가능)
        self._repo.delete_by_spec(spec_id)

        # 4. Parent 저장 (flush → id 획득)
        parent_db_ids: dict[int, int] = {}  # {chunk_index(음수) → db_id}
        for parent in parents:
            db_id = self._repo.save_parent(spec_id, parent)
            parent_db_ids[parent.chunk_index] = db_id

        # 5. Child 저장
        self._repo.save_children(spec_id, children, parent_db_ids, vectors)

        # 6. 단일 트랜잭션으로 삭제+삽입 commit
        self._repo.commit()

        logger.info(
            "spec indexed spec_id=%s parents=%d children=%d",
            spec_id,
            len(parents),
            len(children),
        )
        return IndexResult(
            ok=True,
            spec_id=spec_id,
            parent_count=len(parents),
            child_count=len(children),
        )


# ── 팩토리 ────────────────────────────────────────────────────────────────────


def make_default_service(db: Session) -> SpecIndexingService:
    """기본 구성(HeadingAwareParentChildChunker + Postgres + 로컬 임베딩)으로 서비스 생성."""
    from app.services.embeddings import embed_texts as _embed

    from app.spec.chunking import HeadingAwareParentChildChunker
    from app.spec.repository import SqlAlchemySpecChunkRepository

    class _EmbeddingAdapter:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return _embed(texts)

    return SpecIndexingService(
        strategy=HeadingAwareParentChildChunker(),
        repository=SqlAlchemySpecChunkRepository(db),
        embedding=_EmbeddingAdapter(),
    )
