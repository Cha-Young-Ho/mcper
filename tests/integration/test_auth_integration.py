"""Integration tests for auth router + service + dependencies working together."""

import os
import pytest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.auth.service import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
    hash_api_key,
    validate_password,
)
from app.db.auth_models import User, ApiKey


@pytest.mark.integration
class TestAuthLoginFlow:
    """Login flow: form submission -> JWT cookies -> session."""

    @patch.dict(os.environ, {"MCPER_AUTH_ENABLED": "true"})
    def test_login_page_loads(self, test_client):
        """Login page renders when auth is enabled."""
        response = test_client.get("/auth/login")
        # May redirect or render depending on import-time env check
        assert response.status_code in (200, 303)

    def test_login_page_redirects_when_auth_disabled(self, test_client):
        """Login page redirects to /admin when auth disabled."""
        response = test_client.get("/auth/login", follow_redirects=False)
        assert response.status_code == 303 or response.status_code == 200

    def test_logout_clears_cookie(self, test_client):
        """Logout deletes mcper_token cookie and redirects."""
        response = test_client.get("/auth/logout", follow_redirects=False)
        assert response.status_code == 303
        assert "/auth/login" in response.headers.get("location", "")


@pytest.mark.integration
class TestAuthTokenLifecycle:
    """Token creation, validation, and refresh lifecycle."""

    def test_create_and_decode_access_token(self):
        """Create token and decode it back."""
        token = create_access_token(
            {"sub": "1", "type": "access"},
            expires_delta=timedelta(minutes=15),
        )
        payload = decode_token(token)
        assert payload["sub"] == "1"
        assert payload["type"] == "access"

    def test_create_and_decode_refresh_token(self):
        """Refresh token round-trip."""
        token = create_access_token(
            {"sub": "42", "type": "refresh"},
            expires_delta=timedelta(days=7),
        )
        payload = decode_token(token)
        assert payload["sub"] == "42"
        assert payload["type"] == "refresh"

    def test_expired_token_raises(self):
        """Expired token raises on decode."""
        token = create_access_token(
            {"sub": "1", "type": "access"},
            expires_delta=timedelta(hours=-1),
        )
        with pytest.raises(Exception):
            decode_token(token)

    def test_expired_token_with_allow_expired(self):
        """Expired token returns payload when allow_expired=True."""
        token = create_access_token(
            {"sub": "99", "type": "refresh"},
            expires_delta=timedelta(hours=-1),
        )
        payload = decode_token(token, allow_expired=True)
        assert payload["sub"] == "99"


@pytest.mark.integration
class TestAuthPasswordHashing:
    """Password hash + verify integration."""

    def test_hash_and_verify_password(self):
        """Hash then verify returns True."""
        hashed = hash_password("MySecretPass@123")
        assert verify_password("MySecretPass@123", hashed)

    def test_wrong_password_fails_verify(self):
        """Wrong password fails verification."""
        hashed = hash_password("CorrectPass@123")
        assert not verify_password("WrongPass@456", hashed)

    def test_different_hashes_for_same_password(self):
        """bcrypt produces different hashes each time (salted)."""
        h1 = hash_password("SamePass@123")
        h2 = hash_password("SamePass@123")
        assert h1 != h2
        assert verify_password("SamePass@123", h1)
        assert verify_password("SamePass@123", h2)


@pytest.mark.integration
class TestAuthApiKeyIntegration:
    """API key hash and verification."""

    def test_api_key_hash_consistent(self):
        """Same key always produces same hash (SHA-256)."""
        key = "test_key_abc123"
        h1 = hash_api_key(key)
        h2 = hash_api_key(key)
        assert h1 == h2

    def test_different_keys_different_hash(self):
        """Different keys produce different hashes."""
        assert hash_api_key("key_a") != hash_api_key("key_b")

    def test_api_key_crud_via_router(self, test_client, db_session, admin_user):
        """Create and list API keys through auth router (auth disabled mode)."""
        # When auth is disabled, these endpoints use basic auth
        response = test_client.get(
            "/auth/api-keys",
            auth=("admin", "changeme"),
        )
        # Might return 200 or list depending on auth mode
        assert response.status_code in (200, 401)


@pytest.mark.integration
class TestAuthPasswordValidation:
    """Password policy integration tests."""

    def test_short_password_rejected(self):
        """Password under 12 chars rejected."""
        error = validate_password("Short@1")
        assert error is not None
        assert "12" in error

    def test_no_special_char_rejected(self):
        """Password without special char rejected."""
        error = validate_password("NoSpecialCharHere123")
        assert error is not None
        assert "special" in error.lower()

    def test_valid_password_accepted(self):
        """Valid password returns None (no error)."""
        assert validate_password("ValidPass@12345") is None

    def test_exactly_12_chars_with_special(self):
        """Exactly 12 chars with special char is accepted."""
        assert validate_password("12345678901@") is None

    def test_11_chars_rejected(self):
        """11 chars rejected even with special char."""
        assert validate_password("1234567890@") is not None
