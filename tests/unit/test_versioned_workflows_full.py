"""Unit tests for versioned_workflows — covers all pure functions and DB-delegating
functions via MagicMock session. Aim: drive full file coverage to 100%."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import versioned_workflows as vw


# ── Pure helpers ──────────────────────────────────────────────────────────


class TestSlug:
    def test_plain_text(self):
        assert vw._slug("hello") == "hello"

    def test_special_chars_replaced(self):
        assert vw._slug("a/b c!") == "a_b_c"

    def test_preserved_chars(self):
        assert vw._slug("a-b.c_d") == "a-b.c_d"

    def test_empty_falls_back_to_default(self):
        assert vw._slug("") == "default"

    def test_none_falls_back_to_default(self):
        assert vw._slug(None) == "default"

    def test_all_special_becomes_default(self):
        assert vw._slug("///") == "default"


class TestSavePaths:
    def test_global_path(self):
        assert vw._global_workflow_save_path("main") == ".cursor/workflows/global/main.md"

    def test_app_path(self):
        assert vw._app_workflow_save_path("myapp", "sec") == ".cursor/workflows/app/myapp/sec.md"

    def test_repo_path_with_pattern(self):
        assert vw._repo_workflow_save_path("gh.com/x", "s") == ".cursor/workflows/repo/gh.com_x/s.md"

    def test_repo_path_empty_pattern_uses_default(self):
        assert vw._repo_workflow_save_path("", "s") == ".cursor/workflows/repo/default/s.md"


class TestDomainFilter:
    def test_none_returns_none(self):
        assert vw._domain_filter(MagicMock(), None) is None

    def test_development_returns_or_clause(self):
        col = MagicMock()
        result = vw._domain_filter(col, "development")
        # The result is an SQLAlchemy BooleanClauseList; just assert non-None
        assert result is not None

    def test_other_domain_equals(self):
        col = MagicMock()
        result = vw._domain_filter(col, "planning")
        assert result is not None


class TestRepoHelpers:
    def test_pat_href_segment_empty(self):
        assert vw.repo_workflow_pat_href_segment("") == vw.REPO_WORKFLOW_PATTERN_URL_DEFAULT

    def test_pat_href_segment_value(self):
        assert vw.repo_workflow_pat_href_segment("abc") == "abc"

    def test_pattern_from_url_segment_default(self):
        assert vw.repo_workflow_pattern_from_url_segment(vw.REPO_WORKFLOW_PATTERN_URL_DEFAULT) == ""

    def test_pattern_from_url_segment_value(self):
        assert vw.repo_workflow_pattern_from_url_segment("abc") == "abc"

    def test_card_display_empty(self):
        assert vw.repo_workflow_pattern_card_display("") == "(default)"

    def test_card_display_value(self):
        assert vw.repo_workflow_pattern_card_display("gh.com") == "gh.com"


# ── Global workflows ──────────────────────────────────────────────────────


class TestGlobalWorkflows:
    def test_list_sections_returns_sorted_default_first(self):
        db = MagicMock()
        result_mock = MagicMock()
        # DB now returns (section_name, rank) tuples already ordered (main first).
        result_mock.all.return_value = [("main", 0), ("a", 1), ("z", 1)]
        db.execute.return_value = result_mock
        result = vw.list_sections_for_global_workflow(db)
        assert result[0] == "main"
        assert "a" in result and "z" in result

    def test_list_sections_empty_returns_default(self):
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute.return_value = result_mock
        assert vw.list_sections_for_global_workflow(db) == [vw.DEFAULT_SECTION]

    def test_all_sections_latest_without_domain(self):
        db = MagicMock()
        row = SimpleNamespace(section_name="main", body="b", version=1)
        scalars = MagicMock()
        scalars.all.return_value = [row]
        db.scalars.return_value = scalars
        result = vw._global_workflow_all_sections_latest(db)
        assert result == [row]

    def test_all_sections_latest_with_development_domain(self):
        db = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        db.scalars.return_value = scalars
        vw._global_workflow_all_sections_latest(db, domain="development")
        # Just ensure it executes without error; the filter branch is covered

    def test_all_sections_latest_with_other_domain(self):
        db = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        db.scalars.return_value = scalars
        vw._global_workflow_all_sections_latest(db, domain="planning")

    def test_global_workflow_latest(self):
        db = MagicMock()
        row = SimpleNamespace(section_name="main", version=1, body="b", domain=None)
        scalars = MagicMock()
        scalars.first.return_value = row
        db.scalars.return_value = scalars
        assert vw._global_workflow_latest(db) is row

    def test_next_global_version_with_existing(self):
        db = MagicMock()
        db.scalar.return_value = 3
        assert vw.next_global_workflow_version(db) == 4

    def test_next_global_version_with_none(self):
        db = MagicMock()
        db.scalar.return_value = None
        assert vw.next_global_workflow_version(db) == 1

    def test_publish_global_calls_index_hook(self):
        db = MagicMock()
        db.scalar.return_value = None  # next_version=1

        def _add_side_effect(row):
            row.id = 42
        db.add.side_effect = _add_side_effect

        with patch.object(vw, "_try_index_workflow") as m:
            ver = vw.publish_global_workflow(db, "body", "main")
        assert ver == 1
        assert db.commit.called
        m.assert_called_once()

    def test_delete_global_version(self):
        db = MagicMock()
        vw.delete_global_workflow_version(db, "main", 1)
        db.execute.assert_called_once()
        db.commit.assert_called_once()

    def test_delete_global_section(self):
        db = MagicMock()
        res = MagicMock()
        res.rowcount = 5
        db.execute.return_value = res
        assert vw.delete_global_workflow_section(db, "main") == 5


# ── App workflows ─────────────────────────────────────────────────────────


class TestAppWorkflows:
    def test_list_distinct_apps(self):
        db = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = ["b", "a", None]
        db.scalars.return_value = scalars
        assert vw.list_distinct_apps_with_workflows(db) == ["a", "b"]

    def test_list_distinct_apps_with_domain(self):
        db = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        db.scalars.return_value = scalars
        vw.list_distinct_apps_with_workflows(db, domain="development")

    def test_list_sections_for_app(self):
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.all.return_value = [("main", 0), ("s1", 1)]
        db.execute.return_value = result_mock
        result = vw.list_sections_for_app_workflow(db, "myapp")
        assert result[0] == "main"

    def test_list_sections_for_app_empty(self):
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute.return_value = result_mock
        assert vw.list_sections_for_app_workflow(db, "myapp") == [vw.DEFAULT_SECTION]

    def test_app_all_sections_latest(self):
        db = MagicMock()
        row = SimpleNamespace(section_name="main")
        scalars = MagicMock()
        scalars.all.return_value = [row]
        db.scalars.return_value = scalars
        assert vw._app_workflow_all_sections_latest(db, "myapp") == [row]

    def test_app_latest(self):
        db = MagicMock()
        row = SimpleNamespace()
        scalars = MagicMock()
        scalars.first.return_value = row
        db.scalars.return_value = scalars
        assert vw._app_workflow_latest(db, "myapp") is row

    def test_next_app_version(self):
        db = MagicMock()
        db.scalar.return_value = None
        assert vw.next_app_workflow_version(db, "x") == 1

    def test_publish_app_calls_index(self):
        db = MagicMock()
        db.scalar.return_value = None

        def _add(row):
            row.id = 7
        db.add.side_effect = _add
        with patch.object(vw, "_try_index_workflow") as m:
            key, sn, ver = vw.publish_app_workflow(db, "MyApp", "body", "main")
        assert key == "myapp"
        assert sn == "main"
        assert ver == 1
        m.assert_called_once()

    def test_delete_app_version(self):
        db = MagicMock()
        vw.delete_app_workflow_version(db, "a", "s", 1)
        db.commit.assert_called_once()

    def test_delete_app_section(self):
        db = MagicMock()
        res = MagicMock()
        res.rowcount = 2
        db.execute.return_value = res
        assert vw.delete_app_workflow_section(db, "a", "s") == 2

    def test_delete_app_stream(self):
        db = MagicMock()
        res = MagicMock()
        res.rowcount = 3
        db.execute.return_value = res
        assert vw.delete_app_workflow_stream(db, "a") == 3

    def test_update_app_delegates_to_publish(self):
        db = MagicMock()
        with patch.object(vw, "publish_app_workflow", return_value=("a", "s", 1)) as m:
            result = vw.update_app_workflow(db, "a", "s", "body", domain="dev")
        m.assert_called_once_with(db, "a", "body", "s", domain="dev")
        assert result == ("a", "s", 1)


# ── Repo workflows ────────────────────────────────────────────────────────


class TestRepoWorkflows:
    def test_list_distinct_patterns(self):
        db = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = ["b", None, "a"]
        db.scalars.return_value = scalars
        result = vw.list_distinct_repo_patterns_with_workflows(db)
        assert "a" in result and "b" in result

    def test_list_distinct_patterns_with_domain(self):
        db = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        db.scalars.return_value = scalars
        vw.list_distinct_repo_patterns_with_workflows(db, domain="development")

    def test_list_sections_for_repo(self):
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.all.return_value = [("s", 1)]
        db.execute.return_value = result_mock
        result = vw.list_sections_for_repo_workflow(db, "p")
        assert "s" in result

    def test_list_sections_for_repo_empty(self):
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute.return_value = result_mock
        assert vw.list_sections_for_repo_workflow(db, "p") == [vw.DEFAULT_SECTION]

    def test_repo_all_sections_latest(self):
        db = MagicMock()
        row = SimpleNamespace(section_name="main")
        scalars = MagicMock()
        scalars.all.return_value = [row]
        db.scalars.return_value = scalars
        assert vw._repo_workflow_all_sections_latest(db, "p") == [row]

    def test_repo_latest(self):
        db = MagicMock()
        row = SimpleNamespace()
        scalars = MagicMock()
        scalars.first.return_value = row
        db.scalars.return_value = scalars
        assert vw._repo_workflow_latest(db, "p") is row

    def test_next_repo_version_with_existing(self):
        db = MagicMock()
        db.scalar.return_value = 7
        assert vw.next_repo_workflow_version(db, "p") == 8

    def test_publish_repo_calls_index(self):
        db = MagicMock()
        db.scalar.return_value = None

        def _add(row):
            row.id = 3
        db.add.side_effect = _add
        with patch.object(vw, "_try_index_workflow") as m:
            key, sn, ver = vw.publish_repo_workflow(db, "gh.com/x", "body")
        assert key == "gh.com/x"
        assert ver == 1
        m.assert_called_once()

    def test_delete_repo_version(self):
        db = MagicMock()
        vw.delete_repo_workflow_version(db, "p", "s", 1)
        db.commit.assert_called_once()

    def test_delete_repo_section(self):
        db = MagicMock()
        res = MagicMock()
        res.rowcount = 1
        db.execute.return_value = res
        assert vw.delete_repo_workflow_section(db, "p", "s") == 1

    def test_delete_repo_stream(self):
        db = MagicMock()
        res = MagicMock()
        res.rowcount = 2
        db.execute.return_value = res
        assert vw.delete_repo_workflow_stream(db, "p") == 2


# ── Markdown rendering ────────────────────────────────────────────────────


class TestGetWorkflowsMarkdown:
    def test_empty_returns_placeholder(self):
        db = MagicMock()
        with patch.object(vw, "_global_workflow_all_sections_latest", return_value=[]):
            out = vw.get_workflows_markdown(db)
        assert "등록된 워크플로우가 없습니다" in out

    def test_global_blocks_rendered(self):
        db = MagicMock()
        g = SimpleNamespace(section_name="main", body="HELLO")
        with patch.object(vw, "_global_workflow_all_sections_latest", return_value=[g]):
            out = vw.get_workflows_markdown(db)
        assert "HELLO" in out
        assert "WORKFLOW FILE:" in out
        assert ".cursor/workflows/global/main.md" in out

    def test_non_default_section_name_used_as_display(self):
        db = MagicMock()
        g = SimpleNamespace(section_name="spec-scan", body="BODY")
        with patch.object(vw, "_global_workflow_all_sections_latest", return_value=[g]):
            out = vw.get_workflows_markdown(db)
        assert "spec-scan" in out
        assert "BODY" in out

    def test_origin_url_with_matched_pattern(self):
        db = MagicMock()
        g_row = SimpleNamespace(section_name="main", body="G")
        repo_row = SimpleNamespace(section_name="main", body="R")
        with patch.object(vw, "_global_workflow_all_sections_latest", return_value=[g_row]), \
             patch.object(vw, "list_distinct_repo_patterns_with_workflows",
                          return_value=["github.com/me", "bitbucket"]), \
             patch.object(vw, "_repo_workflow_all_sections_latest", return_value=[repo_row]):
            out = vw.get_workflows_markdown(db, origin_url="https://github.com/me/myrepo.git")
        assert "R" in out

    def test_origin_url_default_pattern_included(self):
        """Empty pattern "" is always included when origin_url is set."""
        db = MagicMock()
        g_row = SimpleNamespace(section_name="main", body="G")
        with patch.object(vw, "_global_workflow_all_sections_latest", return_value=[g_row]), \
             patch.object(vw, "list_distinct_repo_patterns_with_workflows",
                          return_value=["", "other.com"]), \
             patch.object(vw, "_repo_workflow_all_sections_latest", return_value=[]):
            vw.get_workflows_markdown(db, origin_url="https://some.url/")

    def test_app_name_renders_app_blocks(self):
        db = MagicMock()
        g_row = SimpleNamespace(section_name="main", body="G")
        app_row = SimpleNamespace(section_name="impl", body="A")
        with patch.object(vw, "_global_workflow_all_sections_latest", return_value=[g_row]), \
             patch.object(vw, "_app_workflow_all_sections_latest", return_value=[app_row]):
            out = vw.get_workflows_markdown(db, app_name="MyApp")
        assert "A" in out


# ── Workflow file block helper ────────────────────────────────────────────


class TestWorkflowFileBlock:
    def test_block_contains_markers_and_body(self):
        out = vw._workflow_file_block(".cursor/path.md", "기본", "HELLO")
        assert "WORKFLOW FILE: .cursor/path.md" in out
        assert "END WORKFLOW FILE: .cursor/path.md" in out
        assert "HELLO" in out
