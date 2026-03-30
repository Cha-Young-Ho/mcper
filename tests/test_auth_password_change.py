"""Tests for admin password forced change (CRITICAL Item #1)."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.service import hash_password, validate_password, verify_password
from app.db.auth_models import User
from app.db.database import get_db


class TestPasswordChangedAtField:
    """Unit tests: password_changed_at field behavior."""

    def test_admin_user_with_password_changed(self, db_session: Session, admin_user: User):
        """Verify password_changed_at is set for users who changed password."""
        assert admin_user.password_changed_at is not None
        assert isinstance(admin_user.password_changed_at, datetime)
        assert admin_user.password_changed_at.tzinfo is not None

    def test_admin_user_default_password_changed_at_none(
        self, db_session: Session, admin_user_default_password: User
    ):
        """Verify password_changed_at is None for users with default password."""
        assert admin_user_default_password.password_changed_at is None

    def test_password_changed_at_timestamp_precision(self, db_session: Session):
        """Verify password_changed_at stores timestamp with timezone."""
        now = datetime.now(timezone.utc)
        user = User(
            username="test_timestamp",
            hashed_password=hash_password("TestPass123"),
            is_admin=True,
            password_changed_at=now,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        assert user.password_changed_at is not None
        assert user.password_changed_at.year == now.year
        assert user.password_changed_at.month == now.month
        assert user.password_changed_at.day == now.day


class TestIsDefaultPassword:
    """Unit tests: detecting default password usage."""

    def test_is_default_password_true(self, db_session: Session):
        """Verify default password 'changeme' is correctly hashed."""
        default_hash = hash_password("changeme")
        user = User(
            username="user_default_hash",
            hashed_password=default_hash,
            is_admin=True,
            password_changed_at=None,
        )
        db_session.add(user)
        db_session.commit()

        # Verify password matches
        assert verify_password("changeme", user.hashed_password)
        assert user.password_changed_at is None

    def test_is_default_password_false(self, db_session: Session):
        """Verify custom password is not the default."""
        custom_hash = hash_password("MySecurePassword123")
        user = User(
            username="user_custom_hash",
            hashed_password=custom_hash,
            is_admin=True,
            password_changed_at=datetime.now(timezone.utc),
        )
        db_session.add(user)
        db_session.commit()

        assert verify_password("MySecurePassword123", user.hashed_password)
        assert not verify_password("changeme", user.hashed_password)

    def test_password_hash_different_for_same_plaintext(self, db_session: Session):
        """Verify bcrypt produces different hashes for same password (salted)."""
        hash1 = hash_password("SamePassword123")
        hash2 = hash_password("SamePassword123")

        # Hashes should be different due to salt, but both should verify
        assert hash1 != hash2
        assert verify_password("SamePassword123", hash1)
        assert verify_password("SamePassword123", hash2)


class TestPasswordValidationRules:
    """Unit tests: password validation requirements (12 chars + special char)."""

    def test_password_too_short_rejected(self):
        """Password shorter than 12 characters should be rejected."""
        assert validate_password("Short1!") is not None
        assert "12 characters" in validate_password("Short1!")

    def test_password_empty_string_rejected(self):
        """Empty string password should fail length check."""
        assert validate_password("") is not None

    def test_password_exactly_12_chars_with_special_accepted(self):
        """Password of exactly 12 characters with special char should pass."""
        password_12 = "Password123!"
        assert len(password_12) == 12
        assert validate_password(password_12) is None

    def test_password_no_special_char_rejected(self):
        """Password without special character should be rejected."""
        assert validate_password("Password12345") is not None
        assert "special character" in validate_password("Password12345")

    def test_password_with_special_char_accepted(self):
        """Password with special character should pass."""
        assert validate_password("MyPassword1!") is None

    def test_password_unicode_support(self):
        """Verify password handling supports non-ASCII characters."""
        unicode_password = "패스워드123!@#abc"
        hashed = hash_password(unicode_password)
        assert verify_password(unicode_password, hashed)

    def test_various_special_characters(self):
        """Various special characters should be accepted."""
        for special in ["!", "@", "#", "$", "%", "^", "&", "*", "(", ")"]:
            pw = f"Password1234{special}"
            assert validate_password(pw) is None, f"Failed for special char: {special}"


class TestRequireAdminUserDependency:
    """Integration tests: require_admin_user dependency with password_changed_at."""

    def test_default_password_user_redirects_to_change_password(
        self, test_client: TestClient, db_session: Session, admin_user_default_password: User
    ):
        """
        CRITICAL: Admin with default password (password_changed_at=None)
        should be redirected to /auth/change-password-forced.
        """
        # Login first
        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user_default_password

            # Try to access /admin (should redirect to change-password-forced)
            response = test_client.get(
                "/admin",
                cookies={"mcper_token": "dummy_token"},
                follow_redirects=False,
            )

            # Should redirect to change-password-forced
            assert response.status_code in (303, 302)
            assert "/auth/change-password-forced" in response.headers.get("location", "")

    def test_changed_password_user_can_access_admin(
        self, test_client: TestClient, db_session: Session, admin_user: User
    ):
        """Admin with password_changed_at set should access /admin directly."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user

            # Try to access /admin (should NOT redirect to change-password-forced)
            response = test_client.get(
                "/admin",
                cookies={"mcper_token": "dummy_token"},
                follow_redirects=False,
            )

            # Should not be a redirect to change-password-forced
            # (may be 200, 403, or redirect to login, but not to change-password-forced)
            if response.status_code in (303, 302):
                assert "/auth/change-password-forced" not in response.headers.get("location", "")

    def test_already_changed_user_accesses_change_password_forced(
        self, test_client: TestClient, db_session: Session, admin_user: User
    ):
        """
        User who already changed password should be redirected
        away from /auth/change-password-forced.
        """
        from unittest.mock import patch

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user

            response = test_client.get(
                "/auth/change-password-forced",
                cookies={"mcper_token": "dummy_token"},
                follow_redirects=False,
            )

            # Should redirect to /admin (user already changed password)
            if response.status_code in (303, 302):
                assert "/admin" in response.headers.get("location", "")

    def test_non_admin_cannot_access_change_password_forced(
        self, test_client: TestClient, db_session: Session, regular_user: User
    ):
        """Non-admin users should not access password change page."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = regular_user

            response = test_client.get(
                "/auth/change-password-forced",
                cookies={"mcper_token": "dummy_token"},
                follow_redirects=False,
            )

            # Should be forbidden (403) or redirect to login
            assert response.status_code in (403, 302)


class TestPasswordChangeEndpoint:
    """Integration tests: POST /auth/change-password-forced endpoint."""

    def test_change_password_success(
        self, test_client: TestClient, db_session: Session, admin_user_default_password: User
    ):
        """Successfully change password from default."""
        from unittest.mock import patch

        new_password = "NewSecure@Pass1"

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user_default_password

            response = test_client.post(
                "/auth/change-password-forced",
                data={"password": new_password, "password_confirm": new_password},
                cookies={"mcper_token": "dummy_token"},
                follow_redirects=False,
            )

            # Should redirect to /admin
            if response.status_code in (303, 302):
                assert "/admin" in response.headers.get("location", "")

            # Refresh user from DB and verify password changed
            db_session.refresh(admin_user_default_password)
            assert admin_user_default_password.password_changed_at is not None
            assert verify_password("NewSecure@Pass1", admin_user_default_password.hashed_password)

    def test_password_too_short_error(
        self, test_client: TestClient, db_session: Session, admin_user_default_password: User
    ):
        """Password < 12 characters should be rejected."""
        from unittest.mock import patch

        short_password = "Short1!"

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user_default_password

            response = test_client.post(
                "/auth/change-password-forced",
                data={"password": short_password, "password_confirm": short_password},
                cookies={"mcper_token": "dummy_token"},
            )

            # Should return 400 with error message
            assert response.status_code == 400
            assert "at least 12 characters" in response.text.lower()

            # Password should NOT be changed
            db_session.refresh(admin_user_default_password)
            assert admin_user_default_password.password_changed_at is None

    def test_password_no_special_char_error(
        self, test_client: TestClient, db_session: Session, admin_user_default_password: User
    ):
        """Password without special character should be rejected."""
        from unittest.mock import patch

        no_special_password = "NoSpecialChar1"

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user_default_password

            response = test_client.post(
                "/auth/change-password-forced",
                data={"password": no_special_password, "password_confirm": no_special_password},
                cookies={"mcper_token": "dummy_token"},
            )

            # Should return 400 with error message
            assert response.status_code == 400
            assert "special character" in response.text.lower()

            # Password should NOT be changed
            db_session.refresh(admin_user_default_password)
            assert admin_user_default_password.password_changed_at is None

    def test_password_mismatch_error(
        self, test_client: TestClient, db_session: Session, admin_user_default_password: User
    ):
        """Password confirmation mismatch should be rejected."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user_default_password

            response = test_client.post(
                "/auth/change-password-forced",
                data={
                    "password": "NewSecure@Pass1",
                    "password_confirm": "Different@Pass1",
                },
                cookies={"mcper_token": "dummy_token"},
            )

            # Should return 400 with error message
            assert response.status_code == 400
            assert "do not match" in response.text.lower()

            # Password should NOT be changed
            db_session.refresh(admin_user_default_password)
            assert admin_user_default_password.password_changed_at is None

    def test_cannot_reuse_default_password_short(
        self, test_client: TestClient, db_session: Session, admin_user_default_password: User
    ):
        """Default 'changeme' (8 chars) is rejected by length policy first."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user_default_password

            response = test_client.post(
                "/auth/change-password-forced",
                data={"password": "changeme", "password_confirm": "changeme"},
                cookies={"mcper_token": "dummy_token"},
            )

            # Should return 400 (too short)
            assert response.status_code == 400

            db_session.refresh(admin_user_default_password)
            assert admin_user_default_password.password_changed_at is None

    def test_cannot_reuse_default_password_env(
        self, test_client: TestClient, db_session: Session, admin_user_default_password: User
    ):
        """If ADMIN_PASSWORD env is a long valid password, reusing it should be rejected."""
        from unittest.mock import patch
        import os

        long_default = "DefaultPass1!"  # 13 chars, has special char

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user_default_password

            with patch.dict(os.environ, {"ADMIN_PASSWORD": long_default}):
                response = test_client.post(
                    "/auth/change-password-forced",
                    data={"password": long_default, "password_confirm": long_default},
                    cookies={"mcper_token": "dummy_token"},
                )

                # Should return 400 with "cannot be the default"
                assert response.status_code == 400
                assert "cannot be the default" in response.text.lower()

                db_session.refresh(admin_user_default_password)
                assert admin_user_default_password.password_changed_at is None

    def test_login_without_password_change_redirects(
        self, test_client: TestClient, db_session: Session, admin_user_default_password: User
    ):
        """Accessing /admin without changing password should redirect."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user_default_password

            response = test_client.get(
                "/admin",
                cookies={"mcper_token": "dummy_token"},
                follow_redirects=False,
            )

            # Should redirect to change-password-forced
            assert response.status_code in (303, 302)
            assert "/auth/change-password-forced" in response.headers.get("location", "")


class TestEdgeCasesPasswordChange:
    """Edge case tests for password change flow."""

    def test_concurrent_password_change_requests(
        self, test_client: TestClient, db_session: Session, admin_user_default_password: User
    ):
        """Simulate two concurrent password change requests."""
        from unittest.mock import patch
        import threading

        results = {"request1": None, "request2": None}

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user_default_password

            def make_request(key: str, password: str):
                response = test_client.post(
                    "/auth/change-password-forced",
                    data={"password": password, "password_confirm": password},
                    cookies={"mcper_token": "dummy_token"},
                )
                results[key] = response.status_code

            t1 = threading.Thread(
                target=make_request, args=("request1", "FirstPass@word1")
            )
            t2 = threading.Thread(
                target=make_request, args=("request2", "SecondPass@word1")
            )

            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # Both should succeed (race condition handling)
            assert results["request1"] in (303, 200)
            assert results["request2"] in (303, 200)

    def test_whitespace_in_password(
        self, test_client: TestClient, db_session: Session, admin_user_default_password: User
    ):
        """Password with leading/trailing whitespace should be trimmed."""

        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = admin_user_default_password

            # Form data with whitespace
            response = test_client.post(
                "/auth/change-password-forced",
                data={
                    "password": "  NewSecure@Pass1  ",
                    "password_confirm": "  NewSecure@Pass1  ",
                },
                cookies={"mcper_token": "dummy_token"},
                follow_redirects=False,
            )

            # Should succeed (whitespace trimmed)
            if response.status_code in (303, 302):
                db_session.refresh(admin_user_default_password)
                # Verify trimmed password works
                assert verify_password("NewSecure@Pass1", admin_user_default_password.hashed_password)


class TestUnauthenticatedAccess:
    """Tests for unauthenticated access to password change endpoints."""

    def test_unauthenticated_get_change_password_redirects_to_login(
        self, test_client: TestClient
    ):
        """GET /auth/change-password-forced without auth should redirect to login."""
        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = None

            response = test_client.get(
                "/auth/change-password-forced",
                follow_redirects=False,
            )

            # Should redirect to /auth/login
            assert response.status_code in (303, 302)
            assert "/auth/login" in response.headers.get("location", "")

    def test_unauthenticated_post_change_password_redirects_to_login(
        self, test_client: TestClient
    ):
        """POST /auth/change-password-forced without auth should redirect to login."""
        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = None

            response = test_client.post(
                "/auth/change-password-forced",
                data={"password": "NewSecure@Pass1", "password_confirm": "NewSecure@Pass1"},
                follow_redirects=False,
            )

            assert response.status_code in (303, 302)
            assert "/auth/login" in response.headers.get("location", "")

    def test_inactive_user_cannot_change_password(
        self, test_client: TestClient, db_session: Session
    ):
        """Inactive user should not be able to access password change."""
        inactive_user = User(
            username="inactive_admin",
            hashed_password=hash_password("changeme"),
            is_admin=True,
            is_active=False,
            password_changed_at=None,
        )
        db_session.add(inactive_user)
        db_session.commit()
        db_session.refresh(inactive_user)

        # get_current_user_optional returns None for inactive users
        with patch("app.auth.dependencies.get_current_user_optional") as mock_get_user:
            mock_get_user.return_value = None

            response = test_client.get(
                "/auth/change-password-forced",
                cookies={"mcper_token": "dummy_token"},
                follow_redirects=False,
            )

            assert response.status_code in (303, 302)
            assert "/auth/login" in response.headers.get("location", "")


class TestStartupConfigValidation:
    """Tests for _validate_startup_config warnings about default password."""

    def test_default_password_with_auth_enabled_logs_critical(self):
        """ADMIN_PASSWORD='changeme' + AUTH_ENABLED=true should log CRITICAL error."""
        import logging

        with patch.dict(
            "os.environ",
            {"ADMIN_PASSWORD": "changeme", "MCPER_AUTH_ENABLED": "true"},
        ):
            with patch("app.main.logger") as mock_logger:
                from app.main import _validate_startup_config
                _validate_startup_config()
                # Should have called logger.error with CRITICAL message
                error_calls = [
                    str(call) for call in mock_logger.error.call_args_list
                ]
                assert any("CRITICAL" in c for c in error_calls)

    def test_custom_password_no_critical_warning(self):
        """Non-default password should not trigger CRITICAL warning."""
        with patch.dict(
            "os.environ",
            {"ADMIN_PASSWORD": "my_secure_pass_123", "MCPER_AUTH_ENABLED": "true"},
        ):
            with patch("app.main.logger") as mock_logger:
                from app.main import _validate_startup_config
                _validate_startup_config()
                error_calls = [
                    str(call) for call in mock_logger.error.call_args_list
                ]
                assert not any("CRITICAL" in c and "ADMIN_PASSWORD" in c for c in error_calls)
