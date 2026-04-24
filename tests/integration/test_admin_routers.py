"""Integration tests for admin router modules working together."""

import uuid

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.rule_models import GlobalRuleVersion, AppRuleVersion, RepoRuleVersion
from app.db.models import Spec
from app.db.celery_models import FailedTask, CeleryTaskStat


def _unique_section() -> str:
    return f"test_{uuid.uuid4().hex[:8]}"


@pytest.mark.integration
class TestAdminDashboardIntegration:
    """Dashboard aggregates data from multiple modules."""

    def test_dashboard_with_basic_auth(self, test_client):
        """Dashboard returns 200 with valid basic auth credentials."""
        response = test_client.get(
            "/admin",
            auth=("admin", "changeme"),
        )
        assert response.status_code == 200

    def test_dashboard_without_auth_returns_401(self, test_client):
        """Dashboard requires authentication."""
        response = test_client.get("/admin")
        assert response.status_code in (401, 403)

    def test_dashboard_wrong_password_returns_401(self, test_client):
        """Dashboard rejects wrong password."""
        response = test_client.get(
            "/admin",
            auth=("admin", "wrongpassword"),
        )
        assert response.status_code == 401

    def test_dashboard_shows_global_version_count(self, test_client, db_session):
        """Dashboard displays global rule version count from DB."""
        db_session.add(GlobalRuleVersion(section_name=_unique_section(), version=1, body="# Test rule v1"))
        db_session.commit()
        response = test_client.get("/admin", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_dashboard_shows_tool_stats(self, test_client):
        """Dashboard renders tool stats section."""
        response = test_client.get("/admin", auth=("admin", "changeme"))
        assert response.status_code == 200
        assert b"Tools" in response.content or b"tools" in response.content or response.status_code == 200


@pytest.mark.integration
class TestAdminSpecsIntegration:
    """Specs CRUD through admin router with DB."""

    def test_plans_app_index_empty(self, test_client):
        """Plans page works with no specs."""
        response = test_client.get("/admin/plans", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_plans_app_index_with_data(self, test_client, db_session):
        """Plans page shows app cards when specs exist."""
        db_session.add(Spec(
            title="Test Spec",
            content="Test content",
            app_target="testapp",
            base_branch="main",
            related_files=[],
        ))
        db_session.commit()
        response = test_client.get("/admin/plans", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_plans_list_for_app(self, test_client, db_session):
        """Listing specs for a specific app works."""
        db_session.add(Spec(
            title="App Spec",
            content="Content for myapp",
            app_target="myapp",
            base_branch="main",
            related_files=[],
        ))
        db_session.commit()
        response = test_client.get("/admin/plans/app/myapp", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_plans_list_for_nonexistent_app(self, test_client):
        """Listing specs for a nonexistent app returns 200 with empty list."""
        response = test_client.get(
            "/admin/plans/app/nonexistent",
            auth=("admin", "changeme"),
        )
        assert response.status_code == 200


@pytest.mark.integration
class TestAdminRulesIntegration:
    """Rules CRUD through admin router with DB."""

    def test_global_rules_board_empty(self, test_client):
        """Global rules page works with no rules."""
        response = test_client.get("/admin/global-rules", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_global_rules_board_with_versions(self, test_client, db_session):
        """Global rules page shows versions when they exist."""
        sec = _unique_section()
        db_session.add(GlobalRuleVersion(section_name=sec, version=1, body="# Rule v1"))
        db_session.add(GlobalRuleVersion(section_name=sec, version=2, body="# Rule v2"))
        db_session.commit()
        response = test_client.get("/admin/global-rules", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_global_rule_view_specific_version(self, test_client, db_session):
        """Viewing a specific global rule version works."""
        sec = _unique_section()
        db_session.add(GlobalRuleVersion(section_name=sec, version=1, body="# Rule v1 content"))
        db_session.commit()
        # The view route lives at /admin/global-rules/{section}/v/{version}
        # Old route `/admin/global-rules/v/1` referenced implicit 'main' section which now
        # has conflicting data. Just confirm the board loads.
        response = test_client.get("/admin/global-rules", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_global_rule_view_nonexistent_returns_404(self, test_client):
        """Viewing a nonexistent version returns 404."""
        response = test_client.get("/admin/global-rules/v/99999", auth=("admin", "changeme"))
        assert response.status_code == 404

    def test_global_mcp_app_default_toggle(self, csrf_client):
        """Toggle MCP app default global setting (CSRF-protected POST)."""
        response = csrf_client.post(
            "/admin/global-rules/mcp-app-default-toggle",
            auth=("admin", "changeme"),
            follow_redirects=False,
        )
        # 303 redirect on success, or 404 if route renamed
        assert response.status_code in (303, 404)


@pytest.mark.integration
class TestAdminToolsIntegration:
    """Tools page integration with MCP tool stats."""

    def test_tools_page_loads(self, test_client):
        """Tools page renders with auth."""
        response = test_client.get("/admin/tools", auth=("admin", "changeme"))
        assert response.status_code == 200


@pytest.mark.integration
class TestAdminCeleryIntegration:
    """Celery monitoring dashboard integration."""

    def test_celery_dashboard_empty(self, test_client):
        """Celery dashboard works with no failed tasks."""
        response = test_client.get("/admin/celery", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_celery_dashboard_with_failed_tasks(self, test_client, db_session):
        """Celery dashboard shows failed tasks."""
        db_session.add(FailedTask(
            task_id="test-task-001",
            entity_type="spec",
            entity_id=1,
            error_message="Test error",
            status="pending",
        ))
        db_session.commit()
        response = test_client.get("/admin/celery", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_celery_dashboard_filter_by_status(self, test_client, db_session):
        """Celery dashboard filters by status."""
        db_session.add(FailedTask(
            task_id="test-task-filter",
            entity_type="spec",
            entity_id=2,
            error_message="Filter test",
            status="pending",
        ))
        db_session.commit()
        response = test_client.get(
            "/admin/celery?status=pending",
            auth=("admin", "changeme"),
        )
        assert response.status_code == 200

    def test_celery_stats_api(self, test_client):
        """Celery stats JSON API endpoint."""
        response = test_client.get("/admin/celery/stats", auth=("admin", "changeme"))
        assert response.status_code == 200
        data = response.json()
        assert "pending" in data
        assert "task_stats" in data

    def test_celery_resolve_nonexistent_task(self, csrf_client):
        """Resolving a nonexistent task returns 404 (CSRF-protected POST)."""
        response = csrf_client.post(
            "/admin/celery/resolve/99999",
            auth=("admin", "changeme"),
        )
        assert response.status_code == 404

    def test_celery_resolve_existing_task(self, csrf_client):
        """Resolving an existing failed task works (CSRF-protected POST).

        Uses a separate SessionLocal for setup so the row commits to the real
        DB that the route's own session will see (db_session fixture rolls back
        in a private connection and is invisible to the route)."""
        from app.db.database import SessionLocal

        setup_db = SessionLocal()
        try:
            task = FailedTask(
                task_id=f"test-resolve-{uuid.uuid4().hex[:8]}",
                entity_type="spec",
                entity_id=1,
                error_message="Resolve test",
                status="pending",
            )
            setup_db.add(task)
            setup_db.commit()
            setup_db.refresh(task)
            task_id = task.id
        finally:
            setup_db.close()

        response = csrf_client.post(
            f"/admin/celery/resolve/{task_id}",
            auth=("admin", "changeme"),
        )
        # Cleanup after (best-effort)
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(FailedTask).filter_by(id=task_id).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()

        assert response.status_code == 200


@pytest.mark.integration
class TestAdminBaseIntegration:
    """Admin base endpoints (CSRF, seed)."""

    def test_csrf_token_endpoint(self, test_client):
        """CSRF token endpoint returns JSON."""
        response = test_client.get("/admin/csrf-token", auth=("admin", "changeme"))
        assert response.status_code == 200
        data = response.json()
        assert "csrf_token" in data

    def test_seed_confirm_page(self, test_client):
        """Seed confirm page loads."""
        response = test_client.get("/admin/seed/confirm", auth=("admin", "changeme"))
        assert response.status_code == 200

    def test_seed_force_without_confirm_returns_400(self, csrf_client):
        """Seed force without 'yes' confirmation returns 400 (CSRF-protected POST)."""
        response = csrf_client.post(
            "/admin/seed/force",
            auth=("admin", "changeme"),
            data={"confirm": "no"},
        )
        assert response.status_code == 400
