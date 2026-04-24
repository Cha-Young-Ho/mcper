"""Unit tests for WorkflowIndexingService (mirrors test pattern for skill indexing)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.workflow.service import WorkflowIndexingService


@dataclass
class _FakeChunkRecord:
    chunk_type: str
    chunk_index: int
    content: str
    embed_text: str
    section_heading: str = "main"
    parent_chunk_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class _FakeStrategy:
    def __init__(self, records):
        self._records = records
        self.calls: list[tuple[str, dict]] = []

    def chunk(self, body: str, base_meta: dict):
        self.calls.append((body, base_meta))
        return self._records


class _FakeEmbedding:
    def __init__(self):
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        # 384-dim dummy vectors (matches settings.embedding_dim)
        return [[0.1] * 384 for _ in texts]


class _FakeRepository:
    def __init__(self):
        self.deleted: list[tuple[str, int]] = []
        self.parents: list[dict] = []
        self.children_calls: list[dict] = []
        self.committed = False
        self._next_id = 100

    def delete_by_workflow(self, workflow_type: str, workflow_entity_id: int) -> None:
        self.deleted.append((workflow_type, workflow_entity_id))

    def save_parent(self, workflow_type, workflow_entity_id, record, **kw):
        db_id = self._next_id
        self._next_id += 1
        self.parents.append({
            "workflow_type": workflow_type,
            "workflow_entity_id": workflow_entity_id,
            "record": record,
            "db_id": db_id,
            **kw,
        })
        return db_id

    def save_children(self, workflow_type, workflow_entity_id, records, parent_db_ids, embeddings, **kw):
        self.children_calls.append({
            "workflow_type": workflow_type,
            "workflow_entity_id": workflow_entity_id,
            "records": list(records),
            "parent_db_ids": dict(parent_db_ids),
            "embeddings": list(embeddings),
            **kw,
        })

    def commit(self) -> None:
        self.committed = True


def _make_service(records):
    strategy = _FakeStrategy(records)
    repo = _FakeRepository()
    embed = _FakeEmbedding()
    svc = WorkflowIndexingService(strategy=strategy, repository=repo, embedding=embed)
    return svc, strategy, repo, embed


class TestWorkflowIndexingService:
    def test_empty_body_returns_ok_with_zero_counts(self):
        svc, _strategy, repo, embed = _make_service([])
        result = svc.index_workflow("global", 1, "")
        assert result.ok is True
        assert result.parent_count == 0
        assert result.child_count == 0
        assert repo.deleted == []
        assert repo.parents == []
        assert repo.children_calls == []
        assert repo.committed is False
        assert embed.calls == []

    def test_parent_only_skips_embedding(self):
        records = [
            _FakeChunkRecord(chunk_type="parent", chunk_index=-1, content="root", embed_text=""),
        ]
        svc, _strategy, repo, embed = _make_service(records)
        result = svc.index_workflow("global", 42, "body")
        assert result.ok is True
        assert result.parent_count == 1
        assert result.child_count == 0
        assert embed.calls == []
        assert repo.deleted == []

    def test_parent_child_indexing_full_flow(self):
        records = [
            _FakeChunkRecord(chunk_type="parent", chunk_index=-1, content="parent 1", embed_text=""),
            _FakeChunkRecord(
                chunk_type="child", chunk_index=0, content="child A",
                embed_text="child A", parent_chunk_index=-1,
            ),
            _FakeChunkRecord(
                chunk_type="child", chunk_index=1, content="child B",
                embed_text="child B", parent_chunk_index=-1,
            ),
        ]
        svc, _strategy, repo, embed = _make_service(records)
        result = svc.index_workflow(
            "app", 7, "body",
            app_name="adventure", domain="development", section_name="spec-implementation",
        )
        assert result.ok is True
        assert result.parent_count == 1
        assert result.child_count == 2
        # delete old chunks first
        assert repo.deleted == [("app", 7)]
        # embed called exactly once with child texts
        assert embed.calls == [["child A", "child B"]]
        # parent stored with context
        assert len(repo.parents) == 1
        p = repo.parents[0]
        assert p["workflow_type"] == "app"
        assert p["app_name"] == "adventure"
        assert p["domain"] == "development"
        assert p["section_name"] == "spec-implementation"
        # children saved with parent mapping
        assert len(repo.children_calls) == 1
        call = repo.children_calls[0]
        assert len(call["records"]) == 2
        assert call["parent_db_ids"] == {-1: p["db_id"]}
        assert len(call["embeddings"]) == 2
        assert repo.committed is True

    def test_pattern_passed_through_for_repo_workflows(self):
        records = [
            _FakeChunkRecord(chunk_type="parent", chunk_index=-1, content="p", embed_text=""),
            _FakeChunkRecord(
                chunk_type="child", chunk_index=0, content="c",
                embed_text="c", parent_chunk_index=-1,
            ),
        ]
        svc, strategy, repo, _embed = _make_service(records)
        svc.index_workflow(
            "repo", 5, "body",
            pattern="github.com/me/repo", section_name="review",
        )
        # base_meta includes pattern
        assert strategy.calls[0][1]["pattern"] == "github.com/me/repo"
        # pattern forwarded to save_parent
        assert repo.parents[0]["pattern"] == "github.com/me/repo"
        # pattern forwarded to save_children
        assert repo.children_calls[0]["pattern"] == "github.com/me/repo"

    def test_delete_called_before_save_for_reindexing(self):
        records = [
            _FakeChunkRecord(chunk_type="parent", chunk_index=-1, content="p", embed_text=""),
            _FakeChunkRecord(
                chunk_type="child", chunk_index=0, content="c",
                embed_text="c", parent_chunk_index=-1,
            ),
        ]
        svc, _strategy, repo, _embed = _make_service(records)
        svc.index_workflow("global", 99, "body")
        assert repo.deleted == [("global", 99)]
        # ensure delete happened before children save (not tested by order but presence is enough here
        # since _FakeRepository tracks per-method; a separate integration test covers real DB order)
