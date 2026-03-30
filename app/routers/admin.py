"""Admin UI: versioned global rules + per-app rules."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.config import settings
from app.db.database import get_db
from app.db.mcp_tool_stats import McpToolCallStat
from app.db.models import Spec
from app.db.rule_models import (
    AppRuleVersion,
    GlobalRuleVersion,
    McpAppPullOption,
    RepoRuleVersion,
)
from app.db.seed_defaults import seed_force
from app.mcp_tools_docs import tools_with_counts
from app.services import versioned_rules as vr
from app.services.celery_client import enqueue_index_spec, enqueue_or_index_sync
from app.services.document_parser import fetch_url_as_text, parse_uploaded_file
from app.services.spec_admin import content_looks_like_vector_or_blob, spec_display_title

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["admin"])


def _count(db: Session, model) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _related_files_from_textarea(raw: str) -> list[str]:
    return [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]


def _spec_app_cards(db: Session) -> list[dict]:
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


# ----- Home -----


@router.get("")
def admin_home(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    apps = vr.list_distinct_apps(db)
    counts = {
        r.tool_name: int(r.call_count)
        for r in db.scalars(select(McpToolCallStat)).all()
    }
    tool_stats, _ = tools_with_counts(counts)
    mcp_calls_total = int(
        db.scalar(select(func.coalesce(func.sum(McpToolCallStat.call_count), 0))) or 0
    )
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


@router.get("/csrf-token")
def csrf_token_endpoint(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    """CSRF 토큰 반환. JS에서 POST/PUT/DELETE 전 호출."""
    token = request.cookies.get("csrf_token", "")
    return JSONResponse({"csrf_token": token})


@router.get("/tools")
def admin_tools(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    counts = {
        r.tool_name: int(r.call_count)
        for r in db.scalars(select(McpToolCallStat)).all()
    }
    tool_stats, _ = tools_with_counts(counts)
    mcp_calls_total = int(
        db.scalar(select(func.coalesce(func.sum(McpToolCallStat.call_count), 0))) or 0
    )
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


# ----- Global rules (version board) -----


@router.get("/global-rules")
def global_rules_board(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(GlobalRuleVersion).order_by(GlobalRuleVersion.version.desc())
    ).all()
    n = len(rows)
    return templates.TemplateResponse(
        request,
        "admin/global_rules_board.html",
        {
            "request": request,
            "title": "Global rules (버전)",
            "rows": rows,
            "can_delete_any_version": n > 1,
            "include_app_default_global": vr.get_mcp_include_app_default_global(db),
        },
    )


@router.post("/global-rules/mcp-app-default-toggle")
def global_mcp_app_default_toggle(
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """앱별 옵션 행이 없을 때 쓰는 전역 기본: rule pull 시 __default__ 앱 스트림 포함."""
    cur = vr.get_mcp_include_app_default_global(db)
    vr.set_mcp_include_app_default_global(db, not cur)
    return RedirectResponse("/admin/global-rules", status_code=303)


@router.get("/global-rules/v/{version}")
def global_rule_view(
    request: Request,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    row = db.scalars(
        select(GlobalRuleVersion).where(GlobalRuleVersion.version == version)
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n_global = int(
        db.scalar(select(func.count()).select_from(GlobalRuleVersion)) or 0
    )
    return templates.TemplateResponse(
        request,
        "admin/global_rule_view.html",
        {
            "request": request,
            "title": f"Global — version {version}",
            "row": row,
            "can_delete_version": n_global > 1,
        },
    )


@router.post("/global-rules/v/{version}/delete")
def global_rule_delete_version(
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    n = int(db.scalar(select(func.count()).select_from(GlobalRuleVersion)) or 0)
    if n <= 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "마지막 Global 버전은 삭제할 수 없습니다.",
        )
    row = db.scalars(
        select(GlobalRuleVersion).where(GlobalRuleVersion.version == version)
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.commit()
    return RedirectResponse("/admin/global-rules", status_code=303)


@router.post("/global-rules/publish")
def global_rule_publish(
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    nv = vr.publish_global(db, body)
    return RedirectResponse(f"/admin/global-rules/v/{nv}", status_code=303)


@router.post("/global-rules/save-as-new")
def global_rule_save_as_new(
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """본문 보기에서 수정한 내용을 global 새 버전으로 저장."""
    nv = vr.publish_global(db, body)
    return RedirectResponse(f"/admin/global-rules/v/{nv}", status_code=303)


# ----- App rules: card index + search -----


def _sort_app_names(names: list[str]) -> list[str]:
    """`__default__` 카드가 그리드 왼쪽 상단에 오도록 먼저 정렬."""

    def key(n: str) -> tuple[int, str]:
        if n.lower() == "__default__":
            return (0, "")
        return (1, n.lower())

    return sorted(names, key=key)


@router.get("/app-rules")
def app_rules_cards(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    q: str = "",
):
    names = _sort_app_names(vr.list_distinct_apps(db))
    qn = q.strip().lower()
    if qn:
        names = [n for n in names if qn in n.lower()]

    cards: list[dict] = []
    for name in names:
        latest = db.scalars(
            select(AppRuleVersion)
            .where(AppRuleVersion.app_name == name)
            .order_by(AppRuleVersion.version.desc())
            .limit(1)
        ).first()
        if latest is None:
            continue
        disp = vr.app_rule_card_display_name(name)
        is_def = name.lower() == "__default__"
        cards.append(
            {
                "name": name,
                "display": disp,
                "is_default": is_def,
                "can_delete_stream": not is_def,
                "latest_version": latest.version,
                "app_url_encoded": quote(name, safe=""),
                "url": f"/admin/app-rules/app/{quote(name, safe='')}",
                "show_pull_toggle": not is_def,
                "include_app_pull_default": (
                    vr.get_mcp_include_app_default_for_app(db, name) if not is_def else False
                ),
            }
        )

    return templates.TemplateResponse(
        request,
        "admin/app_rules_cards.html",
        {
            "request": request,
            "title": "App rules",
            "cards": cards,
            "q": q,
        },
    )


def _sort_repo_patterns(patterns: list[str]) -> list[str]:
    """빈 패턴(default) 카드가 먼저 오도록 정렬."""

    def key(p: str) -> tuple[int, str]:
        if not (p or "").strip():
            return (0, "")
        return (1, (p or "").lower())

    return sorted(patterns, key=key)


@router.post("/repo-rules/pat/{pat_segment}/include-repo-default-toggle")
def repo_pattern_include_repo_default_toggle(
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """패턴(카드)마다 repository default 스트림 병합 여부."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    if not db.scalars(
        select(RepoRuleVersion).where(RepoRuleVersion.pattern == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown repository pattern")
    cur = vr.get_mcp_include_repo_default_for_pattern(db, key)
    vr.set_mcp_include_repo_default_for_pattern(db, key, not cur)
    return RedirectResponse("/admin/repo-rules", status_code=303)


@router.get("/app-rules/new")
def new_app_form(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    return templates.TemplateResponse(
        request,
        "admin/app_rule_new_app.html",
        {
            "request": request,
            "title": "새 앱 룰 (첫 버전)",
            "error": None,
        },
    )


@router.post("/app-rules/new")
def new_app_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    app_name: str = Form(...),
    body: str = Form(...),
):
    key = app_name.strip().lower()
    if not key:
        return templates.TemplateResponse(
            request,
            "admin/app_rule_new_app.html",
            {
                "request": request,
                "title": "새 앱 룰 (첫 버전)",
                "error": "app_name 필수",
            },
            status_code=400,
        )
    existing = db.scalars(
        select(AppRuleVersion).where(AppRuleVersion.app_name == key).limit(1)
    ).first()
    if existing is not None:
        return templates.TemplateResponse(
            request,
            "admin/app_rule_new_app.html",
            {
                "request": request,
                "title": "새 앱 룰 (첫 버전)",
                "error": f"이미 존재하는 앱: {key} — 기존 앱 화면에서 새 버전을 추가하세요.",
            },
            status_code=400,
        )
    vr.publish_app(db, key, body)
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}",
        status_code=303,
    )


# ----- Per-app version board -----


@router.get("/app-rules/app/{app_name}")
def app_rule_board(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    rows = db.scalars(
        select(AppRuleVersion)
        .where(AppRuleVersion.app_name == key)
        .order_by(AppRuleVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "Unknown app")
    can_delete_stream = key != "__default__"
    n_ver = int(
        db.scalar(
            select(func.count()).where(AppRuleVersion.app_name == key)
        )
        or 0
    )

    def _can_del_app_ver(_v: int) -> bool:
        if key == "__default__":
            return n_ver > 1
        return n_ver >= 1

    show_pull_default_toggle = key != "__default__"
    include_app_pull_default = (
        vr.get_mcp_include_app_default_for_app(db, key) if show_pull_default_toggle else False
    )

    return templates.TemplateResponse(
        request,
        "admin/app_rule_board.html",
        {
            "request": request,
            "title": f"App: {vr.app_rule_card_display_name(key)}",
            "app_name": key,
            "app_display": vr.app_rule_card_display_name(key),
            "rows": rows,
            "app_url_encoded": quote(key, safe=""),
            "can_delete_stream": can_delete_stream,
            "can_delete_app_version": _can_del_app_ver,
            "show_pull_default_toggle": show_pull_default_toggle,
            "include_app_pull_default": include_app_pull_default,
        },
    )


@router.post("/app-rules/app/{app_name}/pull-default-toggle")
def app_rule_pull_default_toggle(
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    return_to: str = Form(""),
):
    """
    이 앱으로 `get_global_rule` 호출 시 `__default__` 앱 스트림을 함께 내려줄지 (앱별).
    """
    key = app_name.lower().strip()
    if key == "__default__":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "default 스트림만 조회할 때는 이 옵션이 적용되지 않습니다.",
        )
    if not db.scalars(
        select(AppRuleVersion).where(AppRuleVersion.app_name == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown app")
    cur = vr.get_mcp_include_app_default_for_app(db, key)
    vr.set_mcp_include_app_default_for_app(db, key, not cur)
    if (return_to or "").strip().lower() == "cards":
        return RedirectResponse("/admin/app-rules", status_code=303)
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}",
        status_code=303,
    )


@router.post("/app-rules/app/{app_name}/delete")
def app_rule_delete_stream(
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """해당 app_name 의 모든 app_rule_versions 행 삭제 (`__default__` 제외)."""
    key = app_name.lower().strip()
    if key == "__default__":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "__default__(default) 앱 스트림은 삭제할 수 없습니다.",
        )
    res = db.execute(delete(AppRuleVersion).where(AppRuleVersion.app_name == key))
    db.execute(delete(McpAppPullOption).where(McpAppPullOption.app_name == key))
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "삭제할 행이 없습니다.")
    return RedirectResponse("/admin/app-rules", status_code=303)


@router.post("/app-rules/app/{app_name}/v/{version}/delete")
def app_rule_delete_one_version(
    app_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    n = int(
        db.scalar(select(func.count()).where(AppRuleVersion.app_name == key)) or 0
    )
    if key == "__default__" and n <= 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "default 앱 스트림은 최소 1개 버전이 필요합니다.",
        )
    if n < 1:
        raise HTTPException(404, "Not found")
    res = db.execute(
        delete(AppRuleVersion).where(
            and_(
                AppRuleVersion.app_name == key,
                AppRuleVersion.version == version,
            )
        )
    )
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "Not found")
    n_after = int(
        db.scalar(select(func.count()).where(AppRuleVersion.app_name == key)) or 0
    )
    if n_after > 0:
        return RedirectResponse(
            f"/admin/app-rules/app/{quote(key, safe='')}",
            status_code=303,
        )
    return RedirectResponse("/admin/app-rules", status_code=303)


@router.get("/app-rules/app/{app_name}/publish")
def app_rule_publish_form(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    if not db.scalars(
        select(AppRuleVersion).where(AppRuleVersion.app_name == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown app")
    next_v = vr.next_app_version(db, key)
    return templates.TemplateResponse(
        request,
        "admin/app_rule_publish.html",
        {
            "request": request,
            "title": f"새 버전 — {key}",
            "app_name": key,
            "next_version": next_v,
            "app_url_encoded": quote(key, safe=""),
        },
    )


@router.post("/app-rules/app/{app_name}/publish")
def app_rule_publish_submit(
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    key = app_name.lower().strip()
    _, nv = vr.publish_app(db, key, body)
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}/v/{nv}",
        status_code=303,
    )


@router.post("/app-rules/app/{app_name}/save-as-new")
def app_rule_save_as_new(
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """버전 상세에서 수정한 내용을 해당 앱의 새 버전으로 저장."""
    key = app_name.lower().strip()
    _, nv = vr.publish_app(db, key, body)
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/app-rules/app/{app_name}/v/{version}")
def app_rule_version_view(
    request: Request,
    app_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    row = db.scalars(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(select(func.count()).where(AppRuleVersion.app_name == key)) or 0
    )
    can_delete_version = n >= 1 and (key != "__default__" or n > 1)
    return templates.TemplateResponse(
        request,
        "admin/app_rule_version_view.html",
        {
            "request": request,
            "title": f"{key} — version {version}",
            "row": row,
            "app_name": key,
            "app_url_encoded": quote(key, safe=""),
            "can_delete_version": can_delete_version,
        },
    )


# ----- Repository rules (URL 패턴별) -----


@router.get("/repo-rules")
def repo_rules_cards(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    q: str = "",
):
    patterns = _sort_repo_patterns(vr.list_distinct_repo_patterns(db))
    qn = q.strip().lower()
    if qn:

        def _repo_pattern_matches_query(pat: str) -> bool:
            pl = (pat or "").lower()
            if qn in pl:
                return True
            if not pl and qn in ("default", "fallback", "폴백", "__default__"):
                return True
            return False

        patterns = [p for p in patterns if _repo_pattern_matches_query(p)]

    cards: list[dict] = []
    for pat in patterns:
        latest = db.scalars(
            select(RepoRuleVersion)
            .where(RepoRuleVersion.pattern == pat)
            .order_by(RepoRuleVersion.version.desc())
            .limit(1)
        ).first()
        if latest is None:
            continue
        seg = vr.repo_pat_href_segment(pat)
        display = vr.repo_pattern_card_display(pat)
        is_def = not (pat or "").strip()
        cards.append(
            {
                "pattern": pat,
                "display": display,
                "is_default": is_def,
                "can_delete_stream": not is_def,
                "latest_version": latest.version,
                "url": f"/admin/repo-rules/pat/{seg}",
                "pat_segment": seg,
                "include_repo_default": vr.get_mcp_include_repo_default_for_pattern(db, pat),
            }
        )

    return templates.TemplateResponse(
        request,
        "admin/repo_rules_cards.html",
        {
            "request": request,
            "title": "Repository rules",
            "cards": cards,
            "q": q,
        },
    )


@router.get("/repo-rules/new")
def new_repo_pattern_form(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    return templates.TemplateResponse(
        request,
        "admin/repo_rule_new_pattern.html",
        {
            "request": request,
            "title": "새 Repository 패턴 (첫 버전)",
            "error": None,
        },
    )


@router.post("/repo-rules/new")
def new_repo_pattern_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    pattern: str = Form(...),
    sort_order: int = Form(100),
    body: str = Form(...),
):
    key = pattern.strip()
    if key == vr.REPO_PATTERN_URL_DEFAULT:
        return templates.TemplateResponse(
            request,
            "admin/repo_rule_new_pattern.html",
            {
                "request": request,
                "title": "새 Repository 패턴 (첫 버전)",
                "error": f"패턴 이름으로 `{vr.REPO_PATTERN_URL_DEFAULT}` 는 사용할 수 없습니다.",
            },
            status_code=400,
        )
    existing = db.scalars(
        select(RepoRuleVersion).where(RepoRuleVersion.pattern == key).limit(1)
    ).first()
    if existing is not None:
        return templates.TemplateResponse(
            request,
            "admin/repo_rule_new_pattern.html",
            {
                "request": request,
                "title": "새 Repository 패턴 (첫 버전)",
                "error": f"이미 존재하는 패턴: `{key or '(빈 패턴)'}`. 기존 패턴 화면에서 새 버전을 추가하세요.",
            },
            status_code=400,
        )
    vr.publish_repo(db, key, body, sort_order=sort_order)
    seg = vr.repo_pat_href_segment(key)
    return RedirectResponse(f"/admin/repo-rules/pat/{seg}", status_code=303)


@router.get("/repo-rules/pat/{pat_segment}")
def repo_rule_board(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vr.repo_pattern_from_url_segment(pat_segment)
    rows = db.scalars(
        select(RepoRuleVersion)
        .where(RepoRuleVersion.pattern == key)
        .order_by(RepoRuleVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "Unknown repository pattern")
    pat_url = vr.repo_pat_href_segment(key)
    display = vr.repo_pattern_card_display(key)
    can_delete_stream = (key or "").strip() != ""
    n_ver = int(
        db.scalar(
            select(func.count()).where(RepoRuleVersion.pattern == key)
        )
        or 0
    )

    def _can_del_repo_ver(_v: int) -> bool:
        if not (key or "").strip():
            return n_ver > 1
        return n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/repo_rule_board.html",
        {
            "request": request,
            "title": f"Repo: {display}",
            "pattern": key,
            "pattern_display": display,
            "rows": rows,
            "pat_url": pat_url,
            "can_delete_stream": can_delete_stream,
            "can_delete_repo_version": _can_del_repo_ver,
        },
    )


@router.post("/repo-rules/pat/{pat_segment}/delete")
def repo_rule_delete_pattern_stream(
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vr.repo_pattern_from_url_segment(pat_segment)
    if not (key or "").strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "default(빈 패턴) Repository 스트림은 삭제할 수 없습니다.",
        )
    res = db.execute(delete(RepoRuleVersion).where(RepoRuleVersion.pattern == key))
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "삭제할 행이 없습니다.")
    return RedirectResponse("/admin/repo-rules", status_code=303)


@router.post("/repo-rules/pat/{pat_segment}/v/{version}/delete")
def repo_rule_delete_one_version(
    pat_segment: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vr.repo_pattern_from_url_segment(pat_segment)
    n = int(
        db.scalar(select(func.count()).where(RepoRuleVersion.pattern == key)) or 0
    )
    if not (key or "").strip() and n <= 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "default 패턴 스트림은 최소 1개 버전이 필요합니다.",
        )
    if n < 1:
        raise HTTPException(404, "Not found")
    res = db.execute(
        delete(RepoRuleVersion).where(
            and_(
                RepoRuleVersion.pattern == key,
                RepoRuleVersion.version == version,
            )
        )
    )
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "Not found")
    n_after = int(
        db.scalar(select(func.count()).where(RepoRuleVersion.pattern == key)) or 0
    )
    pat_url = vr.repo_pat_href_segment(key)
    if n_after > 0:
        return RedirectResponse(f"/admin/repo-rules/pat/{pat_url}", status_code=303)
    return RedirectResponse("/admin/repo-rules", status_code=303)


@router.get("/repo-rules/pat/{pat_segment}/publish")
def repo_rule_publish_form(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vr.repo_pattern_from_url_segment(pat_segment)
    if not db.scalars(
        select(RepoRuleVersion).where(RepoRuleVersion.pattern == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown repository pattern")
    next_v = vr.next_repo_version(db, key)
    pat_url = vr.repo_pat_href_segment(key)
    display = vr.repo_pattern_card_display(key)
    return templates.TemplateResponse(
        request,
        "admin/repo_rule_publish.html",
        {
            "request": request,
            "title": f"새 버전 — {display}",
            "pattern": key,
            "pattern_display": display,
            "next_version": next_v,
            "pat_url": pat_url,
        },
    )


@router.post("/repo-rules/pat/{pat_segment}/publish")
def repo_rule_publish_submit(
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    key = vr.repo_pattern_from_url_segment(pat_segment)
    _, nv = vr.publish_repo(db, key, body)
    pat_url = vr.repo_pat_href_segment(key)
    return RedirectResponse(
        f"/admin/repo-rules/pat/{pat_url}/v/{nv}",
        status_code=303,
    )


@router.post("/repo-rules/pat/{pat_segment}/save-as-new")
def repo_rule_save_as_new(
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    key = vr.repo_pattern_from_url_segment(pat_segment)
    _, nv = vr.publish_repo(db, key, body)
    pat_url = vr.repo_pat_href_segment(key)
    return RedirectResponse(
        f"/admin/repo-rules/pat/{pat_url}/v/{nv}",
        status_code=303,
    )


@router.get("/repo-rules/pat/{pat_segment}/v/{version}")
def repo_rule_version_view(
    request: Request,
    pat_segment: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vr.repo_pattern_from_url_segment(pat_segment)
    row = db.scalars(
        select(RepoRuleVersion).where(
            RepoRuleVersion.pattern == key,
            RepoRuleVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    pat_url = vr.repo_pat_href_segment(key)
    display = vr.repo_pattern_card_display(key)
    n = int(
        db.scalar(select(func.count()).where(RepoRuleVersion.pattern == key)) or 0
    )
    can_delete_version = n >= 1 and ((key or "").strip() != "" or n > 1)
    return templates.TemplateResponse(
        request,
        "admin/repo_rule_version_view.html",
        {
            "request": request,
            "title": f"{display} — version {version}",
            "row": row,
            "pattern": key,
            "pattern_display": display,
            "pat_url": pat_url,
            "can_delete_version": can_delete_version,
        },
    )


# ----- 기획서 (본문) -----


@router.get("/plans")
def plans_app_index(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "admin/spec_apps_cards.html",
        {
            "request": request,
            "title": "기획서",
            "page_heading": "앱별 기획서",
            "nav_base": "plans",
            "cards": _spec_app_cards(db),
        },
    )


@router.get("/plans/app/{app_name}")
def plans_list_for_app(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.strip()
    rows = db.scalars(
        select(Spec)
        .where(Spec.app_target == key)
        .order_by(Spec.id.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "admin/specs_list_by_app.html",
        {
            "request": request,
            "title": f"기획서 — {key}",
            "app_name": key,
            "app_enc": quote(key, safe=""),
            "nav_base": "plans",
            "rows": rows,
            "spec_display_title": spec_display_title,
        },
    )


@router.get("/plans/{spec_id:int}")
def plan_detail(
    request: Request,
    spec_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    row = db.get(Spec, spec_id)
    if row is None:
        raise HTTPException(404, "Not found")
    hide_body = content_looks_like_vector_or_blob(row.content)
    return templates.TemplateResponse(
        request,
        "admin/plan_detail.html",
        {
            "request": request,
            "title": spec_display_title(row),
            "row": row,
            "hide_body": hide_body,
            "spec_display_title": spec_display_title,
            "app_enc": quote(row.app_target, safe=""),
        },
    )


@router.get("/plans/{spec_id:int}/edit")
def plan_edit_form(
    request: Request,
    spec_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    row = db.get(Spec, spec_id)
    if row is None:
        raise HTTPException(404, "Not found")
    related_lines = "\n".join(row.related_files or [])
    return templates.TemplateResponse(
        request,
        "admin/plan_edit.html",
        {
            "request": request,
            "title": f"수정 — {spec_display_title(row)}",
            "row": row,
            "related_lines": related_lines,
            "spec_display_title": spec_display_title,
            "app_enc": quote(row.app_target, safe=""),
        },
    )


@router.post("/plans/{spec_id:int}/edit")
def plan_edit_submit(
    spec_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    title: str = Form(""),
    app_target: str = Form(...),
    base_branch: str = Form(...),
    content: str = Form(...),
    related_files_text: str = Form(""),
):
    row = db.get(Spec, spec_id)
    if row is None:
        raise HTTPException(404, "Not found")
    app_key = app_target.strip()
    if not app_key:
        raise HTTPException(400, "app_target 필수")
    row.title = (title or "").strip() or None
    row.app_target = app_key
    row.base_branch = (base_branch or "").strip() or "main"
    row.content = content or ""
    row.related_files = _related_files_from_textarea(related_files_text)
    db.commit()
    enqueue_index_spec(spec_id)
    return RedirectResponse(f"/admin/plans/{spec_id}", status_code=303)


@router.get("/plans/{spec_id:int}/delete/confirm")
def plan_delete_confirm(
    request: Request,
    spec_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    row = db.get(Spec, spec_id)
    if row is None:
        raise HTTPException(404, "Not found")
    return templates.TemplateResponse(
        request,
        "admin/plan_delete_confirm.html",
        {
            "request": request,
            "title": f"삭제 확인 — {spec_display_title(row)}",
            "row": row,
            "spec_display_title": spec_display_title,
            "app_enc": quote(row.app_target, safe=""),
        },
    )


@router.post("/plans/{spec_id:int}/delete")
def plan_delete(
    spec_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    confirm: str = Form(""),
):
    if confirm.strip().upper() != "DELETE":
        raise HTTPException(400, '확인 입력란에 대문자 DELETE 를 입력하세요.')
    row = db.get(Spec, spec_id)
    if row is None:
        raise HTTPException(404, "Not found")
    app_enc = quote(row.app_target, safe="")
    db.delete(row)
    db.commit()
    return RedirectResponse(f"/admin/plans/app/{app_enc}", status_code=303)


# ----- 기획서 일괄 업로드 -----

_ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


@router.get("/plans/bulk-upload")
def plan_bulk_upload_form(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    apps = sorted({row for (row,) in db.execute(select(Spec.app_target).distinct()).all()})
    return templates.TemplateResponse(
        request,
        "admin/plan_bulk_upload.html",
        {
            "request": request,
            "title": "기획서 일괄 업로드",
            "known_apps": apps,
        },
    )


@router.post("/plans/bulk-upload")
async def plan_bulk_upload_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    app_target: str = Form(...),
    base_branch: str = Form("main"),
    files: list[UploadFile] = File(...),
):
    app_key = app_target.strip().lower()
    if not app_key:
        raise HTTPException(400, "app_target 필수")

    results = []
    for f in files:
        filename = f.filename or "unnamed"
        ext = Path(filename).suffix.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            results.append({"file": filename, "ok": False, "error": f"지원하지 않는 형식: {ext}"})
            continue
        try:
            raw = await f.read()
            text = parse_uploaded_file(filename, raw)
            if not text.strip():
                results.append({"file": filename, "ok": False, "error": "파일 내용이 비어 있습니다"})
                continue

            title = Path(filename).stem
            spec = Spec(
                title=title,
                content=text,
                app_target=app_key,
                base_branch=(base_branch or "main").strip() or "main",
                related_files=[],
            )
            db.add(spec)
            db.flush()  # spec.id 확보
            index_result = enqueue_or_index_sync(spec.id)
            db.commit()
            results.append({
                "file": filename,
                "ok": True,
                "spec_id": spec.id,
                **index_result,
            })
        except Exception as exc:
            db.rollback()
            results.append({"file": filename, "ok": False, "error": str(exc)})

    ok_count = sum(1 for r in results if r["ok"])
    return templates.TemplateResponse(
        request,
        "admin/plan_bulk_upload.html",
        {
            "request": request,
            "title": "기획서 일괄 업로드",
            "known_apps": sorted({row for (row,) in db.execute(select(Spec.app_target).distinct()).all()}),
            "results": results,
            "ok_count": ok_count,
            "total": len(results),
            "app_target": app_key,
        },
        status_code=200,
    )


@router.post("/documents/urls")
async def bulk_register_urls(
    urls: list[str] = Body(...),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin_user),
):
    """Bulk register URLs as documents. Fetches text for each URL, saves as Spec, and enqueues indexing."""
    app_key = ""
    base_branch = "main"
    results = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            text = await fetch_url_as_text(url)
            if not text.strip():
                results.append({"url": url, "ok": False, "error": "URL 내용이 비어 있습니다"})
                continue
            spec = Spec(
                title=url,
                content=text,
                app_target=app_key,
                base_branch=(base_branch or "main").strip() or "main",
                related_files=[],
            )
            db.add(spec)
            db.flush()
            index_result = enqueue_or_index_sync(spec.id)
            db.commit()
            results.append({"url": url, "ok": True, "spec_id": spec.id, **index_result})
        except Exception as exc:
            db.rollback()
            results.append({"url": url, "ok": False, "error": str(exc)})

    ok_count = sum(1 for r in results if r["ok"])
    fail_count = len(results) - ok_count
    return JSONResponse({"ok_count": ok_count, "fail_count": fail_count, "results": results})


# ----- 기획서–코드 (연결 파일) -----


@router.get("/plan-code")
def plan_code_app_index(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "admin/spec_apps_cards.html",
        {
            "request": request,
            "title": "기획서–코드",
            "page_heading": "앱별 기획서 → 연결 코드",
            "nav_base": "plan-code",
            "cards": _spec_app_cards(db),
        },
    )


@router.get("/plan-code/app/{app_name}")
def plan_code_list_for_app(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.strip()
    rows = db.scalars(
        select(Spec)
        .where(Spec.app_target == key)
        .order_by(Spec.id.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "admin/spec_code_list_by_app.html",
        {
            "request": request,
            "title": f"기획서–코드 — {key}",
            "app_name": key,
            "app_enc": quote(key, safe=""),
            "rows": rows,
            "spec_display_title": spec_display_title,
        },
    )


@router.get("/plan-code/{spec_id:int}")
def plan_code_detail(
    request: Request,
    spec_id: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    row = db.get(Spec, spec_id)
    if row is None:
        raise HTTPException(404, "Not found")
    return templates.TemplateResponse(
        request,
        "admin/plan_code_detail.html",
        {
            "request": request,
            "title": f"연결 코드 — {spec_display_title(row)}",
            "row": row,
            "spec_display_title": spec_display_title,
            "app_enc": quote(row.app_target, safe=""),
        },
    )


# ----- Destructive re-seed -----


# ----- Rule 편의성 기능 (㉚ diff / ㉛ rollback / ㉜ export-import) -----


@router.get("/rules/{rule_id}/diff")
def rule_diff(
    rule_id: int,
    v1: int,
    v2: int,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin_user),
):
    """
    Return unified diff between two versions of a global rule.
    rule_id is accepted for API consistency but global rules use a single stream.
    Returns JSON: {"v1": int, "v2": int, "diff": str}
    """
    row1 = db.scalars(
        select(GlobalRuleVersion).where(GlobalRuleVersion.version == v1)
    ).first()
    row2 = db.scalars(
        select(GlobalRuleVersion).where(GlobalRuleVersion.version == v2)
    ).first()

    if row1 is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Global rule version {v1} not found")
    if row2 is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Global rule version {v2} not found")

    lines1 = row1.body.splitlines(keepends=True)
    lines2 = row2.body.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            lines1,
            lines2,
            fromfile=f"v{v1}",
            tofile=f"v{v2}",
        )
    )
    return JSONResponse({"v1": v1, "v2": v2, "diff": "".join(diff_lines)})


@router.post("/rules/{rule_id}/rollback")
def rule_rollback(
    rule_id: int,
    target_version: int = Body(..., embed=True),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin_user),
):
    """
    Roll back a global rule to a specific version by creating a new version
    with the content of the target version (append-only principle).
    """
    try:
        new_version = vr.rollback_global_rule(db, target_version)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return JSONResponse(
        {"ok": True, "rolled_back_to": target_version, "new_version": new_version}
    )


@router.get("/rules/export")
def export_rules(
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin_user),
):
    """Export all rules (global + app + repo latest versions) as JSON."""
    data = vr.export_rules_json(db)
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": "attachment; filename=rules_export.json"},
    )


@router.post("/rules/import")
async def import_rules(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin_user),
):
    """
    Import rules from a JSON export file.
    Expects the same structure produced by GET /admin/rules/export.
    Each rule type is published as a new version (append-only).
    """
    raw = await file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid JSON: {exc}") from exc

    results: dict[str, object] = {}

    # global
    global_section = data.get("global", {})
    global_body = (global_section.get("body") or "").strip() if isinstance(global_section, dict) else ""
    if global_body:
        new_gv = vr.publish_global(db, global_body)
        results["global"] = {"new_version": new_gv}

    # apps
    apps_imported: dict[str, int] = {}
    for app_name, info in (data.get("apps") or {}).items():
        body = (info.get("body") or "").strip() if isinstance(info, dict) else ""
        if not body:
            continue
        _, new_v = vr.publish_app(db, app_name, body)
        apps_imported[app_name] = new_v
    if apps_imported:
        results["apps"] = apps_imported

    # repos
    repos_imported: dict[str, int] = {}
    for pat_key, info in (data.get("repos") or {}).items():
        body = (info.get("body") or "").strip() if isinstance(info, dict) else ""
        if not body:
            continue
        pattern = "" if pat_key == "__default__" else pat_key
        _, new_v = vr.publish_repo(db, pattern, body)
        repos_imported[pat_key] = new_v
    if repos_imported:
        results["repos"] = repos_imported

    return JSONResponse({"ok": True, "imported": results})


@router.get("/seed/confirm")
def seed_confirm(
    request: Request,
    _user: str = Depends(require_admin_user),
):
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
    if confirm != "yes":
        raise HTTPException(400, 'Type "yes" in confirm field')
    seed_force(db)
    return RedirectResponse("/admin", status_code=303)
