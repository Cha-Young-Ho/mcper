"""E2E tests: error handling and edge cases."""

import pytest


@pytest.mark.e2e
class TestAuthErrorHandling:
    """E2E: authentication error scenarios."""

    def test_invalid_basic_auth_username(self, test_client):
        """Invalid username returns 401."""
        response = test_client.get("/admin", auth=("wronguser", "changeme"))
        assert response.status_code == 401

    def test_empty_credentials(self, test_client):
        """Empty credentials return 401."""
        response = test_client.get("/admin", auth=("", ""))
        assert response.status_code == 401

    def test_no_auth_header(self, test_client):
        """No auth header returns 401."""
        response = test_client.get("/admin")
        assert response.status_code in (401, 403)

    def test_admin_subpages_require_auth(self, test_client):
        """All admin subpages require auth."""
        endpoints = [
            "/admin/global-rules",
            "/admin/plans",
            "/admin/tools",
            "/admin/celery",
            "/admin/csrf-token",
            "/admin/seed/confirm",
        ]
        for endpoint in endpoints:
            response = test_client.get(endpoint)
            assert response.status_code in (401, 403), f"{endpoint} should require auth"


@pytest.mark.e2e
class TestNotFoundHandling:
    """E2E: 404 scenarios."""

    def test_nonexistent_global_rule_version(self, test_client):
        """Requesting nonexistent rule version returns 404."""
        response = test_client.get(
            "/admin/global-rules/v/99999",
            auth=("admin", "changeme"),
        )
        assert response.status_code == 404

    def test_nonexistent_celery_resolve(self, test_client):
        """Resolving nonexistent celery task returns 404."""
        response = test_client.post(
            "/admin/celery/resolve/99999",
            auth=("admin", "changeme"),
        )
        assert response.status_code == 404


@pytest.mark.e2e
class TestSeedForceErrorHandling:
    """E2E: seed force error cases."""

    def test_seed_force_without_confirm(self, test_client):
        """Seed force without 'yes' returns 400."""
        response = test_client.post(
            "/admin/seed/force",
            auth=("admin", "changeme"),
            data={"confirm": ""},
        )
        assert response.status_code == 400

    def test_seed_force_with_wrong_confirm(self, test_client):
        """Seed force with wrong confirm text returns 400."""
        response = test_client.post(
            "/admin/seed/force",
            auth=("admin", "changeme"),
            data={"confirm": "no"},
        )
        assert response.status_code == 400


@pytest.mark.e2e
class TestCrossModuleErrorScenarios:
    """E2E: errors spanning multiple modules."""

    def test_celery_retry_nonexistent_task(self, test_client):
        """Retry of nonexistent task returns 400."""
        response = test_client.post(
            "/admin/celery/retry/99999",
            auth=("admin", "changeme"),
        )
        assert response.status_code == 400

    def test_accessing_all_admin_pages_sequentially(self, test_client):
        """Accessing all admin pages in sequence works with auth."""
        pages = [
            "/admin",
            "/admin/global-rules",
            "/admin/plans",
            "/admin/tools",
            "/admin/celery",
            "/admin/celery/stats",
            "/admin/csrf-token",
        ]
        for page in pages:
            response = test_client.get(page, auth=("admin", "changeme"))
            assert response.status_code == 200, (
                f"{page} returned {response.status_code}"
            )
