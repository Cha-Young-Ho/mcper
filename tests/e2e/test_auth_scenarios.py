"""E2E tests: authentication user scenarios."""

import os
import pytest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.auth.service import create_access_token, hash_password
from app.db.auth_models import User
from app.main import app


@pytest.mark.e2e
class TestLoginToAdminFlow:
    """E2E: user logs in and accesses admin features."""

    def test_basic_auth_login_to_dashboard(self, test_client):
        """User authenticates with basic auth and reaches dashboard."""
        response = test_client.get("/admin", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_basic_auth_login_to_tools(self, test_client):
        """User authenticates and accesses tools page."""
        response = test_client.get("/admin/tools", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_basic_auth_login_to_global_rules(self, test_client):
        """User authenticates and accesses global rules."""
        response = test_client.get("/admin/global-rules", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_basic_auth_login_to_plans(self, test_client):
        """User authenticates and accesses plans."""
        response = test_client.get("/admin/plans", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_basic_auth_login_to_celery(self, test_client):
        """User authenticates and accesses celery monitor."""
        response = test_client.get("/admin/celery", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_unauthenticated_then_authenticated_flow(self, test_client):
        """User first gets 401, then authenticates and succeeds."""
        # Step 1: no auth -> 401
        resp1 = test_client.get("/admin")
        assert resp1.status_code in (401, 403)

        # Step 2: with auth -> 200
        resp2 = test_client.get("/admin", auth=("admin", "changeme"))
        assert resp2.status_code == 200

    def test_wrong_credentials_then_correct(self, test_client):
        """User fails with wrong creds, then succeeds with correct."""
        resp1 = test_client.get("/admin", auth=("admin", "wrong"))
        assert resp1.status_code == 401

        resp2 = test_client.get("/admin", auth=("admin", "changeme"))
        assert resp2.status_code == 200


@pytest.mark.e2e
class TestPasswordChangeScenario:
    """E2E: forced password change flow for initial admin."""

    def test_change_password_forced_redirect_when_auth_disabled(self, test_client):
        """When auth disabled, forced password change redirects."""
        response = test_client.get("/auth/change-password-forced", follow_redirects=False)
        assert response.status_code == 303

    def test_logout_flow(self, test_client):
        """User logs out and cookie is cleared."""
        response = test_client.get("/auth/logout", follow_redirects=False)
        assert response.status_code == 303
        location = response.headers.get("location", "")
        assert "/auth/login" in location


@pytest.mark.e2e
class TestTokenRefreshScenario:
    """E2E: token refresh flow."""

    def test_refresh_endpoint_without_auth_returns_400(self, test_client):
        """Token refresh fails when auth is not enabled."""
        response = test_client.post(
            "/auth/token/refresh",
            json={"refresh_token": "some_token"},
        )
        assert response.status_code == 400

    def test_validate_endpoint_without_auth_returns_400(self, test_client):
        """Token validation fails when auth is not enabled."""
        response = test_client.post("/auth/token/validate")
        assert response.status_code == 400
