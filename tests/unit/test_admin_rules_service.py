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
