"""Admin Celery monitoring dashboard."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.routers.admin_base import templates
from app.services.celery_monitoring import CeleryMonitoring

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/celery")
def admin_celery_dashboard(
    request: Request,
    status: str | None = None,
    entity_type: str | None = None,
    page: int = 1,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Celery monitoring dashboard."""
    per_page = 20
    offset = (page - 1) * per_page

    failed_tasks = CeleryMonitoring.get_failed_tasks(
        db,
        status=status,
        entity_type=entity_type,
        limit=per_page,
        offset=offset,
    )
    total_count = CeleryMonitoring.get_failed_tasks_count(
        db,
        status=status,
        entity_type=entity_type,
    )
    task_stats = CeleryMonitoring.get_task_stats(db)

    # Summary counts
    pending_count = CeleryMonitoring.get_failed_tasks_count(db, status="pending")
    retrying_count = CeleryMonitoring.get_failed_tasks_count(db, status="retrying")
    failed_count = CeleryMonitoring.get_failed_tasks_count(db, status="failed")
    resolved_count = CeleryMonitoring.get_failed_tasks_count(db, status="resolved")

    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request,
        "admin/celery.html",
        {
            "request": request,
            "title": "Vector Monitoring",
            "failed_tasks": failed_tasks,
            "task_stats": task_stats if isinstance(task_stats, list) else [],
            "total_count": total_count,
            "pending_count": pending_count,
            "retrying_count": retrying_count,
            "failed_count": failed_count,
            "resolved_count": resolved_count,
            "current_page": page,
            "total_pages": total_pages,
            "filter_status": status or "",
            "filter_entity_type": entity_type or "",
        },
    )


@router.post("/celery/retry/{task_id}")
def admin_celery_retry(
    task_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Retry a failed task."""
    result = CeleryMonitoring.retry_failed_task(db, task_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return JSONResponse(result)


@router.post("/celery/resolve/{task_id}")
def admin_celery_resolve(
    task_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Mark a failed task as resolved."""
    ok = CeleryMonitoring.mark_task_resolved(db, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return JSONResponse({"ok": True})


@router.get("/celery/active")
def admin_celery_active_api(
    _user: str = Depends(require_admin_user),
):
    """
    Celery worker 실행 중/대기 중 태스크 조회 (Inspect API).
    timeout=1.5s 로 worker 응답 대기 — worker 없으면 빈 결과 반환.
    """
    try:
        from app.worker.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=1.5)
        active_raw = inspector.active() or {}
        reserved_raw = inspector.reserved() or {}

        def _flatten(raw: dict) -> list[dict]:
            out = []
            for worker, tasks in raw.items():
                for t in tasks or []:
                    out.append(
                        {
                            "worker": worker,
                            "task_id": t.get("id", ""),
                            "name": t.get("name", ""),
                            "args": str(t.get("args", []))[:120],
                            "time_start": t.get("time_start"),
                        }
                    )
            return out

        return JSONResponse(
            {
                "active": _flatten(active_raw),
                "reserved": _flatten(reserved_raw),
            }
        )
    except Exception as exc:
        logger.warning("Celery Inspect 실패: %s", exc)
        return JSONResponse({"active": [], "reserved": [], "error": str(exc)})


@router.get("/celery/stats")
def admin_celery_stats_api(
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """JSON API for polling task stats."""
    task_stats = CeleryMonitoring.get_task_stats(db)
    stats_list = (
        task_stats
        if isinstance(task_stats, list)
        else ([task_stats] if task_stats else [])
    )

    pending_count = CeleryMonitoring.get_failed_tasks_count(db, status="pending")
    retrying_count = CeleryMonitoring.get_failed_tasks_count(db, status="retrying")
    failed_count = CeleryMonitoring.get_failed_tasks_count(db, status="failed")
    resolved_count = CeleryMonitoring.get_failed_tasks_count(db, status="resolved")

    return JSONResponse(
        {
            "pending": pending_count,
            "retrying": retrying_count,
            "failed": failed_count,
            "resolved": resolved_count,
            "task_stats": [
                {
                    "task_name": s.task_name,
                    "success_count": s.success_count,
                    "failure_count": s.failure_count,
                    "total_duration_seconds": s.total_duration_seconds,
                    "last_success_at": s.last_success_at.isoformat()
                    if s.last_success_at
                    else None,
                    "last_failure_at": s.last_failure_at.isoformat()
                    if s.last_failure_at
                    else None,
                }
                for s in stats_list
            ],
        }
    )
