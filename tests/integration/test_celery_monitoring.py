"""Integration tests for Celery monitoring service with DB."""

import uuid

import pytest

from app.db.celery_models import FailedTask
from app.services.celery_monitoring import CeleryMonitoring


def _unique_task(prefix: str = "task") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.mark.integration
class TestCeleryMonitoringLogFailure:
    """Test failure logging to DB."""

    def test_log_task_failure_creates_record(self, db_session):
        """Logging a failure creates a FailedTask record."""
        result = CeleryMonitoring.log_task_failure(
            db_session,
            task_id="celery-task-001",
            entity_type="spec",
            entity_id=42,
            error_message="Connection refused",
        )
        assert result.id is not None
        assert result.task_id == "celery-task-001"
        assert result.entity_type == "spec"
        assert result.entity_id == 42
        assert result.error_message == "Connection refused"
        assert result.status == "pending"

    def test_log_task_failure_with_traceback(self, db_session):
        """Failure record includes traceback."""
        result = CeleryMonitoring.log_task_failure(
            db_session,
            task_id="celery-task-002",
            entity_type="code_index",
            entity_id=10,
            error_message="Embed failed",
            traceback="Traceback (most recent call last):\n  ...",
        )
        assert result.traceback is not None
        assert "Traceback" in result.traceback

    def test_log_task_failure_custom_max_retries(self, db_session):
        """Custom max_retries is stored."""
        result = CeleryMonitoring.log_task_failure(
            db_session,
            task_id="celery-task-003",
            entity_type="spec",
            entity_id=1,
            error_message="Timeout",
            max_retries=5,
        )
        assert result.max_retries == 5


@pytest.mark.integration
class TestCeleryMonitoringQuery:
    """Test querying failed tasks."""

    def test_get_failed_tasks_empty(self, db_session):
        """Returns empty list when no failed tasks."""
        result = CeleryMonitoring.get_failed_tasks(db_session)
        assert result == []

    def test_get_failed_tasks_with_data(self, db_session):
        """Returns failed tasks from DB."""
        CeleryMonitoring.log_task_failure(db_session, "q-task-1", "spec", 1, "Error 1")
        CeleryMonitoring.log_task_failure(db_session, "q-task-2", "spec", 2, "Error 2")
        result = CeleryMonitoring.get_failed_tasks(db_session)
        assert len(result) == 2

    def test_get_failed_tasks_filter_by_status(self, db_session):
        """Filter failed tasks by status."""
        CeleryMonitoring.log_task_failure(db_session, "s-task-1", "spec", 1, "Err")
        task = db_session.query(FailedTask).filter_by(task_id="s-task-1").first()
        task.status = "resolved"
        db_session.commit()

        CeleryMonitoring.log_task_failure(db_session, "s-task-2", "spec", 2, "Err")

        pending = CeleryMonitoring.get_failed_tasks(db_session, status="pending")
        assert len(pending) == 1
        resolved = CeleryMonitoring.get_failed_tasks(db_session, status="resolved")
        assert len(resolved) == 1

    def test_get_failed_tasks_filter_by_entity_type(self, db_session):
        """Filter failed tasks by entity type."""
        CeleryMonitoring.log_task_failure(db_session, "e-task-1", "spec", 1, "Err")
        CeleryMonitoring.log_task_failure(
            db_session, "e-task-2", "code_index", 2, "Err"
        )
        specs = CeleryMonitoring.get_failed_tasks(db_session, entity_type="spec")
        assert len(specs) == 1
        code = CeleryMonitoring.get_failed_tasks(db_session, entity_type="code_index")
        assert len(code) == 1

    def test_get_failed_tasks_pagination(self, db_session):
        """Pagination works correctly."""
        for i in range(5):
            CeleryMonitoring.log_task_failure(
                db_session, f"p-task-{i}", "spec", i, f"Error {i}"
            )
        page1 = CeleryMonitoring.get_failed_tasks(db_session, limit=2, offset=0)
        page2 = CeleryMonitoring.get_failed_tasks(db_session, limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].task_id != page2[0].task_id

    def test_get_failed_tasks_count(self, db_session):
        """Count works correctly."""
        CeleryMonitoring.log_task_failure(db_session, "c-task-1", "spec", 1, "Err")
        CeleryMonitoring.log_task_failure(db_session, "c-task-2", "spec", 2, "Err")
        assert CeleryMonitoring.get_failed_tasks_count(db_session) == 2
        assert (
            CeleryMonitoring.get_failed_tasks_count(db_session, status="pending") == 2
        )
        assert (
            CeleryMonitoring.get_failed_tasks_count(db_session, status="resolved") == 0
        )


@pytest.mark.integration
class TestCeleryMonitoringResolve:
    """Test task resolution."""

    def test_mark_task_resolved(self, db_session):
        """Mark a task as resolved."""
        task = CeleryMonitoring.log_task_failure(
            db_session, "r-task-1", "spec", 1, "Err"
        )
        assert CeleryMonitoring.mark_task_resolved(db_session, task.id)
        db_session.refresh(task)
        assert task.status == "resolved"

    def test_mark_nonexistent_task_returns_false(self, db_session):
        """Resolving nonexistent task returns False."""
        assert not CeleryMonitoring.mark_task_resolved(db_session, 99999)


@pytest.mark.integration
class TestCeleryMonitoringStats:
    """Test task statistics tracking. Each test uses a unique task name to avoid
    cross-contamination from pre-existing rows in the shared dev database."""

    def test_update_task_stat_success(self, db_session):
        name = _unique_task("index_spec")
        stat = CeleryMonitoring.update_task_stat(
            db_session, name, success=True, duration_seconds=5.0
        )
        assert stat.task_name == name
        assert stat.success_count == 1
        assert stat.failure_count == 0
        assert stat.last_success_at is not None

    def test_update_task_stat_failure(self, db_session):
        name = _unique_task("index_code")
        stat = CeleryMonitoring.update_task_stat(
            db_session, name, success=False, duration_seconds=2.0
        )
        assert stat.failure_count == 1
        assert stat.success_count == 0
        assert stat.last_failure_at is not None

    def test_update_task_stat_cumulative(self, db_session):
        name = _unique_task("multi")
        CeleryMonitoring.update_task_stat(db_session, name, True, 1.0)
        CeleryMonitoring.update_task_stat(db_session, name, True, 2.0)
        CeleryMonitoring.update_task_stat(db_session, name, False, 3.0)
        stat = CeleryMonitoring.get_task_stats(db_session, task_name=name)
        assert stat.success_count == 2
        assert stat.failure_count == 1
        assert stat.total_duration_seconds == 6

    def test_get_task_stats_all(self, db_session):
        name_a = _unique_task("task_a")
        name_b = _unique_task("task_b")
        CeleryMonitoring.update_task_stat(db_session, name_a, True, 1.0)
        CeleryMonitoring.update_task_stat(db_session, name_b, False, 2.0)
        result = CeleryMonitoring.get_task_stats(db_session)
        assert isinstance(result, list)
        names = {r.task_name for r in result}
        assert name_a in names
        assert name_b in names

    def test_get_task_stats_by_name(self, db_session):
        name = _unique_task("specific")
        CeleryMonitoring.update_task_stat(db_session, name, True, 5.0)
        result = CeleryMonitoring.get_task_stats(db_session, task_name=name)
        assert result is not None
        assert result.task_name == name

    def test_get_task_stats_nonexistent(self, db_session):
        result = CeleryMonitoring.get_task_stats(
            db_session, task_name=_unique_task("ghost")
        )
        assert result is None
