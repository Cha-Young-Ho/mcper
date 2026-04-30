"""Unit tests for `app.services.rule_cache` (P12).

- `MCPER_RULE_CACHE` env 토글 동작 검증
- Redis 클라이언트는 MagicMock 으로 대체
- 예외 흡수(장애 격리) 동작 검증
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from app.services.rule_cache import (
    build_rule_cache_key,
    get_cached_rule,
    invalidate_rule,
    set_cached_rule,
)
from app.services import rule_cache as rc


# ── build_rule_cache_key (순수 함수) ──────────────────────────────────


class TestBuildRuleCacheKey:
    def test_all_fields_present(self):
        k = build_rule_cache_key(app_name="myapp", origin_url="git@x", version=3)
        assert k == "myapp:git@x:3"

    def test_none_app_name_becomes_dash(self):
        k = build_rule_cache_key(app_name=None, origin_url="x", version=1)
        assert k == "-:x:1"

    def test_empty_origin_becomes_dash(self):
        k = build_rule_cache_key(app_name="app", origin_url="", version=2)
        assert k == "app:-:2"

    def test_none_version_becomes_latest(self):
        k = build_rule_cache_key(app_name="app", origin_url="u", version=None)
        assert k == "app:u:latest"

    def test_empty_version_string_becomes_latest(self):
        k = build_rule_cache_key(app_name="app", origin_url="u", version="")
        assert k == "app:u:latest"

    def test_latest_literal_preserved(self):
        k = build_rule_cache_key(app_name="app", origin_url="u", version="latest")
        assert k == "app:u:latest"

    def test_app_name_lowercased(self):
        k = build_rule_cache_key(app_name="MyApp", origin_url="u", version=1)
        assert k == "myapp:u:1"

    def test_all_missing(self):
        k = build_rule_cache_key(app_name=None, origin_url=None, version=None)
        assert k == "-:-:latest"


# ── env 토글 ──────────────────────────────────────────────────────────


class TestCacheEnabled:
    def test_default_disabled(self, monkeypatch):
        monkeypatch.delenv("MCPER_RULE_CACHE", raising=False)
        assert rc._cache_enabled() is False

    def test_off_disabled(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "off")
        assert rc._cache_enabled() is False

    def test_redis_enabled(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        assert rc._cache_enabled() is True

    def test_uppercase_redis_enabled(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "REDIS")
        assert rc._cache_enabled() is True


# ── get/set/invalidate (env off → no-op) ─────────────────────────────


class TestDisabledNoop:
    def test_get_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.delenv("MCPER_RULE_CACHE", raising=False)
        assert get_cached_rule("any:any:any") is None

    def test_set_is_noop_when_disabled(self, monkeypatch):
        monkeypatch.delenv("MCPER_RULE_CACHE", raising=False)
        # just shouldn't raise
        set_cached_rule("k", "body")

    def test_invalidate_returns_zero_when_disabled(self, monkeypatch):
        monkeypatch.delenv("MCPER_RULE_CACHE", raising=False)
        assert invalidate_rule("*") == 0


# ── get/set/invalidate (Redis mocked) ────────────────────────────────


class TestGetCachedRule:
    def test_hit_returns_body(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        fake = MagicMock()
        fake.get.return_value = "# body"
        with patch.object(rc, "_client", return_value=fake):
            assert get_cached_rule("k") == "# body"
        fake.get.assert_called_once_with("mcper:rule:k")

    def test_miss_returns_none(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        fake = MagicMock()
        fake.get.return_value = None
        with patch.object(rc, "_client", return_value=fake):
            assert get_cached_rule("k") is None

    def test_redis_exception_returns_none(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        fake = MagicMock()
        fake.get.side_effect = RuntimeError("network")
        with patch.object(rc, "_client", return_value=fake):
            assert get_cached_rule("k") is None

    def test_bytes_value_coerced_to_str(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        fake = MagicMock()
        fake.get.return_value = b"raw"
        with patch.object(rc, "_client", return_value=fake):
            out = get_cached_rule("k")
        assert out == "b'raw'" or out == "raw"  # coercion tolerant


class TestSetCachedRule:
    def test_calls_redis_set_with_ttl(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        fake = MagicMock()
        with patch.object(rc, "_client", return_value=fake):
            set_cached_rule("k", "body")
        fake.set.assert_called_once_with("mcper:rule:k", "body", ex=300)

    def test_custom_ttl(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        fake = MagicMock()
        with patch.object(rc, "_client", return_value=fake):
            set_cached_rule("k", "b", ttl=60)
        fake.set.assert_called_once_with("mcper:rule:k", "b", ex=60)

    def test_set_exception_swallowed(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        fake = MagicMock()
        fake.set.side_effect = RuntimeError("down")
        with patch.object(rc, "_client", return_value=fake):
            set_cached_rule("k", "body")  # shouldn't raise


class TestInvalidateRule:
    def test_scan_and_delete(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        fake = MagicMock()
        # 1st scan returns 2 keys with cursor=7, 2nd returns 1 key with cursor=0
        fake.scan.side_effect = [
            (7, ["mcper:rule:app1:u:1", "mcper:rule:app1:u:2"]),
            (0, ["mcper:rule:app1:u:latest"]),
        ]
        fake.delete.side_effect = [2, 1]
        with patch.object(rc, "_client", return_value=fake):
            n = invalidate_rule("app1:*")
        assert n == 3
        assert fake.scan.call_count == 2
        assert fake.delete.call_count == 2

    def test_empty_scan_returns_zero(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        fake = MagicMock()
        fake.scan.return_value = (0, [])
        with patch.object(rc, "_client", return_value=fake):
            n = invalidate_rule("*")
        assert n == 0
        fake.delete.assert_not_called()

    def test_scan_exception_returns_partial(self, monkeypatch):
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        fake = MagicMock()
        fake.scan.side_effect = RuntimeError("oops")
        with patch.object(rc, "_client", return_value=fake):
            n = invalidate_rule("*")
        assert n == 0  # 에러 시 0 반환 (silent)

    def test_glob_prefix_prepended(self, monkeypatch):
        """`invalidate_rule("*")` 는 `mcper:rule:*` 로 SCAN 해야 다른 네임스페이스 안 건드림."""
        monkeypatch.setenv("MCPER_RULE_CACHE", "redis")
        fake = MagicMock()
        fake.scan.return_value = (0, [])
        with patch.object(rc, "_client", return_value=fake):
            invalidate_rule("*")
        fake.scan.assert_called_once()
        _, kwargs = fake.scan.call_args
        assert kwargs.get("match") == "mcper:rule:*"
