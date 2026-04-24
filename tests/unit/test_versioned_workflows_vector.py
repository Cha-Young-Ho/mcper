"""Unit tests for versioned_workflows new functions added by vectorization feature:

- _try_index_workflow (best-effort wrapper)
- _legacy_ilike_search_workflows (fallback)
- _enrich_chunks_with_version_rows (chunk→legacy shape adapter)
- search_workflows (hybrid + fallback orchestrator)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import versioned_workflows as vw


class TestTryIndexWorkflow:
    def test_success_path_calls_index_workflow(self):
        db = MagicMock()
        fake_svc = MagicMock()
        with patch("app.workflow.service.make_default_workflow_service", return_value=fake_svc):
            vw._try_index_workflow(
                db, "global", 1, "body",
                app_name="a", pattern="p", domain="d", section_name="sn",
            )
        fake_svc.index_workflow.assert_called_once_with(
            workflow_type="global", workflow_entity_id=1, body="body",
            app_name="a", pattern="p", domain="d", section_name="sn",
        )

    def test_failure_is_swallowed_and_logged(self, caplog):
        db = MagicMock()
        with patch(
            "app.workflow.service.make_default_workflow_service",
            side_effect=RuntimeError("boom"),
        ):
            with caplog.at_level("WARNING"):
                # must NOT raise
                vw._try_index_workflow(db, "app", 5, "body")
        assert any("workflow indexing failed" in r.message for r in caplog.records)


class TestLegacyIlikeSearchWorkflows:
    def test_empty_query_returns_empty(self):
        db = MagicMock()
        assert vw._legacy_ilike_search_workflows(db, "", None, "all", 10) == []
        assert vw._legacy_ilike_search_workflows(db, "   ", None, "all", 10) == []

    def test_global_scope_returns_rows(self):
        db = MagicMock()
        row = SimpleNamespace(
            section_name="main", version=1, body="# hi", domain=None,
        )
        scalars = MagicMock()
        scalars.all.return_value = [row]
        db.scalars.return_value = scalars

        results = vw._legacy_ilike_search_workflows(db, "hi", None, "global", 10)
        assert len(results) == 1
        assert results[0]["scope"] == "global"
        assert results[0]["body"] == "# hi"

    def test_app_scope_without_app_name_skips_app(self):
        """app_name=None → app branch skipped, but all others still run."""
        db = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        db.scalars.return_value = scalars
        # scope='all' without app_name should touch global + repo, not app
        results = vw._legacy_ilike_search_workflows(db, "q", None, "all", 10)
        assert results == []

    def test_app_scope_with_app_name_queries_app(self):
        db = MagicMock()
        app_row = SimpleNamespace(
            app_name="myapp", section_name="sec", version=2, body="b", domain="dev",
        )
        scalars = MagicMock()
        scalars.all.return_value = [app_row]
        db.scalars.return_value = scalars

        results = vw._legacy_ilike_search_workflows(db, "q", "myapp", "app", 10)
        assert len(results) == 1
        assert results[0]["scope"] == "app"
        assert results[0]["app_name"] == "myapp"

    def test_repo_scope_returns_repo_rows(self):
        db = MagicMock()
        repo_row = SimpleNamespace(
            pattern="gh.com/x", section_name="s", version=3, body="bd", domain=None,
        )
        scalars = MagicMock()
        scalars.all.return_value = [repo_row]
        db.scalars.return_value = scalars

        results = vw._legacy_ilike_search_workflows(db, "q", None, "repo", 10)
        assert len(results) == 1
        assert results[0]["scope"] == "repo"
        assert results[0]["pattern"] == "gh.com/x"

    def test_top_n_limits_results(self):
        db = MagicMock()
        # scope='all' calls global+repo (no app without app_name)
        global_rows = [
            SimpleNamespace(section_name=f"g{i}", version=1, body="b", domain=None)
            for i in range(3)
        ]
        repo_rows = [
            SimpleNamespace(pattern="p", section_name=f"r{i}", version=1, body="b", domain=None)
            for i in range(3)
        ]
        scalars_global = MagicMock()
        scalars_global.all.return_value = global_rows
        scalars_repo = MagicMock()
        scalars_repo.all.return_value = repo_rows
        db.scalars.side_effect = [scalars_global, scalars_repo]

        results = vw._legacy_ilike_search_workflows(db, "q", None, "all", 3)
        # top_n=3 → trimmed even though 6 matched
        assert len(results) == 3


class TestEnrichChunksWithVersionRows:
    def test_global_chunk_enriched(self):
        db = MagicMock()
        row = SimpleNamespace(section_name="main", version=1, body="B", domain=None)
        with patch.object(vw, "_global_workflow_latest", return_value=row):
            out = vw._enrich_chunks_with_version_rows(db, [
                {"workflow_type": "global", "section_name": "main", "app_name": None, "pattern": None},
            ])
        assert out == [{
            "scope": "global", "section_name": "main",
            "version": 1, "body": "B", "domain": None,
        }]

    def test_app_chunk_enriched(self):
        db = MagicMock()
        row = SimpleNamespace(
            app_name="a", section_name="s", version=2, body="b", domain="d",
        )
        with patch.object(vw, "_app_workflow_latest", return_value=row):
            out = vw._enrich_chunks_with_version_rows(db, [
                {"workflow_type": "app", "section_name": "s", "app_name": "a", "pattern": None},
            ])
        assert out[0]["scope"] == "app"
        assert out[0]["app_name"] == "a"
        assert out[0]["version"] == 2

    def test_repo_chunk_enriched(self):
        db = MagicMock()
        row = SimpleNamespace(pattern="p", section_name="s", version=3, body="b", domain=None)
        with patch.object(vw, "_repo_workflow_latest", return_value=row):
            out = vw._enrich_chunks_with_version_rows(db, [
                {"workflow_type": "repo", "section_name": "s", "app_name": None, "pattern": "p"},
            ])
        assert out[0]["scope"] == "repo"
        assert out[0]["pattern"] == "p"

    def test_duplicate_chunks_deduped(self):
        db = MagicMock()
        row = SimpleNamespace(section_name="main", version=1, body="B", domain=None)
        with patch.object(vw, "_global_workflow_latest", return_value=row) as m:
            out = vw._enrich_chunks_with_version_rows(db, [
                {"workflow_type": "global", "section_name": "main", "app_name": None, "pattern": None},
                {"workflow_type": "global", "section_name": "main", "app_name": None, "pattern": None},
            ])
        assert len(out) == 1
        m.assert_called_once()

    def test_missing_version_row_skipped(self):
        db = MagicMock()
        with patch.object(vw, "_global_workflow_latest", return_value=None):
            out = vw._enrich_chunks_with_version_rows(db, [
                {"workflow_type": "global", "section_name": "ghost", "app_name": None, "pattern": None},
            ])
        assert out == []

    def test_app_without_app_name_skipped(self):
        """app chunk where app_name key is falsy → elif not matched → skipped."""
        db = MagicMock()
        out = vw._enrich_chunks_with_version_rows(db, [
            {"workflow_type": "app", "section_name": "s", "app_name": None, "pattern": None},
        ])
        assert out == []

    def test_unknown_workflow_type_skipped(self):
        db = MagicMock()
        out = vw._enrich_chunks_with_version_rows(db, [
            {"workflow_type": "other", "section_name": "s", "app_name": None, "pattern": None},
        ])
        assert out == []

    def test_missing_section_name_defaults_to_main(self):
        """If chunk lacks section_name, it should default to DEFAULT_SECTION ('main')."""
        db = MagicMock()
        row = SimpleNamespace(section_name="main", version=1, body="B", domain=None)
        with patch.object(vw, "_global_workflow_latest", return_value=row) as m:
            vw._enrich_chunks_with_version_rows(db, [
                {"workflow_type": "global", "section_name": None, "app_name": None, "pattern": None},
            ])
        m.assert_called_once_with(db, "main")


class TestSearchWorkflowsOrchestrator:
    def test_empty_query_returns_empty(self):
        db = MagicMock()
        assert vw.search_workflows(db, "") == []
        assert vw.search_workflows(db, "   ") == []

    def test_hybrid_ok_path_returns_enriched(self):
        db = MagicMock()
        fake_chunks = [
            {"workflow_type": "global", "section_name": "main", "app_name": None, "pattern": None},
        ]
        row = SimpleNamespace(section_name="main", version=1, body="B", domain=None)
        with patch("app.services.search_workflows.hybrid_workflow_search",
                   return_value=(fake_chunks, "hybrid_ok")), \
             patch.object(vw, "_global_workflow_latest", return_value=row):
            out = vw.search_workflows(db, "q", scope="global", top_n=5)
        assert out == [{
            "scope": "global", "section_name": "main",
            "version": 1, "body": "B", "domain": None,
        }]

    def test_hybrid_ok_but_enriched_empty_falls_back_to_ilike(self):
        """hybrid returns chunks but version lookup returns nothing → ILIKE fallback."""
        db = MagicMock()
        fake_chunks = [
            {"workflow_type": "global", "section_name": "gone", "app_name": None, "pattern": None},
        ]
        ilike_results = [{"scope": "global", "section_name": "main", "version": 1, "body": "x", "domain": None}]
        with patch("app.services.search_workflows.hybrid_workflow_search",
                   return_value=(fake_chunks, "hybrid_ok")), \
             patch.object(vw, "_global_workflow_latest", return_value=None), \
             patch.object(vw, "_legacy_ilike_search_workflows", return_value=ilike_results) as fallback:
            out = vw.search_workflows(db, "q", scope="global")
        fallback.assert_called_once()
        assert out == ilike_results

    def test_hybrid_no_index_falls_back(self):
        db = MagicMock()
        ilike_results = [{"scope": "app", "app_name": "x", "section_name": "s", "version": 1, "body": "b", "domain": None}]
        with patch("app.services.search_workflows.hybrid_workflow_search",
                   return_value=([], "no_index")), \
             patch.object(vw, "_legacy_ilike_search_workflows", return_value=ilike_results):
            out = vw.search_workflows(db, "q", app_name="x", scope="app")
        assert out == ilike_results

    def test_hybrid_exception_falls_back_to_ilike(self, caplog):
        db = MagicMock()
        ilike_results = []
        with patch("app.services.search_workflows.hybrid_workflow_search",
                   side_effect=RuntimeError("pgvector missing")), \
             patch.object(vw, "_legacy_ilike_search_workflows", return_value=ilike_results):
            with caplog.at_level("WARNING"):
                out = vw.search_workflows(db, "q")
        assert out == []
        assert any("hybrid workflow search failed" in r.message for r in caplog.records)
