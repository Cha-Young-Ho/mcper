"""Admin 규칙 관리 (글로벌, 앱, 레포, diff, rollback, export/import)."""

from __future__ import annotations

import difflib
import json
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.db.rule_models import (
    AppRuleVersion,
    GlobalRuleVersion,
    McpAppPullOption,
    RepoRuleVersion,
)
from app.routers.admin_base import _count, templates
from app.services import versioned_rules as vr

router = APIRouter(prefix="/admin", tags=["admin"])


# ----- 앱 추가 마법사 -----


@router.get("/apps/new")
def new_app_wizard_form(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """앱 + 레포 한 번에 추가하는 마법사 폼."""
    raw_patterns = _sort_repo_patterns(vr.list_distinct_repo_patterns(db))
    repo_options = [
        {
            "pattern": p,
            "display": vr.repo_pattern_card_display(p),
        }
        for p in raw_patterns
    ]
    return templates.TemplateResponse(
        request,
        "admin/app_new_wizard.html",
        {
            "request": request,
            "title": "앱 추가",
            "repo_options": repo_options,
            "error": None,
        },
    )


@router.post("/apps/new")
def new_app_wizard_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    repo_mode: str = Form(...),
    repo_existing: str = Form(""),
    repo_new_pattern: str = Form(""),
    app_name: str = Form(...),
    body: str = Form(...),
):
    """앱 추가 마법사 처리.

    - app_name 이미 존재 → 409 JSON (프론트에서 alert 표시)
    - repo 패턴 미존재 → 플레이스홀더 본문으로 신규 생성
    - app 신규 생성 후 앱 보드로 이동
    """
    app_key = app_name.strip().lower()
    if not app_key:
        return _wizard_error(request, db, "앱 이름은 필수입니다.")

    existing_app = db.scalars(
        select(AppRuleVersion).where(AppRuleVersion.app_name == app_key).limit(1)
    ).first()
    if existing_app is not None:
        return JSONResponse(
            {"error": "already_exists", "message": f"'{app_key}' 앱이 이미 존재합니다. 기존 앱 화면에서 새 버전을 추가하세요."},
            status_code=409,
        )

    repo_pattern = (repo_new_pattern if repo_mode == "new" else repo_existing).strip()

    if repo_mode == "new" and repo_pattern:
        exists_repo = db.scalars(
            select(RepoRuleVersion).where(RepoRuleVersion.pattern == repo_pattern).limit(1)
        ).first()
        if exists_repo is None:
            placeholder = f"# {repo_pattern}\n\n업무 지침 내용을 여기에 추가하세요.\n"
            vr.publish_repo(db, repo_pattern, placeholder)

    if not body.strip():
        return _wizard_error(request, db, "업무 지침 본문은 필수입니다.")

    vr.publish_app(db, app_key, body)
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(app_key, safe='')}/s/{vr.DEFAULT_SECTION}",
        status_code=303,
    )


def _wizard_error(request: Request, db: Session, error: str):
    """마법사 폼 오류 재표시 헬퍼."""
    raw_patterns = _sort_repo_patterns(vr.list_distinct_repo_patterns(db))
    repo_options = [
        {"pattern": p, "display": vr.repo_pattern_card_display(p)}
        for p in raw_patterns
    ]
    return templates.TemplateResponse(
        request,
        "admin/app_new_wizard.html",
        {
            "request": request,
            "title": "앱 추가",
            "repo_options": repo_options,
            "error": error,
        },
        status_code=400,
    )


# ----- Global rules (카테고리 지원) -----


@router.get("/global-rules")
def global_rules_board(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """글로벌 규칙 카테고리 오버뷰."""
    section_rows = vr._global_all_sections_latest(db)
    sections = []
    for r in section_rows:
        sections.append({
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/global-rules/s/{quote(r.section_name, safe='')}",
        })
    return templates.TemplateResponse(
        request,
        "admin/global_rules_board.html",
        {
            "request": request,
            "title": "Global rules",
            "sections": sections,
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


@router.get("/global-rules/s/new")
def global_category_new_form(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """글로벌 룰 새 카테고리 생성 폼."""
    existing_sections = vr.list_sections_for_global(db)
    return templates.TemplateResponse(
        request,
        "admin/global_rule_category_new.html",
        {
            "request": request,
            "title": "새 카테고리 — Global rules",
            "existing_sections": existing_sections,
            "error": None,
        },
    )


@router.post("/global-rules/s/new")
def global_category_new_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    section_name: str = Form(...),
    body: str = Form(...),
):
    """글로벌 룰 새 카테고리 첫 버전 생성."""
    sn = section_name.strip().lower()
    if not sn:
        existing_sections = vr.list_sections_for_global(db)
        return templates.TemplateResponse(
            request,
            "admin/global_rule_category_new.html",
            {
                "request": request,
                "title": "새 카테고리 — Global rules",
                "existing_sections": existing_sections,
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vr.list_sections_for_global(db)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {"error": "already_exists", "message": f"카테고리 '{sn}' 이 이미 존재합니다."},
            status_code=409,
        )
    nv = vr.publish_global(db, body, sn)
    return RedirectResponse(
        f"/admin/global-rules/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/global-rules/s/{section_name}")
def global_rule_category_board(
    request: Request,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """글로벌 룰 특정 카테고리의 버전 보드."""
    sn = section_name.strip()
    rows = db.scalars(
        select(GlobalRuleVersion)
        .where(GlobalRuleVersion.section_name == sn)
        .order_by(GlobalRuleVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")

    n_ver = len(rows)
    can_delete_section = sn != vr.DEFAULT_SECTION

    def _can_del_ver(_v: int) -> bool:
        if sn == vr.DEFAULT_SECTION:
            return n_ver > 1
        return n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/global_rule_category_board.html",
        {
            "request": request,
            "title": f"Global rules — {'기본' if sn == vr.DEFAULT_SECTION else sn}",
            "section_name": sn,
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del_ver,
        },
    )


@router.post("/global-rules/s/{section_name}/delete")
def global_rule_category_delete(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """글로벌 룰 카테고리 전체 삭제 (main 제외)."""
    sn = section_name.strip()
    if sn == vr.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    res = db.execute(
        delete(GlobalRuleVersion).where(GlobalRuleVersion.section_name == sn)
    )
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    return RedirectResponse("/admin/global-rules", status_code=303)


@router.get("/global-rules/s/{section_name}/publish")
def global_rule_category_publish_form(
    request: Request,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """글로벌 룰 카테고리별 새 버전 publish 폼."""
    sn = section_name.strip()
    latest = vr._global_latest(db, sn)
    next_v = vr.next_global_version(db, sn)
    return templates.TemplateResponse(
        request,
        "admin/global_rule_publish.html",
        {
            "request": request,
            "title": f"새 버전 — Global / {'기본' if sn == vr.DEFAULT_SECTION else sn}",
            "section_name": sn,
            "section_url_encoded": quote(sn, safe=""),
            "next_version": next_v,
            "prefill_body": latest.body if latest else "",
        },
    )


@router.post("/global-rules/s/{section_name}/publish")
def global_rule_category_publish_submit(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """글로벌 룰 카테고리별 새 버전 publish."""
    sn = section_name.strip()
    nv = vr.publish_global(db, body, sn)
    return RedirectResponse(
        f"/admin/global-rules/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.post("/global-rules/s/{section_name}/save-as-new")
def global_rule_category_save_as_new(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """버전 보기에서 수정한 내용을 카테고리 새 버전으로 저장."""
    sn = section_name.strip()
    nv = vr.publish_global(db, body, sn)
    return RedirectResponse(
        f"/admin/global-rules/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/global-rules/s/{section_name}/v/{version}")
def global_rule_category_version_view(
    request: Request,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """글로벌 룰 카테고리 특정 버전 조회."""
    sn = section_name.strip()
    row = db.scalars(
        select(GlobalRuleVersion).where(
            GlobalRuleVersion.section_name == sn,
            GlobalRuleVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(
            select(func.count()).where(GlobalRuleVersion.section_name == sn)
        ) or 0
    )
    can_delete_version = n > 1 if sn == vr.DEFAULT_SECTION else n >= 1
    return templates.TemplateResponse(
        request,
        "admin/global_rule_view.html",
        {
            "request": request,
            "title": f"Global / {'기본' if sn == vr.DEFAULT_SECTION else sn} — v{version}",
            "row": row,
            "section_name": sn,
            "section_url_encoded": quote(sn, safe=""),
            "can_delete_version": can_delete_version,
        },
    )


@router.post("/global-rules/s/{section_name}/v/{version}/delete")
def global_rule_category_version_delete(
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """글로벌 룰 카테고리 특정 버전 삭제."""
    sn = section_name.strip()
    n = int(
        db.scalar(select(func.count()).where(GlobalRuleVersion.section_name == sn)) or 0
    )
    if sn == vr.DEFAULT_SECTION and n <= 1:
        raise HTTPException(400, "기본(main) 카테고리는 최소 1개 버전이 필요합니다.")
    res = db.execute(
        delete(GlobalRuleVersion).where(
            and_(GlobalRuleVersion.section_name == sn, GlobalRuleVersion.version == version)
        )
    )
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "Not found")
    n_after = int(
        db.scalar(select(func.count()).where(GlobalRuleVersion.section_name == sn)) or 0
    )
    if n_after > 0:
        return RedirectResponse(
            f"/admin/global-rules/s/{quote(sn, safe='')}",
            status_code=303,
        )
    return RedirectResponse("/admin/global-rules", status_code=303)


# backward-compat: old global rule routes → main 카테고리 리다이렉트


@router.get("/global-rules/v/{version}")
def global_rule_view_legacy(version: int):
    """backward-compat: 섹션 없는 버전 조회 → main 카테고리로 리다이렉트."""
    return RedirectResponse(
        f"/admin/global-rules/s/{vr.DEFAULT_SECTION}/v/{version}",
        status_code=301,
    )


@router.post("/global-rules/v/{version}/delete")
def global_rule_delete_version_legacy(
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """backward-compat: main 카테고리 버전 삭제."""
    return global_rule_category_version_delete(vr.DEFAULT_SECTION, version, _user, db)


@router.post("/global-rules/publish")
def global_rule_publish_legacy(
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """backward-compat: main 카테고리로 publish."""
    nv = vr.publish_global(db, body, vr.DEFAULT_SECTION)
    return RedirectResponse(
        f"/admin/global-rules/s/{vr.DEFAULT_SECTION}/v/{nv}",
        status_code=303,
    )


@router.post("/global-rules/save-as-new")
def global_rule_save_as_new_legacy(
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """backward-compat: main 카테고리로 save-as-new."""
    nv = vr.publish_global(db, body, vr.DEFAULT_SECTION)
    return RedirectResponse(
        f"/admin/global-rules/s/{vr.DEFAULT_SECTION}/v/{nv}",
        status_code=303,
    )


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
    """앱 규칙 카드 목록."""
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


@router.get("/app-rules/new")
def new_app_form(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    """새 앱 규칙 생성 폼."""
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
    """새 앱 규칙 생성 처리."""
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
        f"/admin/app-rules/app/{quote(key, safe='')}/s/{vr.DEFAULT_SECTION}",
        status_code=303,
    )


@router.get("/app-rules/app/{app_name}")
def app_rule_board(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """앱 규칙 섹션 오버뷰 (섹션 카드 목록)."""
    key = app_name.lower().strip()
    # 앱 존재 확인
    any_row = db.scalars(
        select(AppRuleVersion).where(AppRuleVersion.app_name == key).limit(1)
    ).first()
    if not any_row:
        raise HTTPException(404, "Unknown app")

    # 모든 섹션의 최신 버전 행
    section_rows = vr._app_all_sections_latest(db, key)
    sections = []
    for r in section_rows:
        sections.append({
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/app-rules/app/{quote(key, safe='')}/s/{quote(r.section_name, safe='')}",
        })

    can_delete_stream = key != "__default__"
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
            "app_url_encoded": quote(key, safe=""),
            "sections": sections,
            "can_delete_stream": can_delete_stream,
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
    """이 앱으로 `get_global_rule` 호출 시 `__default__` 앱 스트림을 함께 내려줄지 (앱별)."""
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
def app_rule_delete_one_version_legacy(
    app_name: str,
    version: int,
):
    """backward-compat: 섹션 없는 버전 삭제 → main 섹션으로 리다이렉트."""
    key = app_name.lower().strip()
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}/s/{vr.DEFAULT_SECTION}/v/{version}/delete",
        status_code=307,
    )


@router.get("/app-rules/app/{app_name}/publish")
def app_rule_publish_form_legacy(
    app_name: str,
):
    """backward-compat: /publish → main 섹션 publish 폼으로 리다이렉트."""
    key = app_name.lower().strip()
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}/s/{vr.DEFAULT_SECTION}/publish",
        status_code=301,
    )


@router.post("/app-rules/app/{app_name}/publish")
def app_rule_publish_submit_legacy(
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """backward-compat: main 섹션으로 publish."""
    key = app_name.lower().strip()
    _, _sn, nv = vr.publish_app(db, key, body, vr.DEFAULT_SECTION)
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}/s/{vr.DEFAULT_SECTION}/v/{nv}",
        status_code=303,
    )


@router.post("/app-rules/app/{app_name}/save-as-new")
def app_rule_save_as_new_legacy(
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """backward-compat: main 섹션으로 save-as-new."""
    key = app_name.lower().strip()
    _, _sn, nv = vr.publish_app(db, key, body, vr.DEFAULT_SECTION)
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}/s/{vr.DEFAULT_SECTION}/v/{nv}",
        status_code=303,
    )


@router.get("/app-rules/app/{app_name}/v/{version}")
def app_rule_version_view_legacy(
    app_name: str,
    version: int,
):
    """backward-compat: 섹션 없는 버전 조회 → main 섹션으로 리다이렉트."""
    key = app_name.lower().strip()
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}/s/{vr.DEFAULT_SECTION}/v/{version}",
        status_code=301,
    )


# ── 앱 섹션 라우트 ─────────────────────────────────────────────────────────


@router.get("/app-rules/app/{app_name}/s/new")
def app_section_new_form(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """새 섹션 생성 폼."""
    key = app_name.lower().strip()
    if not db.scalars(
        select(AppRuleVersion).where(AppRuleVersion.app_name == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown app")
    existing_sections = vr.list_sections_for_app(db, key)
    return templates.TemplateResponse(
        request,
        "admin/rule_section_new.html",
        {
            "request": request,
            "title": f"새 카테고리 — {vr.app_rule_card_display_name(key)}",
            "app_name": key,
            "app_display": vr.app_rule_card_display_name(key),
            "app_url_encoded": quote(key, safe=""),
            "existing_sections": existing_sections,
            "error": None,
        },
    )


@router.post("/app-rules/app/{app_name}/s/new")
def app_section_new_submit(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    section_name: str = Form(...),
    body: str = Form(...),
):
    """새 카테고리 첫 버전 생성."""
    key = app_name.lower().strip()
    sn = section_name.strip().lower()
    if not sn:
        existing_sections = vr.list_sections_for_app(db, key)
        return templates.TemplateResponse(
            request,
            "admin/rule_section_new.html",
            {
                "request": request,
                "title": f"새 카테고리 — {vr.app_rule_card_display_name(key)}",
                "app_name": key,
                "app_display": vr.app_rule_card_display_name(key),
                "app_url_encoded": quote(key, safe=""),
                "existing_sections": existing_sections,
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vr.list_sections_for_app(db, key)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {"error": "already_exists", "message": f"카테고리 '{sn}' 이 이미 존재합니다. 기존 카테고리에서 새 버전을 추가하세요."},
            status_code=409,
        )
    _, _sn, nv = vr.publish_app(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/app-rules/app/{app_name}/s/{section_name}")
def app_rule_section_board(
    request: Request,
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """앱 규칙 특정 섹션의 버전 보드."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    rows = db.scalars(
        select(AppRuleVersion)
        .where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.section_name == sn,
        )
        .order_by(AppRuleVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")

    n_ver = len(rows)
    can_delete_stream = key != "__default__"
    can_delete_section = sn != vr.DEFAULT_SECTION

    def _can_del_ver(_v: int) -> bool:
        if key == "__default__" and sn == vr.DEFAULT_SECTION:
            return n_ver > 1
        return n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/app_rule_section_board.html",
        {
            "request": request,
            "title": f"App: {vr.app_rule_card_display_name(key)} — {'기본' if sn == vr.DEFAULT_SECTION else sn}",
            "app_name": key,
            "app_display": vr.app_rule_card_display_name(key),
            "section_name": sn,
            "app_url_encoded": quote(key, safe=""),
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_stream": can_delete_stream,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del_ver,
        },
    )


@router.post("/app-rules/app/{app_name}/s/{section_name}/delete")
def app_rule_section_delete(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """섹션 전체 삭제 (main 섹션 제외)."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    if sn == vr.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    res = db.execute(
        delete(AppRuleVersion).where(
            and_(AppRuleVersion.app_name == key, AppRuleVersion.section_name == sn)
        )
    )
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}",
        status_code=303,
    )


@router.get("/app-rules/app/{app_name}/s/{section_name}/publish")
def app_rule_section_publish_form(
    request: Request,
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """섹션별 새 버전 publish 폼."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    latest = vr._app_latest(db, key, sn)
    next_v = vr.next_app_version(db, key, sn)
    return templates.TemplateResponse(
        request,
        "admin/app_rule_publish.html",
        {
            "request": request,
            "title": f"새 버전 — {key} / {sn}",
            "app_name": key,
            "section_name": sn,
            "next_version": next_v,
            "app_url_encoded": quote(key, safe=""),
            "section_url_encoded": quote(sn, safe=""),
            "prefill_body": latest.body if latest else "",
        },
    )


@router.post("/app-rules/app/{app_name}/s/{section_name}/publish")
def app_rule_section_publish_submit(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """섹션별 새 버전 publish."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    _, _sn, nv = vr.publish_app(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.post("/app-rules/app/{app_name}/s/{section_name}/save-as-new")
def app_rule_section_save_as_new(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """버전 보기에서 수정한 내용을 섹션 새 버전으로 저장."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    _, _sn, nv = vr.publish_app(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/app-rules/app/{app_name}/s/{section_name}/v/{version}")
def app_rule_section_version_view(
    request: Request,
    app_name: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """앱 규칙 섹션 특정 버전 조회."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    row = db.scalars(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.section_name == sn,
            AppRuleVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(
            select(func.count()).where(
                AppRuleVersion.app_name == key,
                AppRuleVersion.section_name == sn,
            )
        ) or 0
    )
    can_delete_version = n >= 1 and (
        (key != "__default__" or sn != vr.DEFAULT_SECTION) or n > 1
    )
    return templates.TemplateResponse(
        request,
        "admin/app_rule_version_view.html",
        {
            "request": request,
            "title": f"{key} / {sn} — version {version}",
            "row": row,
            "app_name": key,
            "section_name": sn,
            "app_url_encoded": quote(key, safe=""),
            "section_url_encoded": quote(sn, safe=""),
            "can_delete_version": can_delete_version,
        },
    )


@router.post("/app-rules/app/{app_name}/s/{section_name}/v/{version}/delete")
def app_rule_section_version_delete(
    app_name: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """앱 규칙 섹션 특정 버전 삭제."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    n = int(
        db.scalar(
            select(func.count()).where(
                AppRuleVersion.app_name == key,
                AppRuleVersion.section_name == sn,
            )
        ) or 0
    )
    if key == "__default__" and sn == vr.DEFAULT_SECTION and n <= 1:
        raise HTTPException(400, "default 앱 기본(main) 카테고리는 최소 1개 버전이 필요합니다.")
    res = db.execute(
        delete(AppRuleVersion).where(
            and_(
                AppRuleVersion.app_name == key,
                AppRuleVersion.section_name == sn,
                AppRuleVersion.version == version,
            )
        )
    )
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "Not found")
    n_after = int(
        db.scalar(
            select(func.count()).where(
                AppRuleVersion.app_name == key,
                AppRuleVersion.section_name == sn,
            )
        ) or 0
    )
    if n_after > 0:
        return RedirectResponse(
            f"/admin/app-rules/app/{quote(key, safe='')}/s/{quote(sn, safe='')}",
            status_code=303,
        )
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}",
        status_code=303,
    )


# ----- Repository rules (URL 패턴별) -----


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


@router.get("/repo-rules")
def repo_rules_cards(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    q: str = "",
):
    """레포 규칙 카드 목록."""
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
    """새 레포 패턴 규칙 생성 폼."""
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
    """새 레포 패턴 규칙 생성 처리."""
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
    """레포 규칙 카테고리 오버뷰."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    any_row = db.scalars(
        select(RepoRuleVersion).where(RepoRuleVersion.pattern == key).limit(1)
    ).first()
    if not any_row:
        raise HTTPException(404, "Unknown repository pattern")
    pat_url = vr.repo_pat_href_segment(key)
    display = vr.repo_pattern_card_display(key)
    can_delete_stream = (key or "").strip() != ""

    section_rows = vr._repo_all_sections_latest_for_pattern(db, key)
    sections = []
    for r in section_rows:
        sn_url = quote(r.section_name, safe="")
        sections.append({
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/repo-rules/pat/{pat_url}/s/{sn_url}",
        })

    return templates.TemplateResponse(
        request,
        "admin/repo_rule_board.html",
        {
            "request": request,
            "title": f"Repo: {display}",
            "pattern": key,
            "pattern_display": display,
            "sections": sections,
            "pat_url": pat_url,
            "can_delete_stream": can_delete_stream,
        },
    )


@router.post("/repo-rules/pat/{pat_segment}/delete")
def repo_rule_delete_pattern_stream(
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """레포 규칙 패턴 전체 삭제."""
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


# ── 레포 카테고리 라우트 ────────────────────────────────────────────────────


@router.get("/repo-rules/pat/{pat_segment}/s/new")
def repo_category_new_form(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """레포 룰 새 카테고리 생성 폼."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    if not db.scalars(
        select(RepoRuleVersion).where(RepoRuleVersion.pattern == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown repository pattern")
    pat_url = vr.repo_pat_href_segment(key)
    display = vr.repo_pattern_card_display(key)
    existing_sections = vr.list_sections_for_repo(db, key)
    return templates.TemplateResponse(
        request,
        "admin/repo_rule_category_new.html",
        {
            "request": request,
            "title": f"새 카테고리 — {display}",
            "pattern": key,
            "pattern_display": display,
            "pat_url": pat_url,
            "existing_sections": existing_sections,
            "error": None,
        },
    )


@router.post("/repo-rules/pat/{pat_segment}/s/new")
def repo_category_new_submit(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    section_name: str = Form(...),
    body: str = Form(...),
):
    """레포 룰 새 카테고리 첫 버전 생성."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    pat_url = vr.repo_pat_href_segment(key)
    display = vr.repo_pattern_card_display(key)
    sn = section_name.strip().lower()
    if not sn:
        existing_sections = vr.list_sections_for_repo(db, key)
        return templates.TemplateResponse(
            request,
            "admin/repo_rule_category_new.html",
            {
                "request": request,
                "title": f"새 카테고리 — {display}",
                "pattern": key,
                "pattern_display": display,
                "pat_url": pat_url,
                "existing_sections": existing_sections,
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vr.list_sections_for_repo(db, key)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {"error": "already_exists", "message": f"카테고리 '{sn}' 이 이미 존재합니다."},
            status_code=409,
        )
    _, _sn, nv = vr.publish_repo(db, key, body, section_name=sn)
    return RedirectResponse(
        f"/admin/repo-rules/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/repo-rules/pat/{pat_segment}/s/{section_name}")
def repo_rule_category_board(
    request: Request,
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """레포 룰 특정 카테고리의 버전 보드."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    rows = db.scalars(
        select(RepoRuleVersion)
        .where(RepoRuleVersion.pattern == key, RepoRuleVersion.section_name == sn)
        .order_by(RepoRuleVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")
    pat_url = vr.repo_pat_href_segment(key)
    display = vr.repo_pattern_card_display(key)
    can_delete_stream = (key or "").strip() != ""
    can_delete_section = sn != vr.DEFAULT_SECTION
    n_ver = len(rows)

    def _can_del_ver(_v: int) -> bool:
        if not (key or "").strip() and sn == vr.DEFAULT_SECTION:
            return n_ver > 1
        return n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/repo_rule_category_board.html",
        {
            "request": request,
            "title": f"Repo: {display} — {'기본' if sn == vr.DEFAULT_SECTION else sn}",
            "pattern": key,
            "pattern_display": display,
            "section_name": sn,
            "pat_url": pat_url,
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_stream": can_delete_stream,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del_ver,
        },
    )


@router.post("/repo-rules/pat/{pat_segment}/s/{section_name}/delete")
def repo_rule_category_delete(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """레포 룰 카테고리 전체 삭제 (main 제외)."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    if sn == vr.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    res = db.execute(
        delete(RepoRuleVersion).where(
            and_(RepoRuleVersion.pattern == key, RepoRuleVersion.section_name == sn)
        )
    )
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    pat_url = vr.repo_pat_href_segment(key)
    return RedirectResponse(f"/admin/repo-rules/pat/{pat_url}", status_code=303)


@router.get("/repo-rules/pat/{pat_segment}/s/{section_name}/publish")
def repo_rule_category_publish_form(
    request: Request,
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """레포 룰 카테고리별 새 버전 publish 폼."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vr.repo_pat_href_segment(key)
    display = vr.repo_pattern_card_display(key)
    latest = vr._repo_latest_for_pattern(db, key, sn)
    next_v = vr.next_repo_version(db, key, sn)
    return templates.TemplateResponse(
        request,
        "admin/repo_rule_publish.html",
        {
            "request": request,
            "title": f"새 버전 — {display} / {'기본' if sn == vr.DEFAULT_SECTION else sn}",
            "pattern": key,
            "pattern_display": display,
            "section_name": sn,
            "section_url_encoded": quote(sn, safe=""),
            "next_version": next_v,
            "pat_url": pat_url,
            "prefill_body": latest.body if latest else "",
        },
    )


@router.post("/repo-rules/pat/{pat_segment}/s/{section_name}/publish")
def repo_rule_category_publish_submit(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """레포 룰 카테고리별 새 버전 publish."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    _, _sn, nv = vr.publish_repo(db, key, body, section_name=sn)
    pat_url = vr.repo_pat_href_segment(key)
    return RedirectResponse(
        f"/admin/repo-rules/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.post("/repo-rules/pat/{pat_segment}/s/{section_name}/save-as-new")
def repo_rule_category_save_as_new(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    """버전 보기에서 수정한 내용을 카테고리 새 버전으로 저장."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    _, _sn, nv = vr.publish_repo(db, key, body, section_name=sn)
    pat_url = vr.repo_pat_href_segment(key)
    return RedirectResponse(
        f"/admin/repo-rules/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/repo-rules/pat/{pat_segment}/s/{section_name}/v/{version}")
def repo_rule_category_version_view(
    request: Request,
    pat_segment: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """레포 룰 카테고리 특정 버전 조회."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    row = db.scalars(
        select(RepoRuleVersion).where(
            RepoRuleVersion.pattern == key,
            RepoRuleVersion.section_name == sn,
            RepoRuleVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(
            select(func.count()).where(
                RepoRuleVersion.pattern == key,
                RepoRuleVersion.section_name == sn,
            )
        ) or 0
    )
    can_delete_version = n >= 1 and (
        (key or "").strip() != "" or sn != vr.DEFAULT_SECTION or n > 1
    )
    pat_url = vr.repo_pat_href_segment(key)
    display = vr.repo_pattern_card_display(key)
    return templates.TemplateResponse(
        request,
        "admin/repo_rule_version_view.html",
        {
            "request": request,
            "title": f"{display} / {'기본' if sn == vr.DEFAULT_SECTION else sn} — v{version}",
            "row": row,
            "pattern": key,
            "pattern_display": display,
            "section_name": sn,
            "section_url_encoded": quote(sn, safe=""),
            "pat_url": pat_url,
            "can_delete_version": can_delete_version,
        },
    )


@router.post("/repo-rules/pat/{pat_segment}/s/{section_name}/v/{version}/delete")
def repo_rule_category_version_delete(
    pat_segment: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """레포 룰 카테고리 특정 버전 삭제."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    n = int(
        db.scalar(
            select(func.count()).where(
                RepoRuleVersion.pattern == key,
                RepoRuleVersion.section_name == sn,
            )
        ) or 0
    )
    if not (key or "").strip() and sn == vr.DEFAULT_SECTION and n <= 1:
        raise HTTPException(400, "default 패턴 기본 카테고리는 최소 1개 버전이 필요합니다.")
    res = db.execute(
        delete(RepoRuleVersion).where(
            and_(
                RepoRuleVersion.pattern == key,
                RepoRuleVersion.section_name == sn,
                RepoRuleVersion.version == version,
            )
        )
    )
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "Not found")
    n_after = int(
        db.scalar(
            select(func.count()).where(
                RepoRuleVersion.pattern == key,
                RepoRuleVersion.section_name == sn,
            )
        ) or 0
    )
    pat_url = vr.repo_pat_href_segment(key)
    if n_after > 0:
        return RedirectResponse(
            f"/admin/repo-rules/pat/{pat_url}/s/{quote(sn, safe='')}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/repo-rules/pat/{pat_url}", status_code=303)


# backward-compat: 섹션 없는 레포 버전 라우트 → main 카테고리 리다이렉트


@router.post("/repo-rules/pat/{pat_segment}/v/{version}/delete")
def repo_rule_delete_one_version_legacy(
    pat_segment: str,
    version: int,
):
    """backward-compat: 섹션 없는 버전 삭제 → main 카테고리로."""
    pat_url = pat_segment
    return RedirectResponse(
        f"/admin/repo-rules/pat/{pat_url}/s/{vr.DEFAULT_SECTION}/v/{version}/delete",
        status_code=307,
    )


@router.get("/repo-rules/pat/{pat_segment}/publish")
def repo_rule_publish_form_legacy(pat_segment: str):
    """backward-compat: /publish → main 카테고리 publish 폼."""
    return RedirectResponse(
        f"/admin/repo-rules/pat/{pat_segment}/s/{vr.DEFAULT_SECTION}/publish",
        status_code=301,
    )


@router.post("/repo-rules/pat/{pat_segment}/publish")
def repo_rule_publish_submit_legacy(
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
    section_name: str = Form(vr.DEFAULT_SECTION),
):
    """backward-compat: main 카테고리로 publish."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = (section_name or vr.DEFAULT_SECTION).strip()
    _, _sn, nv = vr.publish_repo(db, key, body, section_name=sn)
    pat_url = vr.repo_pat_href_segment(key)
    return RedirectResponse(
        f"/admin/repo-rules/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.post("/repo-rules/pat/{pat_segment}/save-as-new")
def repo_rule_save_as_new_legacy(
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
    section_name: str = Form(vr.DEFAULT_SECTION),
):
    """backward-compat: main 카테고리로 save-as-new."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = (section_name or vr.DEFAULT_SECTION).strip()
    _, _sn, nv = vr.publish_repo(db, key, body, section_name=sn)
    pat_url = vr.repo_pat_href_segment(key)
    return RedirectResponse(
        f"/admin/repo-rules/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/repo-rules/pat/{pat_segment}/v/{version}")
def repo_rule_version_view_legacy(pat_segment: str, version: int):
    """backward-compat: 섹션 없는 버전 조회 → main 카테고리로 리다이렉트."""
    return RedirectResponse(
        f"/admin/repo-rules/pat/{pat_segment}/s/{vr.DEFAULT_SECTION}/v/{version}",
        status_code=301,
    )


# ----- Rule 편의성 기능 (diff / rollback / export-import) -----


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

    # apps (섹션별 import 지원: {"app_name": {"main": {"body": ...}, "admin_rules": {...}}})
    apps_imported: dict[str, object] = {}
    for app_name, info in (data.get("apps") or {}).items():
        if isinstance(info, dict):
            # new format: {section_name: {version, body}}
            sections_in = {k: v for k, v in info.items() if isinstance(v, dict) and v.get("body")}
            if sections_in:
                for sn, sinfo in sections_in.items():
                    body = (sinfo.get("body") or "").strip()
                    if body:
                        _, _sn, new_v = vr.publish_app(db, app_name, body, sn)
                apps_imported[app_name] = {sn: new_v for sn, sinfo in sections_in.items() if sinfo.get("body")}
            else:
                # legacy format: {body: ...}
                body = (info.get("body") or "").strip()
                if body:
                    _, _sn, new_v = vr.publish_app(db, app_name, body)
                    apps_imported[app_name] = new_v
    if apps_imported:
        results["apps"] = apps_imported

    # repos (섹션별 import 지원)
    repos_imported: dict[str, object] = {}
    for pat_key, info in (data.get("repos") or {}).items():
        pattern = "" if pat_key == "__default__" else pat_key
        if isinstance(info, dict):
            sections_in = {k: v for k, v in info.items() if isinstance(v, dict) and v.get("body")}
            if sections_in:
                for sn, sinfo in sections_in.items():
                    body = (sinfo.get("body") or "").strip()
                    if body:
                        _, _sn, new_v = vr.publish_repo(db, pattern, body, section_name=sn)
                repos_imported[pat_key] = {sn: new_v for sn, sinfo in sections_in.items() if sinfo.get("body")}
            else:
                body = (info.get("body") or "").strip()
                if body:
                    _, _sn, new_v = vr.publish_repo(db, pattern, body)
                    repos_imported[pat_key] = new_v
    if repos_imported:
        results["repos"] = repos_imported

    return JSONResponse({"ok": True, "imported": results})
