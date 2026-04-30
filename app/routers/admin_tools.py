"""Admin MCP 도구 카탈로그 + 호출 통계."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.routers.admin_base import get_tool_stats, templates

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/tools")
def admin_tools(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """MCP 도구 목록 + 호출 통계."""
    tool_stats, mcp_calls_total = get_tool_stats(db)
    return templates.TemplateResponse(
        request,
        "admin/tools.html",
        {
            "request": request,
            "title": "Tools",
            "tool_stats": tool_stats,
            "mcp_calls_total": mcp_calls_total,
        },
    )
