"""Integration tests for workflow vectorization: publish hooks + hybrid search."""

from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.rag_models import WorkflowChunk
from app.db.workflow_models import (
    AppWorkflowVersion,
    GlobalWorkflowVersion,
    RepoWorkflowVersion,
)
from app.services.versioned_workflows import (
    publish_app_workflow,
    publish_global_workflow,
    publish_repo_workflow,
    search_workflows,
)


SAMPLE_BODY = """# 기획서 구현 워크플로우

## 1. 분석

기획서를 분석하고 범위를 파악합니다.

## 2. 구현

코드를 작성하고 테스트를 수행합니다.
"""


def _cleanup(db: Session):
    db.execute(delete(WorkflowChunk))
    db.execute(delete(GlobalWorkflowVersion))
    db.execute(delete(AppWorkflowVersion))
    db.execute(delete(RepoWorkflowVersion))
    db.commit()


@pytest.mark.integration
class TestPublishIndexingHook:
    """Publishing a workflow must create workflow_chunks rows."""

    def test_publish_global_creates_chunks(self, db_session: Session):
        _cleanup(db_session)
        try:
            publish_global_workflow(db_session, SAMPLE_BODY, section_name="spec-implementation")
            chunks = db_session.query(WorkflowChunk).filter_by(workflow_type="global").all()
            assert len(chunks) > 0, "publish_global_workflow should create workflow_chunks"
            # child chunks (embedding target) must exist; parent chunks are optional for short bodies
            assert any(c.chunk_type == "child" for c in chunks)
        finally:
            _cleanup(db_session)

    def test_publish_app_creates_chunks_with_app_name(self, db_session: Session):
        _cleanup(db_session)
        try:
            publish_app_workflow(db_session, "testapp", SAMPLE_BODY, section_name="main")
            chunks = db_session.query(WorkflowChunk).filter_by(workflow_type="app").all()
            assert len(chunks) > 0
            assert all(c.app_name == "testapp" for c in chunks)
        finally:
            _cleanup(db_session)

    def test_publish_repo_creates_chunks_with_pattern(self, db_session: Session):
        _cleanup(db_session)
        try:
            publish_repo_workflow(
                db_session, "github.com/org/repo", SAMPLE_BODY, section_name="review",
            )
            chunks = db_session.query(WorkflowChunk).filter_by(workflow_type="repo").all()
            assert len(chunks) > 0
            assert all(c.pattern == "github.com/org/repo" for c in chunks)
        finally:
            _cleanup(db_session)

    def test_republish_replaces_old_chunks(self, db_session: Session):
        _cleanup(db_session)
        try:
            # first publish → entity_id A, chunks for A
            publish_global_workflow(db_session, SAMPLE_BODY, section_name="s1")
            first_ids = {r.id for r in db_session.query(GlobalWorkflowVersion).all()}
            chunks_a = db_session.query(WorkflowChunk).filter(
                WorkflowChunk.workflow_entity_id.in_(first_ids)
            ).count()
            assert chunks_a > 0

            # second publish → new entity_id B (version bump), chunks for B
            publish_global_workflow(db_session, SAMPLE_BODY + "\n\n추가 내용\n", section_name="s1")
            all_ids = {r.id for r in db_session.query(GlobalWorkflowVersion).all()}
            new_ids = all_ids - first_ids
            assert len(new_ids) == 1
            chunks_b = db_session.query(WorkflowChunk).filter(
                WorkflowChunk.workflow_entity_id.in_(new_ids)
            ).count()
            assert chunks_b > 0
        finally:
            _cleanup(db_session)


@pytest.mark.integration
class TestSearchWorkflows:
    """search_workflows() goes through hybrid search with legacy fallback."""

    def test_search_returns_legacy_shape(self, db_session: Session):
        _cleanup(db_session)
        try:
            publish_global_workflow(db_session, SAMPLE_BODY, section_name="spec-implementation")
            results = search_workflows(db_session, query="기획서", scope="global", top_n=5)
            assert isinstance(results, list)
            if results:  # hybrid may match or fall back
                r = results[0]
                assert "scope" in r
                assert "section_name" in r
                assert "version" in r
                assert "body" in r
        finally:
            _cleanup(db_session)

    def test_search_empty_query_returns_empty(self, db_session: Session):
        assert search_workflows(db_session, query="") == []
        assert search_workflows(db_session, query="   ") == []

    def test_search_scope_filter_app(self, db_session: Session):
        _cleanup(db_session)
        try:
            publish_global_workflow(db_session, SAMPLE_BODY, section_name="g1")
            publish_app_workflow(db_session, "myapp", SAMPLE_BODY, section_name="a1")
            results = search_workflows(
                db_session, query="구현", app_name="myapp", scope="app", top_n=10,
            )
            for r in results:
                assert r["scope"] == "app"
                assert r["app_name"] == "myapp"
        finally:
            _cleanup(db_session)

    def test_search_fallback_when_no_chunks(self, db_session: Session):
        """Publish inserts both the version row and chunks, but wipe chunks to simulate
        pre-migration state. search_workflows must still find matches via ILIKE fallback."""
        _cleanup(db_session)
        try:
            publish_global_workflow(db_session, SAMPLE_BODY, section_name="spec-implementation")
            # wipe chunks but keep version row
            db_session.execute(delete(WorkflowChunk))
            db_session.commit()

            results = search_workflows(db_session, query="기획서", scope="global", top_n=5)
            # legacy ILIKE path should still return hits since body contains "기획서"
            assert any(r["scope"] == "global" for r in results)
        finally:
            _cleanup(db_session)
