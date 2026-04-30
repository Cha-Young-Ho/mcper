"""Unit tests for `app.services.admin_rules_service` — 순수 함수 + 얇은 DB 래퍼.

DB 의존은 전부 MagicMock 으로 대체. SQLAlchemy 실제 호출 없이 함수가
기대한 호출 패턴으로 동작하는지만 검증한다.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.admin_rules_service import (
    _preview_string,
    app_exists,
    count_global_category,
    delete_app_stream,
    delete_global_category,
    repo_pattern_exists,
)


# ── _preview_string (순수 함수) ──────────────────────────────────────


class TestPreviewString:
    def test_none_returns_empty_string(self):
        assert _preview_string(None) == ""

    def test_empty_string_returns_empty(self):
        assert _preview_string("") == ""

    def test_short_string_returned_as_is(self):
        s = "hello world"
        assert _preview_string(s) == s

    def test_exact_limit_unchanged(self):
        # 200자 정확히 — 잘림 표시 붙지 않아야 함.
        s = "a" * 200
        out = _preview_string(s)
        assert out == s
        assert not out.endswith("…")

    def test_over_limit_truncated_with_ellipsis(self):
        s = "a" * 250
        out = _preview_string(s)
        assert out.endswith("…")
        # 앞 200자 + 말줄임표 → 총 201자.
        assert len(out) == 201
        assert out[:200] == "a" * 200

    def test_unicode_counted_by_codepoints(self):
        # 멀티바이트 문자도 파이썬 문자열 길이 기준(200 코드포인트) 으로 자른다.
        s = "한" * 300
        out = _preview_string(s)
        assert out.endswith("…")
        assert len(out) == 201


# ── app_exists / repo_pattern_exists (mock 기반 DB 래퍼) ──────────────


def _make_scalars(first_value):
    """db.scalars(...).first() 체이닝을 흉내 내는 MagicMock 조립."""
    scalars_result = MagicMock()
    scalars_result.first.return_value = first_value
    db = MagicMock()
    db.scalars.return_value = scalars_result
    return db


class TestAppExists:
    def test_returns_true_when_row_found(self):
        db = _make_scalars(first_value=object())  # truthy row
        assert app_exists(db, "myapp") is True
        db.scalars.assert_called_once()

    def test_returns_false_when_no_row(self):
        db = _make_scalars(first_value=None)
        assert app_exists(db, "missing") is False


class TestRepoPatternExists:
    def test_returns_true_when_pattern_found(self):
        db = _make_scalars(first_value=object())
        assert repo_pattern_exists(db, "github.com/org/*") is True

    def test_returns_false_when_pattern_missing(self):
        db = _make_scalars(first_value=None)
        assert repo_pattern_exists(db, "no/match") is False


# ── delete/count 래퍼 — rowcount 변환만 검증 ─────────────────────────


class TestDeleteGlobalCategory:
    def test_returns_rowcount_and_commits(self):
        exec_result = MagicMock()
        exec_result.rowcount = 3
        db = MagicMock()
        db.execute.return_value = exec_result

        n = delete_global_category(db, "main")
        assert n == 3
        db.execute.assert_called_once()
        db.commit.assert_called_once()

    def test_none_rowcount_treated_as_zero(self):
        # SQLAlchemy 가 rowcount 를 모를 때(None) 0 으로 정규화되어야 함.
        exec_result = MagicMock()
        exec_result.rowcount = None
        db = MagicMock()
        db.execute.return_value = exec_result

        assert delete_global_category(db, "main") == 0


class TestDeleteAppStream:
    def test_deletes_rules_and_pull_options(self):
        rule_res = MagicMock()
        rule_res.rowcount = 5
        pull_res = MagicMock()
        pull_res.rowcount = 1
        db = MagicMock()
        # 두 번의 execute 호출: rules → pull_options 순서.
        db.execute.side_effect = [rule_res, pull_res]

        n = delete_app_stream(db, "myapp")
        assert n == 5  # rule 삭제 카운트만 반환
        assert db.execute.call_count == 2
        db.commit.assert_called_once()


class TestCountGlobalCategory:
    def test_returns_integer_count(self):
        db = MagicMock()
        db.scalar.return_value = 7
        assert count_global_category(db, "main") == 7

    def test_none_count_becomes_zero(self):
        db = MagicMock()
        db.scalar.return_value = None
        assert count_global_category(db, "main") == 0


# ── 추가 CRUD 함수 (phase2) ──────────────────────────────────────────


from app.services.admin_rules_service import (  # noqa: E402
    SectionPreview,
    delete_app_section,
    delete_app_section_version,
    delete_global_category_version,
    delete_repo_category,
    delete_repo_category_version,
    delete_repo_stream,
    get_app_section_version,
    get_global_category_version,
    get_global_version_row,
    get_repo_category_version,
    list_app_section_previews,
    list_app_section_versions,
    list_global_category_versions,
    list_global_section_previews,
    list_repo_category_versions,
    list_repo_section_previews,
)


class TestSectionPreviewDataclass:
    def test_fields_accessible(self):
        from datetime import datetime

        p = SectionPreview(
            section_name="main",
            version=3,
            preview="hi",
            created_at=datetime(2026, 1, 1),
        )
        assert p.section_name == "main"
        assert p.version == 3
        assert p.preview == "hi"

    def test_frozen(self):
        from datetime import datetime
        import pytest

        p = SectionPreview("main", 1, "x", datetime(2026, 1, 1))
        with pytest.raises(Exception):
            p.version = 99  # type: ignore[misc]


class TestPreviewFunctions:
    """list_*_section_previews 는 (section_name, version, body_head, created_at) 튜플 행을 돌려주는
    db.execute().all() 호출 한 번에 의존. preview 문자열 가공만 검증."""

    def _mock_db_rows(self, rows):
        from unittest.mock import MagicMock

        exec_result = MagicMock()
        exec_result.all.return_value = rows
        db = MagicMock()
        db.execute.return_value = exec_result
        return db

    def test_global_previews_truncates_long_body(self):
        from datetime import datetime

        long_body = "x" * 210  # > _PREVIEW_CHARS(200)
        db = self._mock_db_rows([("main", 2, long_body, datetime(2026, 1, 1))])
        out = list_global_section_previews(db)
        assert len(out) == 1
        assert out[0].preview.endswith("…")
        assert len(out[0].preview) == 201  # 200 + …

    def test_app_previews_sorts_main_first(self):
        from datetime import datetime

        db = self._mock_db_rows(
            [
                ("zeta", 1, "zbody", datetime(2026, 1, 1)),
                ("main", 1, "mbody", datetime(2026, 1, 2)),
                ("alpha", 1, "abody", datetime(2026, 1, 3)),
            ]
        )
        out = list_app_section_previews(db, "myapp")
        assert [r.section_name for r in out] == ["main", "alpha", "zeta"]

    def test_repo_previews_empty_input(self):
        db = self._mock_db_rows([])
        out = list_repo_section_previews(db, "")
        assert out == []


class TestListVersions:
    def test_list_global_returns_ordered(self):
        from unittest.mock import MagicMock

        row1 = MagicMock(version=3)
        row2 = MagicMock(version=2)
        scalars_result = MagicMock()
        scalars_result.all.return_value = [row1, row2]
        db = MagicMock()
        db.scalars.return_value = scalars_result
        out = list_global_category_versions(db, "main")
        assert out == [row1, row2]
        db.scalars.assert_called_once()

    def test_list_app_returns_list(self):
        from unittest.mock import MagicMock

        rows = [MagicMock(version=v) for v in (5, 4, 3)]
        scalars_result = MagicMock()
        scalars_result.all.return_value = rows
        db = MagicMock()
        db.scalars.return_value = scalars_result
        out = list_app_section_versions(db, "myapp", "main")
        assert len(out) == 3

    def test_list_repo_returns_list(self):
        from unittest.mock import MagicMock

        rows = [MagicMock(version=v) for v in (2, 1)]
        scalars_result = MagicMock()
        scalars_result.all.return_value = rows
        db = MagicMock()
        db.scalars.return_value = scalars_result
        out = list_repo_category_versions(db, "api", "main")
        assert len(out) == 2


class TestGetVersionTuples:
    def _db_with(self, row, count):
        from unittest.mock import MagicMock

        sc = MagicMock()
        sc.first.return_value = row
        db = MagicMock()
        db.scalars.return_value = sc
        db.scalar.return_value = count
        return db

    def test_get_global_returns_row_and_count(self):
        from unittest.mock import MagicMock

        row = MagicMock()
        db = self._db_with(row, 4)
        r, n = get_global_category_version(db, "main", 2)
        assert r is row
        assert n == 4

    def test_get_global_none_count(self):
        db = self._db_with(None, None)
        r, n = get_global_category_version(db, "main", 99)
        assert r is None
        assert n == 0

    def test_get_app_version(self):
        from unittest.mock import MagicMock

        row = MagicMock()
        db = self._db_with(row, 2)
        r, n = get_app_section_version(db, "app", "main", 1)
        assert r is row and n == 2

    def test_get_repo_version(self):
        from unittest.mock import MagicMock

        row = MagicMock()
        db = self._db_with(row, 3)
        r, n = get_repo_category_version(db, "api", "main", 1)
        assert r is row and n == 3


class TestDeleteVersionTuples:
    def _db(self, row_count, after_count):
        from unittest.mock import MagicMock

        res = MagicMock()
        res.rowcount = row_count
        db = MagicMock()
        db.execute.return_value = res
        db.scalar.return_value = after_count
        return db

    def test_delete_global_version_returns_tuple(self):
        db = self._db(1, 3)
        rowcount, remaining = delete_global_category_version(db, "main", 2)
        assert rowcount == 1
        assert remaining == 3
        db.commit.assert_called_once()

    def test_delete_global_version_zero_rowcount(self):
        db = self._db(0, 5)
        rowcount, remaining = delete_global_category_version(db, "main", 99)
        assert rowcount == 0
        assert remaining == 5

    def test_delete_app_section_version(self):
        db = self._db(1, 2)
        rc, rem = delete_app_section_version(db, "app", "main", 1)
        assert rc == 1 and rem == 2

    def test_delete_repo_version(self):
        db = self._db(1, 0)
        rc, rem = delete_repo_category_version(db, "api", "main", 1)
        assert rc == 1 and rem == 0


class TestDeleteSection:
    def test_delete_app_section_returns_rowcount(self):
        from unittest.mock import MagicMock

        res = MagicMock()
        res.rowcount = 3
        db = MagicMock()
        db.execute.return_value = res
        assert delete_app_section(db, "app", "sec") == 3
        db.commit.assert_called_once()

    def test_delete_repo_category(self):
        from unittest.mock import MagicMock

        res = MagicMock()
        res.rowcount = 2
        db = MagicMock()
        db.execute.return_value = res
        assert delete_repo_category(db, "api", "sec") == 2

    def test_delete_repo_stream(self):
        from unittest.mock import MagicMock

        res = MagicMock()
        res.rowcount = 7
        db = MagicMock()
        db.execute.return_value = res
        assert delete_repo_stream(db, "api") == 7


class TestGetGlobalVersionRow:
    def test_returns_row(self):
        from unittest.mock import MagicMock

        row = MagicMock()
        sc = MagicMock()
        sc.first.return_value = row
        db = MagicMock()
        db.scalars.return_value = sc
        assert get_global_version_row(db, 3) is row

    def test_returns_none(self):
        from unittest.mock import MagicMock

        sc = MagicMock()
        sc.first.return_value = None
        db = MagicMock()
        db.scalars.return_value = sc
        assert get_global_version_row(db, 99) is None
