"""Admin 스킬(Skills) 관리 — Global / App / Repo 카테고리별 CRUD."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.db.skill_models import AppSkillVersion, GlobalSkillVersion, RepoSkillVersion
from app.routers.admin_base import DOMAIN_CONFIG, templates
from app.routers.admin_common import (
    _sort_app_names,
    _sort_repo_patterns,
    _section_display as _section_display_base,
)
from app.services import versioned_skills as vs

router = APIRouter(prefix="/admin", tags=["admin-skills"])


def _section_display(sn: str) -> str:
    """섹션 표시명: DEFAULT_SECTION 이면 '기본', 아니면 원본."""
    return _section_display_base(sn, vs.DEFAULT_SECTION)


# ── 개발 도메인 허브 ──────────────────────────────────────────────────────────


@router.get("/skills-dev")
def skills_dev_hub(
    request: Request,
    _user: str = Depends(require_admin_user),
) -> Response:
    """개발 도메인 스킬 허브 (Global / Repository / App 선택)."""
    return templates.TemplateResponse(
        request,
        "admin/skills_dev_hub.html",
        {"request": request, "title": "스킬 — 개발"},
    )


# ── Global skills ────────────────────────────────────────────────────────────


@router.get("/global-skills")
def global_skills_board(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    domain: str = "",
) -> Response:
    """글로벌 스킬 오버뷰 (카테고리 카드 목록)."""
    domain_filter = domain.strip() or None
    section_rows = vs._global_skill_all_sections_latest(db, domain=domain_filter)
    sections = [
        {
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/global-skills/s/{quote(r.section_name, safe='')}",
        }
        for r in section_rows
    ]
    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/skills/global_skills_board.html",
        {
            "request": request,
            "title": f"Global 스킬 — {domain_cfg['display']}"
            if domain_cfg
            else "Global 스킬",
            "sections": sections,
            "domain": domain_filter or "",
        },
    )


@router.get("/global-skills/s/new")
def global_skill_category_new_form(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """글로벌 스킬 새 카테고리 생성 폼."""
    return templates.TemplateResponse(
        request,
        "admin/skills/category_new.html",
        {
            "request": request,
            "title": "새 카테고리 — Global 스킬",
            "existing_sections": vs.list_sections_for_global_skill(db),
            "form_action": "/admin/global-skills/s/new",
            "cancel_url": "/admin/global-skills",
            "error": None,
        },
    )


@router.post("/global-skills/s/new")
def global_skill_category_new_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    section_name: str = Form(...),
    body: str = Form(...),
) -> Response:
    """글로벌 스킬 새 카테고리 첫 버전 생성."""
    sn = section_name.strip().lower()
    if not sn:
        return templates.TemplateResponse(
            request,
            "admin/skills/category_new.html",
            {
                "request": request,
                "title": "새 카테고리 — Global 스킬",
                "existing_sections": vs.list_sections_for_global_skill(db),
                "form_action": "/admin/global-skills/s/new",
                "cancel_url": "/admin/global-skills",
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vs.list_sections_for_global_skill(db)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {
                "error": "already_exists",
                "message": f"카테고리 '{sn}' 이 이미 존재합니다.",
            },
            status_code=409,
        )
    nv = vs.publish_global_skill(db, body, sn)
    return RedirectResponse(
        f"/admin/global-skills/s/{quote(sn, safe='')}/v/{nv}", status_code=303
    )


@router.get("/global-skills/s/{section_name}")
def global_skill_category_board(
    request: Request,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """글로벌 스킬 오버뷰 (카테고리 카드 목록)."""
    sn = section_name.strip()
    rows = db.scalars(
        select(GlobalSkillVersion)
        .where(GlobalSkillVersion.section_name == sn)
        .order_by(GlobalSkillVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")
    n_ver = len(rows)
    can_delete_section = sn != vs.DEFAULT_SECTION

    def _can_del(v: int) -> bool:
        return n_ver > 1 if sn == vs.DEFAULT_SECTION else n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/skills/category_board.html",
        {
            "request": request,
            "title": f"Global 스킬 — {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del,
            "breadcrumb_home": "/admin/global-skills",
            "breadcrumb_home_label": "Global 스킬",
            "publish_url": f"/admin/global-skills/s/{quote(sn, safe='')}/publish",
            "delete_section_url": f"/admin/global-skills/s/{quote(sn, safe='')}/delete",
            "version_view_base": f"/admin/global-skills/s/{quote(sn, safe='')}/v",
        },
    )


@router.post("/global-skills/s/{section_name}/delete")
def global_skill_category_delete(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """글로벌 스킬 카테고리 전체 삭제 (main 제외)."""
    sn = section_name.strip()
    if sn == vs.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    if vs.delete_global_skill_section(db, sn) == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    return RedirectResponse("/admin/global-skills", status_code=303)


@router.get("/global-skills/s/{section_name}/publish")
def global_skill_category_publish_form(
    request: Request,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """글로벌 스킬 카테고리별 새 버전 publish 폼."""
    sn = section_name.strip()
    latest = vs._global_skill_latest(db, sn)
    return templates.TemplateResponse(
        request,
        "admin/skills/version_publish.html",
        {
            "request": request,
            "title": f"새 버전 — Global / {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "next_version": vs.next_global_skill_version(db, sn),
            "prefill_body": latest.body if latest else "",
            "form_action": f"/admin/global-skills/s/{quote(sn, safe='')}/publish",
            "cancel_url": f"/admin/global-skills/s/{quote(sn, safe='')}",
        },
    )


@router.post("/global-skills/s/{section_name}/publish")
def global_skill_category_publish_submit(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
) -> Response:
    """글로벌 스킬 카테고리별 새 버전 publish."""
    sn = section_name.strip()
    nv = vs.publish_global_skill(db, body, sn)
    return RedirectResponse(
        f"/admin/global-skills/s/{quote(sn, safe='')}/v/{nv}", status_code=303
    )


@router.post("/global-skills/s/{section_name}/save-as-new")
def global_skill_save_as_new(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
) -> Response:
    sn = section_name.strip()
    nv = vs.publish_global_skill(db, body, sn)
    return RedirectResponse(
        f"/admin/global-skills/s/{quote(sn, safe='')}/v/{nv}", status_code=303
    )


@router.get("/global-skills/s/{section_name}/v/{version}")
def global_skill_version_view(
    request: Request,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    sn = section_name.strip()
    row = db.scalars(
        select(GlobalSkillVersion).where(
            GlobalSkillVersion.section_name == sn,
            GlobalSkillVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(select(func.count()).where(GlobalSkillVersion.section_name == sn))
        or 0
    )
    can_delete = n > 1 if sn == vs.DEFAULT_SECTION else n >= 1
    return templates.TemplateResponse(
        request,
        "admin/skills/version_view.html",
        {
            "request": request,
            "title": f"Global / {_section_display(sn)} — v{version}",
            "row": row,
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "can_delete_version": can_delete,
            "save_as_new_url": f"/admin/global-skills/s/{quote(sn, safe='')}/save-as-new",
            "delete_version_url": f"/admin/global-skills/s/{quote(sn, safe='')}/v/{version}/delete",
            "back_url": f"/admin/global-skills/s/{quote(sn, safe='')}",
            "back_label": f"Global 스킬 / {_section_display(sn)}",
        },
    )


@router.post("/global-skills/s/{section_name}/v/{version}/delete")
def global_skill_version_delete(
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    sn = section_name.strip()
    n = int(
        db.scalar(select(func.count()).where(GlobalSkillVersion.section_name == sn))
        or 0
    )
    if sn == vs.DEFAULT_SECTION and n <= 1:
        raise HTTPException(400, "기본(main) 카테고리는 최소 1개 버전이 필요합니다.")
    vs.delete_global_skill_version(db, sn, version)
    n_after = int(
        db.scalar(select(func.count()).where(GlobalSkillVersion.section_name == sn))
        or 0
    )
    if n_after > 0:
        return RedirectResponse(
            f"/admin/global-skills/s/{quote(sn, safe='')}", status_code=303
        )
    return RedirectResponse("/admin/global-skills", status_code=303)


# ── App skills ────────────────────────────────────────────────────────────────


@router.get("/app-skills")
def app_skills_cards(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    q: str = "",
    domain: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Response:
    """앱 스킬 카드 목록 (서버사이드 페이지네이션: limit/offset)."""
    domain_filter = domain.strip() or None
    all_names = _sort_app_names(
        vs.list_distinct_apps_with_skills(db, domain=domain_filter)
    )
    if q.strip():
        all_names = [n for n in all_names if q.strip().lower() in n.lower()]

    total = (
        len(all_names)
        if q.strip()
        else vs.count_distinct_apps_with_skills(db, domain=domain_filter)
    )
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    names = all_names[offset : offset + limit]

    cards: list[dict] = []
    for name in names:
        latest = db.scalars(
            select(AppSkillVersion)
            .where(AppSkillVersion.app_name == name)
            .order_by(AppSkillVersion.version.desc())
            .limit(1)
        ).first()
        if latest is None:
            continue
        cards.append(
            {
                "name": name,
                "display": name,
                "latest_version": latest.version,
                "app_url_encoded": quote(name, safe=""),
                "url": f"/admin/app-skills/app/{quote(name, safe='')}",
                "can_delete_stream": True,
            }
        )

    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/skills/app_skills_cards.html",
        {
            "request": request,
            "title": f"App 스킬 — {domain_cfg['display']}"
            if domain_cfg
            else "App 스킬",
            "cards": cards,
            "q": q,
            "domain": domain_filter or "",
            "page_limit": limit,
            "page_offset": offset,
            "page_total": total,
            "has_prev": offset > 0,
            "has_next": offset + limit < total,
            "prev_offset": max(0, offset - limit),
            "next_offset": offset + limit,
        },
    )


@router.get("/app-skills/new")
def new_app_skill_form(
    request: Request,
    _user: str = Depends(require_admin_user),
) -> Response:
    """새 앱 스킬 생성 폼."""
    return templates.TemplateResponse(
        request,
        "admin/skills/app_skill_new.html",
        {"request": request, "title": "새 앱 스킬", "error": None},
    )


@router.post("/app-skills/new")
def new_app_skill_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    app_name: str = Form(...),
    body: str = Form(...),
) -> Response:
    """새 앱 스킬 생성 처리."""
    key = app_name.strip().lower()
    if not key:
        return templates.TemplateResponse(
            request,
            "admin/skills/app_skill_new.html",
            {
                "request": request,
                "title": "새 앱 스킬",
                "error": "앱 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = db.scalars(
        select(AppSkillVersion).where(AppSkillVersion.app_name == key).limit(1)
    ).first()
    if existing is not None:
        return JSONResponse(
            {"error": "already_exists", "message": f"'{key}' 앱이 이미 존재합니다."},
            status_code=409,
        )
    vs.publish_app_skill(db, key, body)
    return RedirectResponse(
        f"/admin/app-skills/app/{quote(key, safe='')}/s/{vs.DEFAULT_SECTION}",
        status_code=303,
    )


@router.get("/app-skills/app/{app_name}")
def app_skill_board(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """스킬 앱의 섹션 오버뷰."""
    key = app_name.lower().strip()
    if not db.scalars(
        select(AppSkillVersion).where(AppSkillVersion.app_name == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown app")
    section_rows = vs._app_skill_all_sections_latest(db, key)
    sections = [
        {
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(r.section_name, safe='')}",
        }
        for r in section_rows
    ]
    return templates.TemplateResponse(
        request,
        "admin/skills/app_skill_board.html",
        {
            "request": request,
            "title": f"App 스킬: {key}",
            "app_name": key,
            "app_display": key,
            "app_url_encoded": quote(key, safe=""),
            "sections": sections,
            "can_delete_stream": True,
        },
    )


@router.post("/app-skills/app/{app_name}/delete")
def app_skill_delete_stream(
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """앱 전체 스트림 삭제."""
    key = app_name.lower().strip()
    if vs.delete_app_skill_stream(db, key) == 0:
        raise HTTPException(404, "삭제할 항목이 없습니다.")
    return RedirectResponse("/admin/app-skills", status_code=303)


@router.get("/app-skills/app/{app_name}/s/new")
def app_skill_category_new_form(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    key = app_name.lower().strip()
    if not db.scalars(
        select(AppSkillVersion).where(AppSkillVersion.app_name == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown app")
    return templates.TemplateResponse(
        request,
        "admin/skills/category_new.html",
        {
            "request": request,
            "title": f"새 카테고리 — {key} 스킬",
            "existing_sections": vs.list_sections_for_app_skill(db, key),
            "form_action": f"/admin/app-skills/app/{quote(key, safe='')}/s/new",
            "cancel_url": f"/admin/app-skills/app/{quote(key, safe='')}",
            "error": None,
        },
    )


@router.post("/app-skills/app/{app_name}/s/new")
def app_skill_category_new_submit(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    section_name: str = Form(...),
    body: str = Form(...),
) -> Response:
    key = app_name.lower().strip()
    sn = section_name.strip().lower()
    if not sn:
        return templates.TemplateResponse(
            request,
            "admin/skills/category_new.html",
            {
                "request": request,
                "title": f"새 카테고리 — {key} 스킬",
                "existing_sections": vs.list_sections_for_app_skill(db, key),
                "form_action": f"/admin/app-skills/app/{quote(key, safe='')}/s/new",
                "cancel_url": f"/admin/app-skills/app/{quote(key, safe='')}",
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vs.list_sections_for_app_skill(db, key)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {
                "error": "already_exists",
                "message": f"카테고리 '{sn}' 이 이미 존재합니다.",
            },
            status_code=409,
        )
    _, _sn, nv = vs.publish_app_skill(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/app-skills/app/{app_name}/s/{section_name}")
def app_skill_category_board(
    request: Request,
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """스킬 앱의 섹션 오버뷰."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    rows = db.scalars(
        select(AppSkillVersion)
        .where(AppSkillVersion.app_name == key, AppSkillVersion.section_name == sn)
        .order_by(AppSkillVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")
    n_ver = len(rows)
    can_delete_section = sn != vs.DEFAULT_SECTION

    def _can_del(v: int) -> bool:
        return n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/skills/category_board.html",
        {
            "request": request,
            "title": f"App 스킬: {key} — {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del,
            "breadcrumb_home": f"/admin/app-skills/app/{quote(key, safe='')}",
            "breadcrumb_home_label": f"App 스킬: {key}",
            "publish_url": f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/publish",
            "delete_section_url": f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/delete",
            "version_view_base": f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v",
        },
    )


@router.post("/app-skills/app/{app_name}/s/{section_name}/delete")
def app_skill_category_delete(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    key = app_name.lower().strip()
    sn = section_name.strip()
    if sn == vs.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    if vs.delete_app_skill_section(db, key, sn) == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    return RedirectResponse(
        f"/admin/app-skills/app/{quote(key, safe='')}", status_code=303
    )


@router.get("/app-skills/app/{app_name}/s/{section_name}/publish")
def app_skill_category_publish_form(
    request: Request,
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    key = app_name.lower().strip()
    sn = section_name.strip()
    latest = vs._app_skill_latest(db, key, sn)
    return templates.TemplateResponse(
        request,
        "admin/skills/version_publish.html",
        {
            "request": request,
            "title": f"새 버전 — {key} / {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "next_version": vs.next_app_skill_version(db, key, sn),
            "prefill_body": latest.body if latest else "",
            "form_action": f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/publish",
            "cancel_url": f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}",
        },
    )


@router.post("/app-skills/app/{app_name}/s/{section_name}/publish")
def app_skill_category_publish_submit(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
) -> Response:
    key = app_name.lower().strip()
    sn = section_name.strip()
    _, _sn, nv = vs.publish_app_skill(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.post("/app-skills/app/{app_name}/s/{section_name}/save-as-new")
def app_skill_save_as_new(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
) -> Response:
    key = app_name.lower().strip()
    sn = section_name.strip()
    _, _sn, nv = vs.publish_app_skill(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/app-skills/app/{app_name}/s/{section_name}/v/{version}")
def app_skill_version_view(
    request: Request,
    app_name: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    key = app_name.lower().strip()
    sn = section_name.strip()
    row = db.scalars(
        select(AppSkillVersion).where(
            AppSkillVersion.app_name == key,
            AppSkillVersion.section_name == sn,
            AppSkillVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(
            select(func.count()).where(
                AppSkillVersion.app_name == key,
                AppSkillVersion.section_name == sn,
            )
        )
        or 0
    )
    return templates.TemplateResponse(
        request,
        "admin/skills/version_view.html",
        {
            "request": request,
            "title": f"{key} / {_section_display(sn)} — v{version}",
            "row": row,
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "can_delete_version": n >= 1,
            "save_as_new_url": f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/save-as-new",
            "delete_version_url": f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{version}/delete",
            "back_url": f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}",
            "back_label": f"{key} / {_section_display(sn)}",
        },
    )


@router.post("/app-skills/app/{app_name}/s/{section_name}/v/{version}/delete")
def app_skill_version_delete(
    app_name: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    key = app_name.lower().strip()
    sn = section_name.strip()
    vs.delete_app_skill_version(db, key, sn, version)
    n_after = int(
        db.scalar(
            select(func.count()).where(
                AppSkillVersion.app_name == key,
                AppSkillVersion.section_name == sn,
            )
        )
        or 0
    )
    if n_after > 0:
        return RedirectResponse(
            f"/admin/app-skills/app/{quote(key, safe='')}/s/{quote(sn, safe='')}",
            status_code=303,
        )
    return RedirectResponse(
        f"/admin/app-skills/app/{quote(key, safe='')}", status_code=303
    )


# ── Repo skills ───────────────────────────────────────────────────────────────


@router.get("/repo-skills")
def repo_skills_cards(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    q: str = "",
    domain: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Response:
    """레포 스킬 카드 목록 (서버사이드 페이지네이션: limit/offset)."""
    domain_filter = domain.strip() or None
    all_patterns = _sort_repo_patterns(
        vs.list_distinct_repo_patterns_with_skills(db, domain=domain_filter)
    )
    if q.strip():
        qn = q.strip().lower()
        all_patterns = [p for p in all_patterns if qn in (p or "").lower()]

    total = (
        len(all_patterns)
        if q.strip()
        else vs.count_distinct_repo_patterns_with_skills(db, domain=domain_filter)
    )
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    patterns = all_patterns[offset : offset + limit]

    cards: list[dict] = []
    for pat in patterns:
        latest = db.scalars(
            select(RepoSkillVersion)
            .where(RepoSkillVersion.pattern == pat)
            .order_by(RepoSkillVersion.version.desc())
            .limit(1)
        ).first()
        if latest is None:
            continue
        seg = vs.repo_skill_pat_href_segment(pat)
        cards.append(
            {
                "pattern": pat,
                "display": vs.repo_skill_pattern_card_display(pat),
                "is_default": not (pat or "").strip(),
                "can_delete_stream": bool((pat or "").strip()),
                "latest_version": latest.version,
                "url": f"/admin/repo-skills/pat/{seg}",
                "pat_segment": seg,
            }
        )

    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/skills/repo_skills_cards.html",
        {
            "request": request,
            "title": f"Repository 스킬 — {domain_cfg['display']}"
            if domain_cfg
            else "Repository 스킬",
            "cards": cards,
            "q": q,
            "domain": domain_filter or "",
            "page_limit": limit,
            "page_offset": offset,
            "page_total": total,
            "has_prev": offset > 0,
            "has_next": offset + limit < total,
            "prev_offset": max(0, offset - limit),
            "next_offset": offset + limit,
        },
    )


@router.get("/repo-skills/new")
def new_repo_skill_form(
    request: Request,
    _user: str = Depends(require_admin_user),
) -> Response:
    return templates.TemplateResponse(
        request,
        "admin/skills/repo_skill_new.html",
        {"request": request, "title": "새 Repository 패턴 스킬", "error": None},
    )


@router.post("/repo-skills/new")
def new_repo_skill_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    pattern: str = Form(...),
    body: str = Form(...),
) -> Response:
    key = pattern.strip()
    existing = db.scalars(
        select(RepoSkillVersion).where(RepoSkillVersion.pattern == key).limit(1)
    ).first()
    if existing is not None:
        return templates.TemplateResponse(
            request,
            "admin/skills/repo_skill_new.html",
            {
                "request": request,
                "title": "새 Repository 패턴 스킬",
                "error": f"이미 존재하는 패턴: {key or '(기본)'}",
            },
            status_code=400,
        )
    vs.publish_repo_skill(db, key, body)
    seg = vs.repo_skill_pat_href_segment(key)
    return RedirectResponse(f"/admin/repo-skills/pat/{seg}", status_code=303)


@router.get("/repo-skills/pat/{pat_segment}")
def repo_skill_board(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """스킬 레포 패턴 섹션 오버뷰."""
    key = vs.repo_skill_pattern_from_url_segment(pat_segment)
    if not db.scalars(
        select(RepoSkillVersion).where(RepoSkillVersion.pattern == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown repository pattern")
    pat_url = vs.repo_skill_pat_href_segment(key)
    display = vs.repo_skill_pattern_card_display(key)
    can_delete_stream = bool((key or "").strip())
    section_rows = vs._repo_skill_all_sections_latest(db, key)
    sections = [
        {
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/repo-skills/pat/{pat_url}/s/{quote(r.section_name, safe='')}",
        }
        for r in section_rows
    ]
    return templates.TemplateResponse(
        request,
        "admin/skills/repo_skill_board.html",
        {
            "request": request,
            "title": f"Repo 스킬: {display}",
            "pattern": key,
            "pattern_display": display,
            "sections": sections,
            "pat_url": pat_url,
            "can_delete_stream": can_delete_stream,
        },
    )


@router.post("/repo-skills/pat/{pat_segment}/delete")
def repo_skill_delete_stream(
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    key = vs.repo_skill_pattern_from_url_segment(pat_segment)
    if not (key or "").strip():
        raise HTTPException(400, "default 패턴은 삭제할 수 없습니다.")
    if vs.delete_repo_skill_stream(db, key) == 0:
        raise HTTPException(404, "삭제할 항목이 없습니다.")
    return RedirectResponse("/admin/repo-skills", status_code=303)


@router.get("/repo-skills/pat/{pat_segment}/s/new")
def repo_skill_category_new_form(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """레포 스킬 새 카테고리 생성 폼."""
    key = vs.repo_skill_pattern_from_url_segment(pat_segment)
    pat_url = vs.repo_skill_pat_href_segment(key)
    display = vs.repo_skill_pattern_card_display(key)
    return templates.TemplateResponse(
        request,
        "admin/skills/category_new.html",
        {
            "request": request,
            "title": f"새 카테고리 — {display} 스킬",
            "existing_sections": vs.list_sections_for_repo_skill(db, key),
            "form_action": f"/admin/repo-skills/pat/{pat_url}/s/new",
            "cancel_url": f"/admin/repo-skills/pat/{pat_url}",
            "error": None,
        },
    )


@router.post("/repo-skills/pat/{pat_segment}/s/new")
def repo_skill_category_new_submit(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    section_name: str = Form(...),
    body: str = Form(...),
) -> Response:
    """레포 스킬 새 카테고리 첫 버전 생성."""
    key = vs.repo_skill_pattern_from_url_segment(pat_segment)
    pat_url = vs.repo_skill_pat_href_segment(key)
    sn = section_name.strip().lower()
    if not sn:
        return templates.TemplateResponse(
            request,
            "admin/skills/category_new.html",
            {
                "request": request,
                "title": f"새 카테고리 — {vs.repo_skill_pattern_card_display(key)} 스킬",
                "existing_sections": vs.list_sections_for_repo_skill(db, key),
                "form_action": f"/admin/repo-skills/pat/{pat_url}/s/new",
                "cancel_url": f"/admin/repo-skills/pat/{pat_url}",
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vs.list_sections_for_repo_skill(db, key)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {
                "error": "already_exists",
                "message": f"카테고리 '{sn}' 이 이미 존재합니다.",
            },
            status_code=409,
        )
    _, _sn, nv = vs.publish_repo_skill(db, key, body, sn)
    return RedirectResponse(
        f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/repo-skills/pat/{pat_segment}/s/{section_name}")
def repo_skill_category_board(
    request: Request,
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """스킬 레포 패턴 섹션 오버뷰."""
    key = vs.repo_skill_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vs.repo_skill_pat_href_segment(key)
    display = vs.repo_skill_pattern_card_display(key)
    rows = db.scalars(
        select(RepoSkillVersion)
        .where(RepoSkillVersion.pattern == key, RepoSkillVersion.section_name == sn)
        .order_by(RepoSkillVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")
    n_ver = len(rows)
    can_delete_section = sn != vs.DEFAULT_SECTION

    def _can_del(v: int) -> bool:
        if not (key or "").strip() and sn == vs.DEFAULT_SECTION:
            return n_ver > 1
        return n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/skills/category_board.html",
        {
            "request": request,
            "title": f"Repo 스킬: {display} — {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del,
            "breadcrumb_home": f"/admin/repo-skills/pat/{pat_url}",
            "breadcrumb_home_label": f"Repo 스킬: {display}",
            "publish_url": f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}/publish",
            "delete_section_url": f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}/delete",
            "version_view_base": f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}/v",
        },
    )


@router.post("/repo-skills/pat/{pat_segment}/s/{section_name}/delete")
def repo_skill_category_delete(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """레포 스킬 카테고리 전체 삭제 (main 제외)."""
    key = vs.repo_skill_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vs.repo_skill_pat_href_segment(key)
    if sn == vs.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    if vs.delete_repo_skill_section(db, key, sn) == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    return RedirectResponse(f"/admin/repo-skills/pat/{pat_url}", status_code=303)


@router.get("/repo-skills/pat/{pat_segment}/s/{section_name}/publish")
def repo_skill_category_publish_form(
    request: Request,
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """레포 스킬 카테고리별 새 버전 publish 폼."""
    key = vs.repo_skill_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vs.repo_skill_pat_href_segment(key)
    latest = vs._repo_skill_latest(db, key, sn)
    return templates.TemplateResponse(
        request,
        "admin/skills/version_publish.html",
        {
            "request": request,
            "title": f"새 버전 — {vs.repo_skill_pattern_card_display(key)} / {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "next_version": vs.next_repo_skill_version(db, key, sn),
            "prefill_body": latest.body if latest else "",
            "form_action": f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}/publish",
            "cancel_url": f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}",
        },
    )


@router.post("/repo-skills/pat/{pat_segment}/s/{section_name}/publish")
def repo_skill_category_publish_submit(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
) -> Response:
    """레포 스킬 카테고리별 새 버전 publish."""
    key = vs.repo_skill_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vs.repo_skill_pat_href_segment(key)
    _, _sn, nv = vs.publish_repo_skill(db, key, body, sn)
    return RedirectResponse(
        f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.post("/repo-skills/pat/{pat_segment}/s/{section_name}/save-as-new")
def repo_skill_save_as_new(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
) -> Response:
    key = vs.repo_skill_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vs.repo_skill_pat_href_segment(key)
    _, _sn, nv = vs.publish_repo_skill(db, key, body, sn)
    return RedirectResponse(
        f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/repo-skills/pat/{pat_segment}/s/{section_name}/v/{version}")
def repo_skill_version_view(
    request: Request,
    pat_segment: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    key = vs.repo_skill_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vs.repo_skill_pat_href_segment(key)
    display = vs.repo_skill_pattern_card_display(key)
    row = db.scalars(
        select(RepoSkillVersion).where(
            RepoSkillVersion.pattern == key,
            RepoSkillVersion.section_name == sn,
            RepoSkillVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(
            select(func.count()).where(
                RepoSkillVersion.pattern == key,
                RepoSkillVersion.section_name == sn,
            )
        )
        or 0
    )
    can_delete = (
        n > 1 if (not (key or "").strip() and sn == vs.DEFAULT_SECTION) else n >= 1
    )
    return templates.TemplateResponse(
        request,
        "admin/skills/version_view.html",
        {
            "request": request,
            "title": f"{display} / {_section_display(sn)} — v{version}",
            "row": row,
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "can_delete_version": can_delete,
            "save_as_new_url": f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}/save-as-new",
            "delete_version_url": f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}/v/{version}/delete",
            "back_url": f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}",
            "back_label": f"{display} / {_section_display(sn)}",
        },
    )


@router.post("/repo-skills/pat/{pat_segment}/s/{section_name}/v/{version}/delete")
def repo_skill_version_delete(
    pat_segment: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    key = vs.repo_skill_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vs.repo_skill_pat_href_segment(key)
    n = int(
        db.scalar(
            select(func.count()).where(
                RepoSkillVersion.pattern == key,
                RepoSkillVersion.section_name == sn,
            )
        )
        or 0
    )
    if not (key or "").strip() and sn == vs.DEFAULT_SECTION and n <= 1:
        raise HTTPException(
            400, "default 패턴 기본 카테고리는 최소 1개 버전이 필요합니다."
        )
    vs.delete_repo_skill_version(db, key, sn, version)
    n_after = int(
        db.scalar(
            select(func.count()).where(
                RepoSkillVersion.pattern == key,
                RepoSkillVersion.section_name == sn,
            )
        )
        or 0
    )
    if n_after > 0:
        return RedirectResponse(
            f"/admin/repo-skills/pat/{pat_url}/s/{quote(sn, safe='')}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/repo-skills/pat/{pat_url}", status_code=303)
