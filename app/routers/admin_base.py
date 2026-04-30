"""Admin 라우터 공통 헬퍼, 응답 포맷 + 기본 엔드포인트 (CSRF, seed)."""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
import jinja2
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.auth.service import hash_api_key
from app.db.auth_models import ApiKey, User
from app.db.database import get_db
from app.db.models import Spec
from app.db.mcp_tool_stats import McpToolCallStat
from app.db.seed_defaults import seed_force
from app.mcp_tools_docs import tools_with_counts

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _datefmt(value: object) -> str:
    """datetime → 'YYYY-MM-DD HH:MM' 로 축약."""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")  # type: ignore[union-attr]
    s = str(value)
    return s[:16] if len(s) >= 16 else s


def _make_jinja_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=jinja2.select_autoescape(["html", "xml"]),
    )
    env.filters["datefmt"] = _datefmt
    return env


templates = Jinja2Templates(env=_make_jinja_env())

router = APIRouter(prefix="/admin", tags=["admin"])

# 상수
ADMIN_ITEMS_PER_PAGE = 20
ADMIN_UPLOAD_ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}

# ── 도메인 설정 ─────────────────────────────────────────────────────────────
DOMAIN_CONFIG: dict[str, dict] = {
    "planning": {"slug": "planning", "display": "기획", "scopes": ["app"]},
    "analysis": {"slug": "analysis", "display": "분석", "scopes": ["app"]},
    "development": {
        "slug": "development",
        "display": "개발",
        "scopes": ["global", "repo", "app"],
    },
}

DOMAIN_ORDER = ["planning", "analysis", "development"]


def get_domain_config(slug: str) -> dict | None:
    """도메인 slug로 설정 반환. 없으면 None."""
    return DOMAIN_CONFIG.get(slug)


def get_all_domains() -> list[dict]:
    """정렬된 도메인 목록 반환."""
    return [DOMAIN_CONFIG[k] for k in DOMAIN_ORDER]


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
) -> Response:
    """CSRF 토큰 반환. JS에서 POST/PUT/DELETE 전 호출."""
    token = request.cookies.get("csrf_token", "")
    return JSONResponse({"csrf_token": token})


# ----- Destructive re-seed -----


@router.get("/seed/confirm")
def seed_confirm(
    request: Request,
    _user: str = Depends(require_admin_user),
) -> Response:
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
) -> Response:
    """시드 데이터 강제 초기화."""
    if confirm != "yes":
        raise HTTPException(400, 'Type "yes" in confirm field')
    seed_force(db)
    return RedirectResponse("/admin", status_code=303)


# ----- API Key 관리 -----


def _server_url(request: Request) -> str:
    """요청의 Host 헤더로부터 서버 URL 생성."""
    host = request.headers.get("host", "localhost:8001")
    scheme = "https" if "443" in host else "http"
    return f"{scheme}://{host}"


@router.get("/api-keys")
def api_keys_page(
    request: Request,
    username: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """API 키 관리 페이지."""
    user = db.scalar(select(User).where(User.username == username))
    keys = (
        db.scalars(
            select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.id.desc())
        ).all()
        if user
        else []
    )
    return templates.TemplateResponse(
        request,
        "admin/api_keys.html",
        {
            "request": request,
            "title": "API 키 관리",
            "keys": keys,
            "new_key": None,
            "server_url": _server_url(request),
        },
    )


@router.post("/api-keys/new")
def api_keys_create(
    request: Request,
    name: str = Form(...),
    username: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """새 API 키 발급 → 키 표시와 함께 페이지 다시 렌더링."""
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(404, "User not found")
    raw_key = secrets.token_urlsafe(32)
    db.add(ApiKey(user_id=user.id, key_hash=hash_api_key(raw_key), name=name.strip()))
    db.commit()
    keys = db.scalars(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.id.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "admin/api_keys.html",
        {
            "request": request,
            "title": "API 키 관리",
            "keys": keys,
            "new_key": raw_key,
            "server_url": _server_url(request),
        },
    )


@router.post("/api-keys/{key_id}/revoke")
def api_keys_revoke(
    key_id: int,
    username: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """API 키 삭제."""
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(404, "User not found")
    db.execute(delete(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id))
    db.commit()
    return RedirectResponse("/admin/api-keys", status_code=303)
