"""Admin 대시보드."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.db.rule_models import GlobalRuleVersion
from app.routers.admin_base import (
    _count,
    get_tool_stats,
    templates,
)
from app.services import versioned_rules as vr

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("")
def admin_home(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """어드민 대시보드."""
    apps = vr.list_distinct_apps(db)
    tool_stats, mcp_calls_total = get_tool_stats(db)
    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "request": request,
            "title": "대시보드",
            "global_versions_n": _count(db, GlobalRuleVersion),
            "repo_patterns_n": len(vr.list_distinct_repo_patterns(db)),
            "apps_n": len(apps),
            "tool_stats": tool_stats,
            "mcp_calls_total": mcp_calls_total,
        },
    )
