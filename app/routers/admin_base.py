"""Admin 라우터 공통 헬퍼, 응답 포맷 + 기본 엔드포인트 (CSRF, seed)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.db.models import Spec
from app.db.mcp_tool_stats import McpToolCallStat
from app.db.seed_defaults import seed_force
from app.mcp_tools_docs import tools_with_counts

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["admin"])

# 상수
ADMIN_ITEMS_PER_PAGE = 20
ADMIN_UPLOAD_ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def _count(db: Session, model) -> int:
    """테이블 레코드 수 조회."""
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _related_files_from_textarea(raw: str) -> list[str]:
    """textarea 입력을 줄 단위로 파싱."""
    return [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]


def _spec_app_cards(db: Session) -> list[dict]:
    """모든 앱의 기획서 카드 생성."""
    apps = db.scalars(select(Spec.app_target).distinct()).all()
    cards: list[dict] = []
    for a in sorted({x for x in apps if x}):
        cnt = (
            db.scalar(
                select(func.count()).select_from(Spec).where(Spec.app_target == a)
            )
            or 0
        )
        cards.append(
            {
                "app": a,
                "count": int(cnt),
                "enc": quote(a, safe=""),
            }
        )
    return cards


def get_tool_stats(db: Session) -> tuple[list[dict], int]:
    """MCP 도구 통계 조회."""
    counts = {
        r.tool_name: int(r.call_count)
        for r in db.scalars(select(McpToolCallStat)).all()
    }
    tool_stats, _ = tools_with_counts(counts)
    mcp_calls_total = int(
        db.scalar(select(func.coalesce(func.sum(McpToolCallStat.call_count), 0))) or 0
    )
    return tool_stats, mcp_calls_total


# ----- CSRF token -----


@router.get("/csrf-token")
def csrf_token_endpoint(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    """CSRF 토큰 반환. JS에서 POST/PUT/DELETE 전 호출."""
    token = request.cookies.get("csrf_token", "")
    return JSONResponse({"csrf_token": token})


# ----- Destructive re-seed -----


@router.get("/seed/confirm")
def seed_confirm(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    """시드 데이터 초기화 확인 페이지."""
    return templates.TemplateResponse(
        request,
        "admin/seed_confirm.html",
        {"request": request, "title": "Re-seed from defaults"},
    )


@router.post("/seed/force")
def seed_force_run(
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    confirm: str = Form(""),
):
    """시드 데이터 강제 초기화."""
    if confirm != "yes":
        raise HTTPException(400, 'Type "yes" in confirm field')
    seed_force(db)
    return RedirectResponse("/admin", status_code=303)
