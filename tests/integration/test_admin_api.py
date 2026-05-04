"""Integration tests for admin API endpoints."""

import pytest


@pytest.mark.integration
class TestAdminAPI:
    def test_health_endpoint(self, test_client):
        """Verify /health/live returns 200.

        TestClient 는 lifespan 을 실행하지 않아 `_startup_done=False` →
        `/health` 와 `/health/ready` 는 503 반환. 그러나 `/health/live` 는
        의존 없는 liveness probe 라 200 보장.
        """
        response = test_client.get("/health/live")
        assert response.status_code == 200

    def test_admin_requires_auth(self, test_client):
        """Verify /admin returns 401 without credentials."""
        response = test_client.get("/admin/")
        assert response.status_code in (401, 403)
