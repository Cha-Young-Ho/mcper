"""Unit tests for config utilities: env expansion, deep merge, settings."""

from __future__ import annotations

import os
from unittest.mock import patch


from app.config import (
    _deep_merge_dict,
    _expand_env_in_str,
    expand_env_placeholders,
)


# ── _expand_env_in_str ──────────────────────────────────────────────


class TestExpandEnvInStr:
    def test_no_placeholder(self):
        assert _expand_env_in_str("plain text") == "plain text"

    def test_known_env_var(self):
        with patch.dict(os.environ, {"MY_VAR": "hello"}):
            assert _expand_env_in_str("${MY_VAR}") == "hello"

    def test_unknown_env_with_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UNKNOWN_VAR", None)
            assert _expand_env_in_str("${UNKNOWN_VAR:-fallback}") == "fallback"

    def test_unknown_env_no_default_keeps_placeholder(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MISSING", None)
            result = _expand_env_in_str("${MISSING}")
            assert result == "${MISSING}"

    def test_multiple_placeholders(self):
        with patch.dict(os.environ, {"A": "1", "B": "2"}):
            assert _expand_env_in_str("${A}-${B}") == "1-2"

    def test_empty_string(self):
        assert _expand_env_in_str("") == ""

    def test_env_var_set_to_empty_returns_default(self):
        with patch.dict(os.environ, {"EMPTY_VAR": ""}):
            result = _expand_env_in_str("${EMPTY_VAR:-default}")
            assert result == "default"


# ── expand_env_placeholders (recursive) ─────────────────────────────


class TestExpandEnvPlaceholders:
    def test_nested_dict(self):
        with patch.dict(os.environ, {"PORT": "8080"}):
            data = {"server": {"port": "${PORT}"}}
            result = expand_env_placeholders(data)
            assert result["server"]["port"] == "8080"

    def test_list(self):
        with patch.dict(os.environ, {"HOST": "localhost"}):
            data = ["${HOST}", "other"]
            result = expand_env_placeholders(data)
            assert result == ["localhost", "other"]

    def test_non_string_passthrough(self):
        assert expand_env_placeholders(42) == 42
        assert expand_env_placeholders(None) is None
        assert expand_env_placeholders(True) is True


# ── _deep_merge_dict ────────────────────────────────────────────────


class TestDeepMergeDict:
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        overlay = {"b": 3, "c": 4}
        result = _deep_merge_dict(base, overlay)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"server": {"host": "0.0.0.0", "port": 8000}}
        overlay = {"server": {"port": 9000}}
        result = _deep_merge_dict(base, overlay)
        assert result == {"server": {"host": "0.0.0.0", "port": 9000}}

    def test_overlay_adds_new_nested_key(self):
        base = {"server": {"host": "0.0.0.0"}}
        overlay = {"server": {"ssl": True}}
        result = _deep_merge_dict(base, overlay)
        assert result["server"]["ssl"] is True
        assert result["server"]["host"] == "0.0.0.0"

    def test_overlay_replaces_non_dict_with_dict(self):
        base = {"key": "string_value"}
        overlay = {"key": {"nested": True}}
        result = _deep_merge_dict(base, overlay)
        assert result["key"] == {"nested": True}

    def test_empty_overlay(self):
        base = {"a": 1}
        assert _deep_merge_dict(base, {}) == {"a": 1}

    def test_empty_base(self):
        overlay = {"a": 1}
        assert _deep_merge_dict({}, overlay) == {"a": 1}

    def test_does_not_mutate_base(self):
        base = {"a": {"b": 1}}
        overlay = {"a": {"b": 2}}
        _deep_merge_dict(base, overlay)
        assert base["a"]["b"] == 1
