"""Celery task monitoring and failure recovery service."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.celery_models import FailedTask, CeleryTaskStat

logger = logging.getLogger(__name__)


class CeleryMonitoring:
    """Service for monitoring and recovering failed Celery tasks."""

    @staticmethod
    def log_task_failure(
        db: Session,
        task_id: str,
        entity_type: str,
        entity_id: int,
        error_message: str,
        traceback: str | None = None,
        max_retries: int = 3,
    ) -> FailedTask:
        """
        Log a failed task for later retry.

        Args:
            db: Database session
            task_id: Celery task ID
            entity_type: Type of entity ("spec", "code_index", etc.)
            entity_id: ID of the entity being processed
            error_message: Error description
            traceback: Full traceback if available
            max_retries: Maximum number of retry attempts

        Returns:
            FailedTask object
        """
        failed_task = FailedTask(
            task_id=task_id,
            entity_type=entity_type,
            entity_id=entity_id,
            error_message=error_message,
            traceback=traceback,
            max_retries=max_retries,
            status="pending",
        )
        db.add(failed_task)
        db.commit()

        logger.error(
            "Task %s failed: %s:%s — %s",
            task_id,
            entity_type,
            entity_id,
            error_message,
        )

        return failed_task

    @staticmethod
    def get_failed_tasks(
        db: Session,
        status: str | None = None,
        entity_type: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[FailedTask]:
        """
        Retrieve failed tasks with optional filtering.

        Args:
            db: Database session
            status: Filter by status ("pending", "retrying", "failed", "resolved")
            entity_type: Filter by entity type ("spec", "code_index")
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of FailedTask objects
        """
        query = db.query(FailedTask)

        if status:
            query = query.filter_by(status=status)
        if entity_type:
            query = query.filter_by(entity_type=entity_type)

        return (
            query.order_by(FailedTask.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_failed_tasks_count(
        db: Session,
        status: str | None = None,
        entity_type: str | None = None,
    ) -> int:
        """Get count of failed tasks."""
        query = db.query(FailedTask)

        if status:
            query = query.filter_by(status=status)
        if entity_type:
            query = query.filter_by(entity_type=entity_type)

        return query.count()

    @staticmethod
    def retry_failed_task(
        db: Session,
        failed_task_id: int,
    ) -> dict[str, Any]:
        """
        Retry a failed task.

        Args:
            db: Database session
            failed_task_id: ID of FailedTask record

        Returns:
            Result dict with status and details
        """
        failed_task = db.query(FailedTask).filter_by(id=failed_task_id).first()

        if not failed_task:
            return {"ok": False, "error": "task not found"}

        if failed_task.retry_count >= failed_task.max_retries:
            failed_task.status = "failed"
            db.commit()
            return {"ok": False, "error": "max retries exceeded"}

        # Re-enqueue the original task
        try:
            from app.worker.celery_app import celery_app

            if failed_task.entity_type == "spec":
                celery_app.send_task(
                    "index_spec",
                    args=(failed_task.entity_id,),
                )
            elif failed_task.entity_type == "code_index":
                # For code_index, we don't have enough context to requeue
                # This would need to be handled differently
                logger.warning("Cannot auto-retry code_index task without original payload")
                return {"ok": False, "error": "cannot auto-retry code_index without payload"}
            else:
                return {"ok": False, "error": f"unknown entity_type: {failed_task.entity_type}"}

            failed_task.retry_count += 1
            failed_task.status = "retrying"
            failed_task.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=10)
            db.commit()

            logger.info(
                "Retrying task %s (attempt %d/%d)",
                failed_task.task_id,
                failed_task.retry_count,
                failed_task.max_retries,
            )

            return {
                "ok": True,
                "retry_count": failed_task.retry_count,
                "max_retries": failed_task.max_retries,
                "task_id": failed_task.task_id,
            }
        except Exception as e:
            logger.exception("Failed to retry task: %s", e)
            return {"ok": False, "error": str(e)}

    @staticmethod
    def mark_task_resolved(
        db: Session,
        failed_task_id: int,
    ) -> bool:
        """
        Mark a failed task as manually resolved.

        Args:
            db: Database session
            failed_task_id: ID of FailedTask record

        Returns:
            True if successful
        """
        failed_task = db.query(FailedTask).filter_by(id=failed_task_id).first()

        if not failed_task:
            return False

        failed_task.status = "resolved"
        db.commit()

        logger.info("Task %s marked as resolved", failed_task.task_id)
        return True

    @staticmethod
    def get_task_stats(
        db: Session,
        task_name: str | None = None,
    ) -> list[CeleryTaskStat] | CeleryTaskStat | None:
        """
        Get aggregate task statistics.

        Args:
            db: Database session
            task_name: Optional filter by task name

        Returns:
            CeleryTaskStat object(s) or None
        """
        query = db.query(CeleryTaskStat)

        if task_name:
            return query.filter_by(task_name=task_name).first()

        return query.order_by(CeleryTaskStat.failure_count.desc()).all()

    @staticmethod
    def update_task_stat(
        db: Session,
        task_name: str,
        success: bool,
        duration_seconds: float = 0.0,
    ) -> CeleryTaskStat:
        """
        Update aggregate statistics for a task.

        Args:
            db: Database session
            task_name: Name of the task
            success: Whether the task succeeded
            duration_seconds: Task execution duration

        Returns:
            Updated CeleryTaskStat object
        """
        stat = db.query(CeleryTaskStat).filter_by(task_name=task_name).first()

        if not stat:
            stat = CeleryTaskStat(task_name=task_name)
            db.add(stat)

        if success:
            stat.success_count += 1
            stat.last_success_at = datetime.now(timezone.utc)
        else:
            stat.failure_count += 1
            stat.last_failure_at = datetime.now(timezone.utc)

        stat.total_duration_seconds += int(duration_seconds)
        db.commit()

        return stat
