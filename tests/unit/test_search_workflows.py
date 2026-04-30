"""Unit tests for app.services.search_workflows — 100% line coverage.

DB는 MagicMock으로 스텁. SQLAlchemy 객체들은 실행되지 않고,
db.scalars/db.scalar 반환값을 제어해 각 분기를 커버한다.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from app.services import search_workflows as sw


def _make_scalars_mock(return_list):
    """Create a mock where .scalars(...).all() returns the given list."""
    scalars_ret = MagicMock()
    scalars_ret.all.return_value = return_list
    return scalars_ret


def _db_with_scalars_queue(queue_of_lists):
    """Mock db whose .scalars(stmt) returns values from a queue, each supporting .all()."""
    db = MagicMock()
    db.scalars.side_effect = [_make_scalars_mock(lst) for lst in queue_of_lists]
    return db


class TestWorkflowChunkVectorIds:
    def test_returns_list_from_scalars(self):
        db = _db_with_scalars_queue([[1, 2, 3]])
        result = sw.workflow_chunk_vector_ids(
            db,
            query_embedding=[0.1] * 384,
            workflow_type="global",
            app_name="a",
            pattern="p",
            limit=10,
        )
        assert result == [1, 2, 3]

    def test_no_filters(self):
        db = _db_with_scalars_queue([[]])
        result = sw.workflow_chunk_vector_ids(db, query_embedding=[0.0] * 384)
        assert result == []


class TestWorkflowChunkFtsIds:
    def test_empty_query_returns_empty(self):
        db = MagicMock()
        assert sw.workflow_chunk_fts_ids(db, query="") == []
        assert sw.workflow_chunk_fts_ids(db, query="   ") == []
        db.scalars.assert_not_called()

    def test_valid_query_returns_ids(self):
        db = _db_with_scalars_queue([[10, 20]])
        result = sw.workflow_chunk_fts_ids(
            db,
            query="foo",
            workflow_type="app",
            app_name="myapp",
            pattern="pat",
            limit=5,
        )
        assert result == [10, 20]

    def test_exception_returns_empty_and_logs(self, caplog):
        db = MagicMock()
        db.scalars.side_effect = RuntimeError("tsvector missing")
        with caplog.at_level("WARNING"):
            result = sw.workflow_chunk_fts_ids(db, query="hello")
        assert result == []
        assert any("FTS workflow_chunks failed" in r.message for r in caplog.records)


class TestHybridWorkflowSearch:
    def test_no_chunks_returns_no_index(self):
        db = MagicMock()
        db.scalar.return_value = 0  # count = 0
        results, mode = sw.hybrid_workflow_search(db, query="q")
        assert results == []
        assert mode == "no_index"

    def test_embed_failure_uses_fts_only_and_returns_results(self):
        """embed_query raises → falls back to FTS only → has hits → hybrid_ok path."""
        db = MagicMock()
        db.scalar.return_value = 1  # count > 0

        # Prepare .scalars() calls:
        # 1st: workflow_chunk_fts_ids internal scalars → [5]
        # 2nd: final "ordered" rows fetch → [ch]
        # 3rd: parent fetch → [parent]
        child_chunk = SimpleNamespace(
            id=5,
            workflow_type="global",
            workflow_entity_id=1,
            app_name=None,
            pattern=None,
            section_name="main",
            chunk_index=0,
            content="body",
            parent_chunk_id=99,
            chunk_metadata={"k": "v"},
        )
        parent_chunk = SimpleNamespace(
            id=99,
            content="parent body",
        )
        db.scalars.side_effect = [
            _make_scalars_mock([5]),  # FTS ids
            _make_scalars_mock([child_chunk]),  # fetch ordered rows
            _make_scalars_mock([parent_chunk]),  # fetch parents
        ]

        with patch.object(sw, "embed_query", side_effect=RuntimeError("embed failed")):
            results, mode = sw.hybrid_workflow_search(
                db, query="q", scope="global", top_n=3
            )

        assert mode == "hybrid_ok"
        assert len(results) == 1
        r = results[0]
        assert r["chunk_id"] == 5
        assert r["workflow_type"] == "global"
        assert r["parent_content"] == "parent body"
        assert r["metadata"] == {"k": "v"}

    def test_embed_failure_fts_empty_returns_indexed_no_match(self):
        db = MagicMock()
        db.scalar.return_value = 1
        db.scalars.side_effect = [_make_scalars_mock([])]  # FTS returns nothing
        with patch.object(sw, "embed_query", side_effect=RuntimeError("x")):
            results, mode = sw.hybrid_workflow_search(db, query="q")
        assert results == []
        assert mode == "indexed_no_match"

    def test_hybrid_happy_path_combines_vector_and_fts(self):
        db = MagicMock()
        db.scalar.return_value = 5

        child = SimpleNamespace(
            id=1,
            workflow_type="app",
            workflow_entity_id=10,
            app_name="my",
            pattern=None,
            section_name="sec",
            chunk_index=0,
            content="c",
            parent_chunk_id=None,
            chunk_metadata={},
        )
        # calls in order:
        #   vector_ids: [1]
        #   fts_ids:    [2]
        #   ordered rows fetch: [child]
        #   (no parents because parent_chunk_id is None → no parents fetch)
        db.scalars.side_effect = [
            _make_scalars_mock([1]),
            _make_scalars_mock([2]),
            _make_scalars_mock([child]),
        ]

        with (
            patch.object(sw, "embed_query", return_value=[0.5] * 384),
            patch.object(sw, "reciprocal_rank_fusion", return_value=[1]),
        ):
            results, mode = sw.hybrid_workflow_search(
                db,
                query="q",
                app_name="my",
                scope="app",
                top_n=5,
            )
        assert mode == "hybrid_ok"
        assert len(results) == 1
        assert results[0]["parent_content"] is None

    def test_hybrid_ranked_empty_returns_indexed_no_match(self):
        db = MagicMock()
        db.scalar.return_value = 5
        db.scalars.side_effect = [
            _make_scalars_mock([]),  # vector ids
            _make_scalars_mock([]),  # fts ids
        ]
        with (
            patch.object(sw, "embed_query", return_value=[0.1] * 384),
            patch.object(sw, "reciprocal_rank_fusion", return_value=[]),
        ):
            results, mode = sw.hybrid_workflow_search(db, query="q")
        assert results == []
        assert mode == "indexed_no_match"

    def test_scope_all_no_type_filter(self):
        """scope='all' should not set workflow_type_filter (no KeyError etc)."""
        db = MagicMock()
        db.scalar.return_value = 0  # quickly returns no_index
        results, mode = sw.hybrid_workflow_search(db, query="q", scope="all")
        assert mode == "no_index"

    def test_pattern_filter_propagates(self):
        """pattern=... must be forwarded to the count query (smoke test via no_index)."""
        db = MagicMock()
        db.scalar.return_value = 0
        results, mode = sw.hybrid_workflow_search(
            db,
            query="q",
            pattern="github.com/org",
            scope="repo",
        )
        assert mode == "no_index"

    def test_by_id_filters_rows_not_in_ranked(self):
        """If DB returns fewer rows than ranked ids, loop skips missing keys."""
        db = MagicMock()
        db.scalar.return_value = 2

        child = SimpleNamespace(
            id=1,
            workflow_type="global",
            workflow_entity_id=1,
            app_name=None,
            pattern=None,
            section_name="main",
            chunk_index=0,
            content="c",
            parent_chunk_id=None,
            chunk_metadata={},
        )
        db.scalars.side_effect = [
            _make_scalars_mock([1, 2]),  # vector
            _make_scalars_mock([]),  # fts
            _make_scalars_mock([child]),  # only id=1 returned even though ranked=[1,2]
        ]
        with (
            patch.object(sw, "embed_query", return_value=[0.0] * 384),
            patch.object(sw, "reciprocal_rank_fusion", return_value=[1, 2]),
        ):
            results, mode = sw.hybrid_workflow_search(db, query="q")
        assert mode == "hybrid_ok"
        assert len(results) == 1
        assert results[0]["chunk_id"] == 1
