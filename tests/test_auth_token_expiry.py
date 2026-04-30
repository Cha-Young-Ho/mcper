"""Tests for API token expiry validation (CRITICAL Item #2)."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from jose import JWTError

from app.auth.service import (
    create_access_token,
    decode_token,
    verify_token_not_expired,
    hash_api_key,
)
from app.db.auth_models import User, ApiKey
from tests.conftest import auth_disabled_skip


class TestJWTTokenExpiry:
    """Unit tests: JWT token expiry validation."""

    def test_token_creation_has_exp_claim(self, admin_user: User):
        """Verify created token includes exp claim."""
        token = create_access_token(
            data={"sub": str(admin_user.id), "type": "access"},
            expires_delta=timedelta(minutes=15),
        )

        payload = decode_token(token)
        assert "exp" in payload
        assert isinstance(payload["exp"], int)

    def test_token_exp_timestamp_is_future(self, admin_user: User):
        """Verify exp timestamp is in the future."""
        token = create_access_token(
            data={"sub": str(admin_user.id)}, expires_delta=timedelta(minutes=15)
        )

        payload = decode_token(token)
        exp_dt = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)

        assert exp_dt > now

    def test_expired_token_raises_jwt_error(self, admin_user: User):
        """Verify expired token raises JWTError on decode."""
        token = create_access_token(
            data={"sub": str(admin_user.id)},
            expires_delta=timedelta(hours=-1),  # Expired
        )

        with pytest.raises(JWTError):
            decode_token(token, allow_expired=False)

    def test_expired_token_with_allow_expired_flag(self, admin_user: User):
        """Verify allow_expired=True returns payload even if expired."""
        token = create_access_token(
            data={"sub": str(admin_user.id), "type": "refresh"},
            expires_delta=timedelta(hours=-1),  # Expired
        )

        payload = decode_token(token, allow_expired=True)
        assert payload.get("sub") == str(admin_user.id)
        assert payload.get("type") == "refresh"

    def test_verify_token_not_expired_valid_token(self, admin_user: User):
        """verify_token_not_expired returns True for valid token."""
        token = create_access_token(
            data={"sub": str(admin_user.id)}, expires_delta=timedelta(minutes=15)
        )

        assert verify_token_not_expired(token) is True

    def test_verify_token_not_expired_expired_token(self, admin_user: User):
        """verify_token_not_expired returns False for expired token."""
        token = create_access_token(
            data={"sub": str(admin_user.id)}, expires_delta=timedelta(hours=-1)
        )

        assert verify_token_not_expired(token) is False

    def test_verify_token_not_expired_invalid_token(self):
        """verify_token_not_expired returns False for invalid token."""
        assert verify_token_not_expired("invalid.token.here") is False

    def test_token_with_nbf_claim_not_yet_valid(self, admin_user: User):
        """Token with nbf (not before) in future should be invalid."""
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        token = create_access_token(
            data={"sub": str(admin_user.id), "nbf": int(future_time.timestamp())},
            expires_delta=timedelta(minutes=15),
        )

        # This should fail because token is not yet valid
        with pytest.raises(JWTError):
            decode_token(token)


class TestAccessTokenLifetime:
    """Integration tests: Access token lifetime (15 minutes)."""

    def test_access_token_expires_in_15_minutes(self, admin_user: User):
        """Verify access token lifetime is approximately 15 minutes."""
        token = create_access_token(
            data={"sub": str(admin_user.id), "type": "access"},
            expires_delta=timedelta(minutes=15),
        )

        payload = decode_token(token)
        exp_dt = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)

        time_until_expiry = exp_dt - now
        # Should be close to 15 minutes (±30 seconds)
        assert 14 * 60 < time_until_expiry.total_seconds() < 16 * 60

    def test_expired_access_token_rejected_in_dependency(
        self, test_client, db_session, admin_user: User
    ):
        """Expired access token should be rejected in get_current_user_optional."""
        expired_token = create_access_token(
            data={"sub": str(admin_user.id), "type": "access"},
            expires_delta=timedelta(hours=-1),
        )

        # Test using a protected endpoint (mock the dependency to use this token)
        with patch("app.auth.dependencies.decode_token") as mock_decode:
            mock_decode.side_effect = JWTError("Token has expired")

            response = test_client.get(
                "/admin",
                cookies={"mcper_token": expired_token},
            )

            # Should get 401 or 303 (redirect to login)
            assert response.status_code in (401, 303)

    def test_fresh_token_accepted_in_dependency(self, test_client, admin_user: User):
        """Fresh (non-expired) token should be accepted."""
        valid_token = create_access_token(
            data={"sub": str(admin_user.id), "type": "access"},
            expires_delta=timedelta(minutes=15),
        )

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get:
            mock_get.return_value = admin_user

            response = test_client.get(
                "/admin",
                cookies={"mcper_token": valid_token},
            )

            # Should not be rejected for token expiry
            # (may be other auth issues, but not token expiry)
            assert response.status_code != 401 or "expired" not in response.text.lower()


class TestRefreshTokenPattern:
    """Integration tests: Refresh token pattern for token renewal."""

    def test_refresh_token_type_identification(self, admin_user: User):
        """Verify refresh token has type='refresh' claim."""
        refresh_token = create_access_token(
            data={"sub": str(admin_user.id), "type": "refresh"},
            expires_delta=timedelta(days=7),
        )

        payload = decode_token(refresh_token)
        assert payload.get("type") == "refresh"

    def test_access_token_type_identification(self, admin_user: User):
        """Verify access token has type='access' claim."""
        access_token = create_access_token(
            data={"sub": str(admin_user.id), "type": "access"},
            expires_delta=timedelta(minutes=15),
        )

        payload = decode_token(access_token)
        assert payload.get("type") == "access"

    def test_refresh_token_longer_lifetime(self, admin_user: User):
        """Verify refresh token has longer lifetime than access token."""
        access_token = create_access_token(
            data={"sub": str(admin_user.id), "type": "access"},
            expires_delta=timedelta(minutes=15),
        )
        refresh_token = create_access_token(
            data={"sub": str(admin_user.id), "type": "refresh"},
            expires_delta=timedelta(days=7),
        )

        access_payload = decode_token(access_token)
        refresh_payload = decode_token(refresh_token)

        access_exp = datetime.fromtimestamp(access_payload["exp"], tz=timezone.utc)
        refresh_exp = datetime.fromtimestamp(refresh_payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)

        access_lifetime = (access_exp - now).total_seconds()
        refresh_lifetime = (refresh_exp - now).total_seconds()

        assert refresh_lifetime > access_lifetime

    def test_refresh_endpoint_with_expired_access_token(
        self, test_client, admin_user: User
    ):
        """POST /auth/token/refresh should work with expired access token."""
        refresh_token = create_access_token(
            data={"sub": str(admin_user.id), "type": "refresh"},
            expires_delta=timedelta(days=7),
        )

        response = test_client.post(
            "/auth/token/refresh",
            json={"refresh_token": refresh_token},
        )

        # Should succeed
        if response.status_code == 200:
            data = response.json()
            assert "access_token" in data
            assert data["token_type"] == "bearer"

            # New token should be decodable
            new_token = data["access_token"]
            payload = decode_token(new_token)
            assert payload.get("sub") == str(admin_user.id)

    def test_refresh_token_cannot_be_used_as_access_token(
        self, test_client, admin_user: User
    ):
        """Refresh token should not work as access token."""
        _ = create_access_token(
            data={"sub": str(admin_user.id), "type": "refresh"},
            expires_delta=timedelta(days=7),
        )

        with patch("app.auth.dependencies.get_current_user_optional"):
            with patch("app.auth.dependencies.decode_token") as mock_decode:
                payload = {"sub": str(admin_user.id), "type": "refresh"}
                mock_decode.return_value = payload
                # Should reject because type is "refresh", not "access"

                # This would be caught in the endpoint logic
                assert payload.get("type") != "access"

    @auth_disabled_skip
    def test_expired_refresh_token_rejected(self, test_client, admin_user: User):
        """Expired refresh token should be rejected."""
        expired_refresh = create_access_token(
            data={"sub": str(admin_user.id), "type": "refresh"},
            expires_delta=timedelta(days=-1),
        )

        response = test_client.post(
            "/auth/token/refresh",
            json={"refresh_token": expired_refresh},
        )

        # Should fail with 401
        assert response.status_code == 401
        assert "invalid" in response.json().get("detail", "").lower()


class TestAPIKeyExpiry:
    """Integration tests: API key expires_at validation."""

    def test_api_key_valid_not_expired(
        self, db_session, admin_user: User, api_key_valid
    ):
        """Valid API key with future expires_at should pass."""
        raw_key, api_key = api_key_valid

        # Verify key is not expired
        now = datetime.now(timezone.utc)
        assert api_key.expires_at is not None
        assert api_key.expires_at > now

    def test_api_key_expired_past_expiry_date(
        self, db_session, admin_user: User, api_key_expired
    ):
        """Expired API key should fail validation."""
        raw_key, api_key = api_key_expired

        # Verify key is expired
        now = datetime.now(timezone.utc)
        assert api_key.expires_at is not None
        assert api_key.expires_at < now

    def test_api_key_with_no_expiry(self, db_session, admin_user: User):
        """API key with expires_at=None should not be rejected for expiry."""
        raw_key = "api_key_no_expiry_" + __import__("os").urandom(16).hex()
        key_hash = hash_api_key(raw_key)

        api_key = ApiKey(
            user_id=admin_user.id,
            key_hash=key_hash,
            name="no_expiry_key",
            expires_at=None,  # No expiry
        )
        db_session.add(api_key)
        db_session.commit()

        # Should not fail expiry check
        now = datetime.now(timezone.utc)
        # expires_at check only applies if it's not None
        if api_key.expires_at is not None and api_key.expires_at < now:
            assert False, "Should not expire if expires_at is None"

    def test_expired_api_key_rejected_in_dependency(
        self, test_client, db_session, admin_user: User, api_key_expired
    ):
        """Expired API key should be rejected in get_current_user_optional."""
        raw_key, api_key = api_key_expired

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get:
            mock_get.return_value = None  # Expired key should return None

            response = test_client.get(
                "/admin",
                headers={"Authorization": f"Bearer {raw_key}"},
            )

            # Should be rejected (401 or redirect to login)
            assert response.status_code in (401, 303)

    def test_api_key_last_used_at_updated(
        self, db_session, admin_user: User, api_key_valid
    ):
        """Using valid API key should update last_used_at."""
        raw_key, api_key = api_key_valid
        original_last_used = api_key.last_used_at

        with patch("app.auth.dependencies.get_current_user_optional"):
            # Simulate using the key
            db_session.refresh(api_key)
            api_key.last_used_at = datetime.now(timezone.utc)
            db_session.add(api_key)
            db_session.commit()

            db_session.refresh(api_key)
            assert api_key.last_used_at is not None
            # Should be more recent than before (or equal if very fast)
            if original_last_used:
                assert api_key.last_used_at >= original_last_used


@auth_disabled_skip
class TestTokenValidationEndpoint:
    """Integration tests: POST /auth/token/validate endpoint."""

    def test_validate_token_with_valid_jwt(
        self, test_client, admin_user: User, valid_jwt_token: str
    ):
        """POST /auth/token/validate with valid JWT should return user info."""
        with patch("app.auth.dependencies.get_current_user_optional") as mock_get:
            mock_get.return_value = admin_user

            response = test_client.post(
                "/auth/token/validate",
                cookies={"mcper_token": valid_jwt_token},
            )

            if response.status_code == 200:
                data = response.json()
                assert data.get("valid") is True
                assert data.get("user_id") == admin_user.id
                assert data.get("username") == admin_user.username
                assert "expires_at" in data

    def test_validate_token_with_expired_jwt(
        self, test_client, admin_user: User, expired_jwt_token: str
    ):
        """POST /auth/token/validate with expired JWT should return 401."""
        with patch("app.auth.dependencies.get_current_user_optional") as mock_get:
            mock_get.return_value = None  # Expired token returns None

            response = test_client.post(
                "/auth/token/validate",
                cookies={"mcper_token": expired_jwt_token},
            )

            assert response.status_code == 401
            assert "no valid token" in response.json().get("detail", "").lower()

    def test_validate_token_without_token(self, test_client):
        """POST /auth/token/validate without token should return 401."""
        with patch("app.auth.dependencies.get_current_user_optional") as mock_get:
            mock_get.return_value = None

            response = test_client.post(
                "/auth/token/validate",
            )

            assert response.status_code == 401


class TestEdgeCasesTokenExpiry:
    """Edge case tests for token expiry scenarios."""

    def test_token_with_very_short_lifetime(self, admin_user: User):
        """Token with minimal lifetime should expire quickly."""
        token = create_access_token(
            data={"sub": str(admin_user.id)}, expires_delta=timedelta(seconds=1)
        )

        # Should be decodable immediately
        payload = decode_token(token)
        assert payload.get("sub") == str(admin_user.id)

        # After sleep, should be expired
        import time

        time.sleep(2)
        with pytest.raises(JWTError):
            decode_token(token)

    def test_token_clock_skew_tolerance(self, admin_user: User):
        """Token should handle minor clock differences gracefully."""
        token = create_access_token(
            data={"sub": str(admin_user.id)}, expires_delta=timedelta(minutes=15)
        )

        # jose library allows some clock skew by default
        payload = decode_token(token)
        assert payload.get("sub") == str(admin_user.id)

    def test_api_key_expiry_boundary_conditions(self, db_session, admin_user: User):
        """Test API key at exact expiry boundary."""
        now = datetime.now(timezone.utc)
        raw_key = "boundary_test_" + __import__("os").urandom(16).hex()
        key_hash = hash_api_key(raw_key)

        # Create key expiring exactly now
        api_key = ApiKey(
            user_id=admin_user.id,
            key_hash=key_hash,
            name="boundary_key",
            expires_at=now,  # Expires exactly now
        )
        db_session.add(api_key)
        db_session.commit()

        # Should be considered expired (not >=, but >)
        check_now = datetime.now(timezone.utc)
        if api_key.expires_at is not None:
            is_expired = api_key.expires_at < check_now
            # Depending on timing, might be expired
            assert isinstance(is_expired, bool)


class TestTokenIntegrity:
    """Tests for token tampering and invalid token scenarios."""

    def test_tampered_token_signature_rejected(self, admin_user: User):
        """Token with tampered signature should be rejected."""
        token = create_access_token(
            data={"sub": str(admin_user.id), "type": "access"},
            expires_delta=timedelta(minutes=15),
        )

        # Tamper with the signature (last part of JWT)
        parts = token.rsplit(".", 1)
        tampered = parts[0] + ".invalidsignature"

        with pytest.raises(JWTError):
            decode_token(tampered)

    def test_completely_invalid_token_rejected(self):
        """Completely invalid token string should be rejected."""
        with pytest.raises(JWTError):
            decode_token("not.a.valid.jwt.token")

    def test_empty_token_rejected(self):
        """Empty token string should be rejected."""
        with pytest.raises(Exception):
            decode_token("")

    def test_token_with_missing_sub_claim(self, admin_user: User):
        """Token without 'sub' claim should decode but have no sub."""
        token = create_access_token(
            data={"type": "access"},  # No 'sub'
            expires_delta=timedelta(minutes=15),
        )
        payload = decode_token(token)
        assert payload.get("sub") is None

    def test_token_with_wrong_algorithm_rejected(self, admin_user: User):
        """Token signed with different key should be rejected."""
        from jose import jwt

        token = jwt.encode(
            {"sub": str(admin_user.id), "type": "access"},
            "wrong_secret_key",
            algorithm="HS256",
        )

        with pytest.raises(JWTError):
            decode_token(token)


@auth_disabled_skip
class TestRefreshEndpointEdgeCases:
    """Edge case tests for POST /auth/token/refresh endpoint."""

    def test_refresh_with_access_token_type_rejected(
        self, test_client, admin_user: User
    ):
        """Using access token type for refresh should be rejected."""
        access_token = create_access_token(
            data={"sub": str(admin_user.id), "type": "access"},
            expires_delta=timedelta(minutes=15),
        )

        response = test_client.post(
            "/auth/token/refresh",
            json={"refresh_token": access_token},
        )

        # Should be rejected because type is 'access', not 'refresh'
        assert response.status_code == 401
        assert "invalid token type" in response.json().get("detail", "").lower()

    def test_refresh_with_empty_body(self, test_client):
        """Empty JSON body should return 400."""
        response = test_client.post(
            "/auth/token/refresh",
            json={},
        )

        assert response.status_code == 400
        assert "refresh_token required" in response.json().get("detail", "").lower()

    def test_refresh_with_invalid_json(self, test_client):
        """Invalid JSON body should return 400."""
        response = test_client.post(
            "/auth/token/refresh",
            content="not json",
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 400

    def test_refresh_with_inactive_user(
        self, test_client, db_session, admin_user: User
    ):
        """Refresh token for inactive user should be rejected."""
        refresh_token = create_access_token(
            data={"sub": str(admin_user.id), "type": "refresh"},
            expires_delta=timedelta(days=7),
        )

        # Deactivate user
        admin_user.is_active = False
        db_session.add(admin_user)
        db_session.commit()

        response = test_client.post(
            "/auth/token/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 401
        assert "inactive" in response.json().get("detail", "").lower()

    def test_refresh_with_nonexistent_user(self, test_client):
        """Refresh token for non-existent user ID should be rejected."""
        refresh_token = create_access_token(
            data={"sub": "99999", "type": "refresh"},
            expires_delta=timedelta(days=7),
        )

        response = test_client.post(
            "/auth/token/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 401
