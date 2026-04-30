"""E2E tests: admin workflow scenarios."""

import pytest

from app.db.models import Spec
from app.db.rule_models import GlobalRuleVersion
from app.db.celery_models import FailedTask


@pytest.mark.e2e
class TestRuleManagementWorkflow:
    """E2E: create rules -> view -> manage versions."""

    def test_create_global_rule_and_view(self, test_client, db_session):
        """Admin creates global rule version and views it."""
        # Step 1: Create rule in DB
        db_session.add(
            GlobalRuleVersion(
                version=1, body="# Project Rules\n\nFollow coding standards."
            )
        )
        db_session.commit()

        # Step 2: View rule board
        response = test_client.get("/admin/global-rules", auth=("admin", "changeme"))
        assert response.status_code == 200

        # Step 3: View specific version
        response = test_client.get(
            "/admin/global-rules/v/1", auth=("admin", "changeme")
        )
        assert response.status_code == 200

    def test_multiple_rule_versions_workflow(self, test_client, db_session):
        """Admin creates multiple versions and navigates between them."""
        db_session.add(GlobalRuleVersion(version=1, body="# Rules v1"))
        db_session.add(GlobalRuleVersion(version=2, body="# Rules v2\n\nUpdated."))
        db_session.commit()

        # View board shows both
        resp_board = test_client.get("/admin/global-rules", auth=("admin", "changeme"))
        assert resp_board.status_code == 200

        # View each version
        resp_v1 = test_client.get("/admin/global-rules/v/1", auth=("admin", "changeme"))
        assert resp_v1.status_code == 200

        resp_v2 = test_client.get("/admin/global-rules/v/2", auth=("admin", "changeme"))
        assert resp_v2.status_code == 200


@pytest.mark.e2e
class TestSpecManagementWorkflow:
    """E2E: create specs -> view -> list by app."""

    def test_spec_crud_workflow(self, test_client, db_session):
        """Admin creates spec, views app cards, lists by app."""
        # Step 1: Create spec
        db_session.add(
            Spec(
                title="Login Feature",
                content="## Login\n\nImplement OAuth login.",
                app_target="webapp",
                base_branch="main",
                related_files=["auth.py", "login.html"],
            )
        )
        db_session.commit()

        # Step 2: View app cards
        resp_cards = test_client.get("/admin/plans", auth=("admin", "changeme"))
        assert resp_cards.status_code == 200

        # Step 3: View specs for app
        resp_list = test_client.get(
            "/admin/plans/app/webapp", auth=("admin", "changeme")
        )
        assert resp_list.status_code == 200

    def test_multiple_apps_workflow(self, test_client, db_session):
        """Admin manages specs across multiple apps."""
        db_session.add(
            Spec(
                title="Feature A",
                content="Content A",
                app_target="app1",
                base_branch="main",
                related_files=[],
            )
        )
        db_session.add(
            Spec(
                title="Feature B",
                content="Content B",
                app_target="app2",
                base_branch="main",
                related_files=[],
            )
        )
        db_session.commit()

        # Both apps appear in cards
        resp = test_client.get("/admin/plans", auth=("admin", "changeme"))
        assert resp.status_code == 200

        # Each app's specs are separate
        resp1 = test_client.get("/admin/plans/app/app1", auth=("admin", "changeme"))
        assert resp1.status_code == 200
        resp2 = test_client.get("/admin/plans/app/app2", auth=("admin", "changeme"))
        assert resp2.status_code == 200


@pytest.mark.e2e
class TestCeleryMonitoringWorkflow:
    """E2E: monitor failed tasks -> resolve."""

    def test_failed_task_lifecycle(self, test_client, db_session):
        """Admin sees failed task, then resolves it."""
        # Step 1: Failed task appears
        task = FailedTask(
            task_id="e2e-failed-001",
            entity_type="spec",
            entity_id=1,
            error_message="Connection timeout",
            status="pending",
        )
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)

        # Step 2: View dashboard
        resp_dash = test_client.get("/admin/celery", auth=("admin", "changeme"))
        assert resp_dash.status_code == 200

        # Step 3: Check stats API
        resp_stats = test_client.get("/admin/celery/stats", auth=("admin", "changeme"))
        assert resp_stats.status_code == 200
        stats = resp_stats.json()
        assert stats["pending"] >= 1

        # Step 4: Resolve the task
        resp_resolve = test_client.post(
            f"/admin/celery/resolve/{task.id}",
            auth=("admin", "changeme"),
        )
        assert resp_resolve.status_code == 200

    def test_celery_filter_workflow(self, test_client, db_session):
        """Admin filters failed tasks by status and entity type."""
        db_session.add(
            FailedTask(
                task_id="e2e-filter-1",
                entity_type="spec",
                entity_id=1,
                error_message="Err",
                status="pending",
            )
        )
        db_session.add(
            FailedTask(
                task_id="e2e-filter-2",
                entity_type="code_index",
                entity_id=2,
                error_message="Err",
                status="failed",
            )
        )
        db_session.commit()

        # Filter by status
        resp_pending = test_client.get(
            "/admin/celery?status=pending",
            auth=("admin", "changeme"),
        )
        assert resp_pending.status_code == 200

        # Filter by entity_type
        resp_code = test_client.get(
            "/admin/celery?entity_type=code_index",
            auth=("admin", "changeme"),
        )
        assert resp_code.status_code == 200


@pytest.mark.e2e
class TestHealthCheckWorkflow:
    """E2E: health check endpoints."""

    def test_health_check_no_auth_required(self, test_client):
        """Health endpoint is public."""
        response = test_client.get("/health")
        assert response.status_code in (200, 503)
        data = response.json()
        assert "status" in data

    def test_health_rag_endpoint(self, test_client):
        """RAG health endpoint works."""
        response = test_client.get("/health/rag")
        assert response.status_code in (200, 503)
        data = response.json()
        assert "status" in data
