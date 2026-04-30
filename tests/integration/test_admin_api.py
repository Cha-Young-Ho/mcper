"""Integration tests for admin API endpoints."""

import pytest


@pytest.mark.integration
class TestAdminAPI:
    def test_health_endpoint(self, test_client):
        """Verify /health returns 200."""
        response = test_client.get("/health")
        assert response.status_code == 200

    def test_admin_requires_auth(self, test_client):
        """Verify /admin returns 401 without credentials."""
        response = test_client.get("/admin/")
        assert response.status_code in (401, 403)
