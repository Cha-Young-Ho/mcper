"""Unit tests for SqlAlchemyWorkflowChunkRepository — 100% line coverage.

DB는 MagicMock으로 스텁. SQLAlchemy statement objects는 실제로 실행되지 않고,
세션에 전달된 인자 확인으로 동작을 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.db.rag_models import WorkflowChunk
from app.workflow.repository import SqlAlchemyWorkflowChunkRepository


@dataclass
class _FakeRecord:
    chunk_index: int
    content: str
    section_heading: str = "main"
    parent_chunk_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _extract_row_from_add(mock_session: MagicMock, index: int = -1) -> WorkflowChunk:
    """Extract the WorkflowChunk instance that was passed to db.add()."""
    call_args = mock_session.add.call_args_list[index]
    return call_args[0][0]


class TestDeleteBySection:
    def test_delete_issues_execute(self):
        db = MagicMock()
        repo = SqlAlchemyWorkflowChunkRepository(db)
        repo.delete_by_section(
            "app",
            app_name="myapp",
            pattern=None,
            section_name="main",
        )
        assert db.execute.called
        assert db.execute.call_count == 1

    def test_delete_with_null_app_name_and_pattern(self):
        """global workflows have app_name=None, pattern=None — must render IS NULL."""
        from app.workflow.repository import _eq_or_null
        from app.db.rag_models import WorkflowChunk

        # _eq_or_null returns an IS NULL clause for None
        clause_null = _eq_or_null(WorkflowChunk.app_name, None)
        clause_eq = _eq_or_null(WorkflowChunk.app_name, "x")
        # compile to SQL text to verify IS NULL vs =
        assert "IS NULL" in str(
            clause_null.compile(compile_kwargs={"literal_binds": True})
        )
        assert "=" in str(clause_eq.compile(compile_kwargs={"literal_binds": True}))

    def test_delete_all_three_scopes(self):
        db = MagicMock()
        repo = SqlAlchemyWorkflowChunkRepository(db)
        # global
        repo.delete_by_section(
            "global", app_name=None, pattern=None, section_name="main"
        )
        # app
        repo.delete_by_section(
            "app", app_name="adventure", pattern=None, section_name="main"
        )
        # repo
        repo.delete_by_section(
            "repo", app_name=None, pattern="gh.com/x", section_name="s"
        )
        assert db.execute.call_count == 3


class TestSaveParent:
    def test_save_parent_adds_row_and_returns_id(self):
        db = MagicMock()

        def _flush_side_effect():
            # simulate DB assigning a primary key after flush
            added = db.add.call_args[0][0]
            added.id = 777

        db.flush.side_effect = _flush_side_effect

        repo = SqlAlchemyWorkflowChunkRepository(db)
        record = _FakeRecord(
            chunk_index=-1,
            content="parent content",
            section_heading="Section X",
            metadata={"src": "test"},
        )
        returned_id = repo.save_parent(
            "global",
            1,
            record,
            app_name="myapp",
            pattern="pat",
            domain="dev",
            section_name="main",
        )
        assert returned_id == 777
        assert db.add.called
        assert db.flush.called

        row = _extract_row_from_add(db)
        assert row.workflow_type == "global"
        assert row.workflow_entity_id == 1
        assert row.app_name == "myapp"
        assert row.pattern == "pat"
        assert row.domain == "dev"
        assert row.section_name == "main"
        assert row.chunk_index == -1
        assert row.content == "parent content"
        assert row.embedding is None
        assert row.chunk_type == "parent"
        assert row.parent_chunk_id is None
        # metadata must include chunk_type and section_heading + original keys
        assert row.chunk_metadata["chunk_type"] == "parent"
        assert row.chunk_metadata["section_heading"] == "Section X"
        assert row.chunk_metadata["src"] == "test"

    def test_save_parent_defaults(self):
        """Default kwargs: app_name/pattern/domain=None, section_name='main'."""
        db = MagicMock()

        def _flush():
            db.add.call_args[0][0].id = 1

        db.flush.side_effect = _flush
        repo = SqlAlchemyWorkflowChunkRepository(db)
        record = _FakeRecord(chunk_index=-1, content="p")
        repo.save_parent("repo", 5, record)
        row = _extract_row_from_add(db)
        assert row.app_name is None
        assert row.pattern is None
        assert row.domain is None
        assert row.section_name == "main"


class TestSaveChildren:
    def test_save_children_maps_parent_and_embedding(self):
        db = MagicMock()
        repo = SqlAlchemyWorkflowChunkRepository(db)

        records = [
            _FakeRecord(
                chunk_index=0, content="c0", parent_chunk_index=-1, metadata={"k": 1}
            ),
            _FakeRecord(chunk_index=1, content="c1", parent_chunk_index=-1),
            _FakeRecord(
                chunk_index=2, content="c2", parent_chunk_index=None
            ),  # no parent
        ]
        parent_db_ids = {-1: 100}
        embeddings = [[0.1] * 384, [0.2] * 384, [0.3] * 384]

        repo.save_children(
            "app",
            7,
            records,
            parent_db_ids,
            embeddings,
            app_name="myapp",
            pattern=None,
            domain="dev",
            section_name="sec",
        )

        assert db.add.call_count == 3

        row0 = _extract_row_from_add(db, 0)
        _ = _extract_row_from_add(db, 1)
        row2 = _extract_row_from_add(db, 2)

        # row0: parent mapped
        assert row0.parent_chunk_id == 100
        assert row0.chunk_type == "child"
        assert row0.content == "c0"
        assert row0.workflow_type == "app"
        assert row0.workflow_entity_id == 7
        assert row0.app_name == "myapp"
        assert row0.domain == "dev"
        assert row0.section_name == "sec"
        assert row0.embedding == [0.1] * 384
        # metadata merged
        assert row0.chunk_metadata["k"] == 1
        assert row0.chunk_metadata["chunk_type"] == "child"
        assert row0.chunk_metadata["chunk_index"] == 0

        # row2: no parent index → parent_chunk_id stays None
        assert row2.parent_chunk_id is None
        assert row2.embedding == [0.3] * 384

    def test_save_children_parent_index_missing_in_map(self):
        """If parent_chunk_index points to an unknown key, parent_chunk_id = None."""
        db = MagicMock()
        repo = SqlAlchemyWorkflowChunkRepository(db)
        records = [
            _FakeRecord(chunk_index=0, content="x", parent_chunk_index=99),
        ]
        parent_db_ids = {-1: 100}  # 99 not present
        embeddings = [[0.5] * 384]
        repo.save_children("global", 1, records, parent_db_ids, embeddings)
        row = _extract_row_from_add(db)
        assert row.parent_chunk_id is None

    def test_save_children_defaults(self):
        """Default kwargs path."""
        db = MagicMock()
        repo = SqlAlchemyWorkflowChunkRepository(db)
        records = [_FakeRecord(chunk_index=0, content="x")]
        repo.save_children("global", 1, records, {}, [[0.0] * 384])
        row = _extract_row_from_add(db)
        assert row.app_name is None
        assert row.pattern is None
        assert row.domain is None
        assert row.section_name == "main"

    def test_save_children_length_mismatch_raises(self):
        """strict=True in zip should raise when records and embeddings differ."""
        db = MagicMock()
        repo = SqlAlchemyWorkflowChunkRepository(db)
        records = [
            _FakeRecord(chunk_index=0, content="a"),
            _FakeRecord(chunk_index=1, content="b"),
        ]
        embeddings = [[0.0] * 384]  # only 1 embedding for 2 records
        with pytest.raises(ValueError):
            repo.save_children("global", 1, records, {}, embeddings)


class TestCommitRollback:
    def test_commit_delegates_to_session(self):
        db = MagicMock()
        SqlAlchemyWorkflowChunkRepository(db).commit()
        db.commit.assert_called_once()

    def test_rollback_delegates_to_session(self):
        db = MagicMock()
        SqlAlchemyWorkflowChunkRepository(db).rollback()
        db.rollback.assert_called_once()
