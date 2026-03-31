"""Unit tests for app.auth.service — password, token, validation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from jose import JWTError

from app.auth.service import (
    create_access_token,
    decode_token,
    hash_api_key,
    hash_password,
    validate_password,
    verify_password,
    verify_token_not_expired,
)


# ── hash_password / verify_password ─────────────────────────────────


class TestHashPassword:
    def test_hash_returns_bcrypt_format(self):
        h = hash_password("testpassword")
        assert h.startswith("$2b$") or h.startswith("$2a$")

    def test_hash_is_salted(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2

    def test_verify_correct_password(self):
        h = hash_password("correct")
        assert verify_password("correct", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_verify_empty_password(self):
        h = hash_password("notempty")
        assert verify_password("", h) is False

    def test_hash_unicode_password(self):
        pw = "한글패스워드!@#"
        h = hash_password(pw)
        assert verify_password(pw, h) is True

    def test_hash_long_password(self):
        pw = "A" * 200 + "!@#"
        h = hash_password(pw)
        assert verify_password(pw, h) is True


# ── hash_api_key ────────────────────────────────────────────────────


class TestHashApiKey:
    def test_returns_sha256_hex(self):
        result = hash_api_key("mykey")
        expected = hashlib.sha256(b"mykey").hexdigest()
        assert result == expected

    def test_deterministic(self):
        assert hash_api_key("key") == hash_api_key("key")

    def test_different_keys_different_hashes(self):
        assert hash_api_key("key1") != hash_api_key("key2")

    def test_empty_key(self):
        result = hash_api_key("")
        assert isinstance(result, str) and len(result) == 64


# ── validate_password ───────────────────────────────────────────────


class TestValidatePassword:
    @pytest.mark.parametrize(
        "pw,expected_none",
        [
            ("ValidPass123!", True),
            ("Short1!", False),
            ("", False),
            ("NoSpecialChar1", False),
            ("12345678901!", True),
            ("abcdefghijk@", True),
            ("12charslong!", True),
        ],
        ids=[
            "valid_mixed",
            "too_short",
            "empty",
            "no_special",
            "digits_special",
            "alpha_special",
            "exact_12_special",
        ],
    )
    def test_parametrized(self, pw: str, expected_none: bool):
        result = validate_password(pw)
        if expected_none:
            assert result is None, f"Expected pass for {pw!r}, got: {result}"
        else:
            assert result is not None, f"Expected failure for {pw!r}"

    def test_11_chars_rejected(self):
        assert validate_password("12345678!0a") is not None

    def test_special_chars_variety(self):
        specials = "!@#$%^&*()_+-=[]{}|;':\",./<>?`~"
        for ch in specials:
            pw = "Abcdefghijk" + ch
            assert validate_password(pw) is None, f"Failed for {ch!r}"

    def test_returns_str_message_on_failure(self):
        msg = validate_password("short")
        assert isinstance(msg, str)
        assert "12 characters" in msg


# ── create_access_token / decode_token ──────────────────────────────


class TestTokenCreationDecoding:
    def test_roundtrip(self):
        token = create_access_token(
            {"sub": "42", "type": "access"}, timedelta(minutes=5)
        )
        payload = decode_token(token)
        assert payload["sub"] == "42"
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_exp_in_future(self):
        token = create_access_token({"sub": "1"}, timedelta(minutes=10))
        payload = decode_token(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert exp > datetime.now(timezone.utc)

    def test_expired_token_raises(self):
        token = create_access_token({"sub": "1"}, timedelta(hours=-1))
        with pytest.raises(JWTError):
            decode_token(token)

    def test_allow_expired_returns_payload(self):
        token = create_access_token(
            {"sub": "1", "type": "refresh"}, timedelta(hours=-1)
        )
        payload = decode_token(token, allow_expired=True)
        assert payload["sub"] == "1"

    def test_invalid_token_raises(self):
        with pytest.raises(JWTError):
            decode_token("not.valid.token")

    def test_empty_token_raises(self):
        with pytest.raises(Exception):
            decode_token("")

    def test_tampered_signature_raises(self):
        token = create_access_token({"sub": "1"}, timedelta(minutes=5))
        parts = token.rsplit(".", 1)
        tampered = parts[0] + ".AAAA"
        with pytest.raises(JWTError):
            decode_token(tampered)

    def test_custom_data_preserved(self):
        token = create_access_token(
            {"sub": "1", "role": "admin", "extra": 99}, timedelta(minutes=5)
        )
        payload = decode_token(token)
        assert payload["role"] == "admin"
        assert payload["extra"] == 99

    def test_default_expires_delta_uses_settings(self):
        token = create_access_token({"sub": "1"})
        payload = decode_token(token)
        assert "exp" in payload


# ── verify_token_not_expired ────────────────────────────────────────


class TestVerifyTokenNotExpired:
    def test_valid_token_returns_true(self):
        token = create_access_token({"sub": "1"}, timedelta(minutes=5))
        assert verify_token_not_expired(token) is True

    def test_expired_token_returns_false(self):
        token = create_access_token({"sub": "1"}, timedelta(hours=-1))
        assert verify_token_not_expired(token) is False

    def test_garbage_token_returns_false(self):
        assert verify_token_not_expired("garbage") is False

    def test_empty_string_returns_false(self):
        assert verify_token_not_expired("") is False
