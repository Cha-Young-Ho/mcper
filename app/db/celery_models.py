"""Celery task monitoring and failure tracking."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


class FailedTask(Base):
    """Track failed Celery tasks for retry management."""

    __tablename__ = "failed_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)  # "spec", "code_index"
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(64), nullable=False, default="pending", index=True
    )  # pending/retrying/failed/resolved
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now, onupdate=_utc_now
    )

    def __repr__(self) -> str:
        return (
            f"<FailedTask id={self.id} task_id={self.task_id} "
            f"entity={self.entity_type}:{self.entity_id} status={self.status}>"
        )


class CeleryTaskStat(Base):
    """Aggregate statistics on Celery task execution."""

    __tablename__ = "celery_task_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    success_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_duration_seconds: Mapped[float] = mapped_column(Integer, nullable=False, default=0)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CeleryTaskStat task_name={self.task_name} "
            f"success={self.success_count} failure={self.failure_count}>"
        )
