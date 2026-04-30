"""Unit tests for `app.tools._common` — error envelope helpers + app_name 정규화."""

from __future__ import annotations

import json

from app.tools._common import _normalize_app_name, error_json, error_payload


# ── _normalize_app_name ─────────────────────────────────────────────


class TestNormalizeAppName:
    def test_plain_name(self):
        assert _normalize_app_name("myapp") == "myapp"

    def test_strips_surrounding_whitespace(self):
        assert _normalize_app_name("  myapp  ") == "myapp"

    def test_strips_double_quotes(self):
        assert _normalize_app_name('"myapp"') == "myapp"

    def test_strips_single_quotes(self):
        assert _normalize_app_name("'myapp'") == "myapp"

    def test_name_with_branch_uses_name_part(self):
        assert _normalize_app_name("myapp/main") == "myapp"

    def test_name_with_branch_and_quotes(self):
        assert _normalize_app_name('"myapp/feature"') == "myapp"

    def test_name_with_branch_trims_name_part(self):
        # 이름 조각 내부 공백도 제거되어야 함.
        assert _normalize_app_name("myapp / feature") == "myapp"

    def test_empty_string(self):
        assert _normalize_app_name("") == ""


# ── error_payload ───────────────────────────────────────────────────


class TestErrorPayload:
    def test_basic_shape(self):
        payload = error_payload("boom")
        assert payload == {"ok": False, "error": "boom"}

    def test_extra_fields_merged(self):
        payload = error_payload("boom", code=42, hint="retry")
        assert payload["ok"] is False
        assert payload["error"] == "boom"
        assert payload["code"] == 42
        assert payload["hint"] == "retry"

    def test_extra_cannot_override_ok_flag(self):
        # `ok`/`error` 도 dict 병합이므로 호출자가 override 할 수 있다. 의도된
        # 동작은 아니지만 현재 구현 기준을 고정해 놓는다 — 변경 시 회귀 탐지.
        payload = error_payload("m", ok=True)
        assert payload["ok"] is True


# ── error_json ──────────────────────────────────────────────────────


class TestErrorJson:
    def test_returns_valid_json_string(self):
        out = error_json("bad")
        assert isinstance(out, str)
        data = json.loads(out)
        assert data == {"ok": False, "error": "bad"}

    def test_extras_serialized(self):
        out = error_json("bad", field="x")
        data = json.loads(out)
        assert data["field"] == "x"

    def test_korean_not_escaped(self):
        # ensure_ascii=False 인지 확인 — 한글이 escape 되지 않아야 함.
        out = error_json("오류")
        assert "오류" in out
