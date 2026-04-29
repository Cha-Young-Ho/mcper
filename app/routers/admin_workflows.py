"""Admin 워크플로우(Workflows) 관리 — Global / App / Repo 카테고리별 CRUD."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.db.workflow_models import AppWorkflowVersion, GlobalWorkflowVersion, RepoWorkflowVersion
from app.routers.admin_base import DOMAIN_CONFIG, templates
from app.routers.admin_common import _sort_app_names, _sort_repo_patterns, _section_display as _section_display_base
from app.services import versioned_workflows as vw

router = APIRouter(prefix="/admin", tags=["admin-workflows"])


def _section_display(sn: str) -> str:
    return _section_display_base(sn, vw.DEFAULT_SECTION)


# ── 개발 도메인 허브 ──────────────────────────────────────────────────────────


@router.get("/workflows-dev")
def workflows_dev_hub(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    """개발 도메인 워크플로우 허브 (Global / Repository / App 선택)."""
    return templates.TemplateResponse(
        request,
        "admin/workflows_hub.html",
        {"request": request, "title": "워크플로우 — 개발"},
    )


# ── Global workflows ────────────────────────────────────────────────────────


@router.get("/global-workflows")
def global_workflows_board(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    domain: str = "",
):
    domain_filter = domain.strip() or None
    section_rows = vw._global_workflow_all_sections_latest(db, domain=domain_filter)
    sections = [
        {
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/global-workflows/s/{quote(r.section_name, safe='')}",
        }
        for r in section_rows
    ]
    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/workflows/global_workflows_board.html",
        {
            "request": request,
            "title": f"Global 워크플로우 — {domain_cfg['display']}" if domain_cfg else "Global 워크플로우",
            "sections": sections,
            "domain": domain_filter or "",
        },
    )


@router.get("/global-workflows/s/new")
def global_workflow_category_new_form(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "admin/workflows/category_new.html",
        {
            "request": request,
            "title": "새 카테고리 — Global 워크플로우",
            "existing_sections": vw.list_sections_for_global_workflow(db),
            "form_action": "/admin/global-workflows/s/new",
            "cancel_url": "/admin/global-workflows",
            "error": None,
        },
    )


@router.post("/global-workflows/s/new")
def global_workflow_category_new_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    section_name: str = Form(...),
    body: str = Form(...),
):
    sn = section_name.strip().lower()
    if not sn:
        return templates.TemplateResponse(
            request,
            "admin/workflows/category_new.html",
            {
                "request": request,
                "title": "새 카테고리 — Global 워크플로우",
                "existing_sections": vw.list_sections_for_global_workflow(db),
                "form_action": "/admin/global-workflows/s/new",
                "cancel_url": "/admin/global-workflows",
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vw.list_sections_for_global_workflow(db)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {"error": "already_exists", "message": f"카테고리 '{sn}' 이 이미 존재합니다."},
            status_code=409,
        )
    nv = vw.publish_global_workflow(db, body, sn)
    return RedirectResponse(f"/admin/global-workflows/s/{quote(sn, safe='')}/v/{nv}", status_code=303)


@router.get("/global-workflows/s/{section_name}")
def global_workflow_category_board(
    request: Request,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    sn = section_name.strip()
    rows = db.scalars(
        select(GlobalWorkflowVersion)
        .where(GlobalWorkflowVersion.section_name == sn)
        .order_by(GlobalWorkflowVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")
    n_ver = len(rows)
    can_delete_section = sn != vw.DEFAULT_SECTION

    def _can_del(v: int) -> bool:
        return n_ver > 1 if sn == vw.DEFAULT_SECTION else n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/workflows/category_board.html",
        {
            "request": request,
            "title": f"Global 워크플로우 — {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del,
            "breadcrumb_home": "/admin/global-workflows",
            "breadcrumb_home_label": "Global 워크플로우",
            "publish_url": f"/admin/global-workflows/s/{quote(sn, safe='')}/publish",
            "delete_section_url": f"/admin/global-workflows/s/{quote(sn, safe='')}/delete",
            "version_view_base": f"/admin/global-workflows/s/{quote(sn, safe='')}/v",
        },
    )


@router.post("/global-workflows/s/{section_name}/delete")
def global_workflow_category_delete(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    sn = section_name.strip()
    if sn == vw.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    if vw.delete_global_workflow_section(db, sn) == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    return RedirectResponse("/admin/global-workflows", status_code=303)


@router.get("/global-workflows/s/{section_name}/publish")
def global_workflow_category_publish_form(
    request: Request,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    sn = section_name.strip()
    latest = vw._global_workflow_latest(db, sn)
    return templates.TemplateResponse(
        request,
        "admin/workflows/version_publish.html",
        {
            "request": request,
            "title": f"새 버전 — Global / {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "next_version": vw.next_global_workflow_version(db, sn),
            "prefill_body": latest.body if latest else "",
            "form_action": f"/admin/global-workflows/s/{quote(sn, safe='')}/publish",
            "cancel_url": f"/admin/global-workflows/s/{quote(sn, safe='')}",
        },
    )


@router.post("/global-workflows/s/{section_name}/publish")
def global_workflow_category_publish_submit(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    sn = section_name.strip()
    nv = vw.publish_global_workflow(db, body, sn)
    return RedirectResponse(f"/admin/global-workflows/s/{quote(sn, safe='')}/v/{nv}", status_code=303)


@router.post("/global-workflows/s/{section_name}/save-as-new")
def global_workflow_save_as_new(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    sn = section_name.strip()
    nv = vw.publish_global_workflow(db, body, sn)
    return RedirectResponse(f"/admin/global-workflows/s/{quote(sn, safe='')}/v/{nv}", status_code=303)


@router.get("/global-workflows/s/{section_name}/v/{version}")
def global_workflow_version_view(
    request: Request,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    sn = section_name.strip()
    row = db.scalars(
        select(GlobalWorkflowVersion).where(
            GlobalWorkflowVersion.section_name == sn,
            GlobalWorkflowVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(db.scalar(select(func.count()).where(GlobalWorkflowVersion.section_name == sn)) or 0)
    can_delete = n > 1 if sn == vw.DEFAULT_SECTION else n >= 1
    return templates.TemplateResponse(
        request,
        "admin/workflows/version_view.html",
        {
            "request": request,
            "title": f"Global / {_section_display(sn)} — v{version}",
            "row": row,
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "can_delete_version": can_delete,
            "save_as_new_url": f"/admin/global-workflows/s/{quote(sn, safe='')}/save-as-new",
            "delete_version_url": f"/admin/global-workflows/s/{quote(sn, safe='')}/v/{version}/delete",
            "back_url": f"/admin/global-workflows/s/{quote(sn, safe='')}",
            "back_label": f"Global 워크플로우 / {_section_display(sn)}",
        },
    )


@router.post("/global-workflows/s/{section_name}/v/{version}/delete")
def global_workflow_version_delete(
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    sn = section_name.strip()
    n = int(db.scalar(select(func.count()).where(GlobalWorkflowVersion.section_name == sn)) or 0)
    if sn == vw.DEFAULT_SECTION and n <= 1:
        raise HTTPException(400, "기본(main) 카테고리는 최소 1개 버전이 필요합니다.")
    vw.delete_global_workflow_version(db, sn, version)
    n_after = int(db.scalar(select(func.count()).where(GlobalWorkflowVersion.section_name == sn)) or 0)
    if n_after > 0:
        return RedirectResponse(f"/admin/global-workflows/s/{quote(sn, safe='')}", status_code=303)
    return RedirectResponse("/admin/global-workflows", status_code=303)


# ── App workflows ────────────────────────────────────────────────────────────


@router.get("/app-workflows")
def app_workflows_cards(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    q: str = "",
    domain: str = "",
    limit: int = 50,
    offset: int = 0,
):
    """앱 워크플로우 카드 목록 (서버사이드 페이지네이션: limit/offset)."""
    domain_filter = domain.strip() or None
    all_names = _sort_app_names(vw.list_distinct_apps_with_workflows(db, domain=domain_filter))
    if q.strip():
        all_names = [n for n in all_names if q.strip().lower() in n.lower()]

    total = len(all_names) if q.strip() else vw.count_distinct_apps_with_workflows(db, domain=domain_filter)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    names = all_names[offset : offset + limit]

    cards: list[dict] = []
    for name in names:
        latest = db.scalars(
            select(AppWorkflowVersion)
            .where(AppWorkflowVersion.app_name == name)
            .order_by(AppWorkflowVersion.version.desc())
            .limit(1)
        ).first()
        if latest is None:
            continue
        cards.append({
            "name": name,
            "display": name,
            "latest_version": latest.version,
            "app_url_encoded": quote(name, safe=""),
            "url": f"/admin/app-workflows/app/{quote(name, safe='')}",
            "can_delete_stream": True,
        })

    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/workflows/app_workflows_cards.html",
        {
            "request": request,
            "title": f"App 워크플로우 — {domain_cfg['display']}" if domain_cfg else "App 워크플로우",
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


@router.get("/app-workflows/new")
def new_app_workflow_form(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    return templates.TemplateResponse(
        request,
        "admin/workflows/app_workflow_new.html",
        {"request": request, "title": "새 앱 워크플로우", "error": None},
    )


@router.post("/app-workflows/new")
def new_app_workflow_submit(
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
            "admin/workflows/app_workflow_new.html",
            {"request": request, "title": "새 앱 워크플로우", "error": "앱 이름은 필수입니다."},
            status_code=400,
        )
    existing = db.scalars(select(AppWorkflowVersion).where(AppWorkflowVersion.app_name == key).limit(1)).first()
    if existing is not None:
        return JSONResponse(
            {"error": "already_exists", "message": f"'{key}' 앱이 이미 존재합니다."},
            status_code=409,
        )
    vw.publish_app_workflow(db, key, body)
    return RedirectResponse(
        f"/admin/app-workflows/app/{quote(key, safe='')}/s/{vw.DEFAULT_SECTION}",
        status_code=303,
    )


@router.get("/app-workflows/app/{app_name}")
def app_workflow_board(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    if not db.scalars(select(AppWorkflowVersion).where(AppWorkflowVersion.app_name == key).limit(1)).first():
        raise HTTPException(404, "Unknown app")
    section_rows = vw._app_workflow_all_sections_latest(db, key)
    sections = [
        {
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(r.section_name, safe='')}",
        }
        for r in section_rows
    ]
    return templates.TemplateResponse(
        request,
        "admin/workflows/app_workflow_board.html",
        {
            "request": request,
            "title": f"App 워크플로우: {key}",
            "app_name": key,
            "app_display": key,
            "app_url_encoded": quote(key, safe=""),
            "sections": sections,
            "can_delete_stream": True,
        },
    )


@router.post("/app-workflows/app/{app_name}/delete")
def app_workflow_delete_stream(
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    if vw.delete_app_workflow_stream(db, key) == 0:
        raise HTTPException(404, "삭제할 항목이 없습니다.")
    return RedirectResponse("/admin/app-workflows", status_code=303)


@router.get("/app-workflows/app/{app_name}/s/new")
def app_workflow_category_new_form(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    if not db.scalars(select(AppWorkflowVersion).where(AppWorkflowVersion.app_name == key).limit(1)).first():
        raise HTTPException(404, "Unknown app")
    return templates.TemplateResponse(
        request,
        "admin/workflows/category_new.html",
        {
            "request": request,
            "title": f"새 카테고리 — {key} 워크플로우",
            "existing_sections": vw.list_sections_for_app_workflow(db, key),
            "form_action": f"/admin/app-workflows/app/{quote(key, safe='')}/s/new",
            "cancel_url": f"/admin/app-workflows/app/{quote(key, safe='')}",
            "error": None,
        },
    )


@router.post("/app-workflows/app/{app_name}/s/new")
def app_workflow_category_new_submit(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    section_name: str = Form(...),
    body: str = Form(...),
):
    key = app_name.lower().strip()
    sn = section_name.strip().lower()
    if not sn:
        return templates.TemplateResponse(
            request,
            "admin/workflows/category_new.html",
            {
                "request": request,
                "title": f"새 카테고리 — {key} 워크플로우",
                "existing_sections": vw.list_sections_for_app_workflow(db, key),
                "form_action": f"/admin/app-workflows/app/{quote(key, safe='')}/s/new",
                "cancel_url": f"/admin/app-workflows/app/{quote(key, safe='')}",
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vw.list_sections_for_app_workflow(db, key)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {"error": "already_exists", "message": f"카테고리 '{sn}' 이 이미 존재합니다."},
            status_code=409,
        )
    _, _sn, nv = vw.publish_app_workflow(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/app-workflows/app/{app_name}/s/{section_name}")
def app_workflow_category_board(
    request: Request,
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    rows = db.scalars(
        select(AppWorkflowVersion)
        .where(AppWorkflowVersion.app_name == key, AppWorkflowVersion.section_name == sn)
        .order_by(AppWorkflowVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")
    n_ver = len(rows)
    can_delete_section = sn != vw.DEFAULT_SECTION

    def _can_del(v: int) -> bool:
        return n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/workflows/category_board.html",
        {
            "request": request,
            "title": f"App 워크플로우: {key} — {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del,
            "breadcrumb_home": f"/admin/app-workflows/app/{quote(key, safe='')}",
            "breadcrumb_home_label": f"App 워크플로우: {key}",
            "publish_url": f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/publish",
            "delete_section_url": f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/delete",
            "version_view_base": f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v",
        },
    )


@router.post("/app-workflows/app/{app_name}/s/{section_name}/delete")
def app_workflow_category_delete(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    if sn == vw.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    if vw.delete_app_workflow_section(db, key, sn) == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    return RedirectResponse(f"/admin/app-workflows/app/{quote(key, safe='')}", status_code=303)


@router.get("/app-workflows/app/{app_name}/s/{section_name}/publish")
def app_workflow_category_publish_form(
    request: Request,
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    latest = vw._app_workflow_latest(db, key, sn)
    return templates.TemplateResponse(
        request,
        "admin/workflows/version_publish.html",
        {
            "request": request,
            "title": f"새 버전 — {key} / {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "next_version": vw.next_app_workflow_version(db, key, sn),
            "prefill_body": latest.body if latest else "",
            "form_action": f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/publish",
            "cancel_url": f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}",
        },
    )


@router.post("/app-workflows/app/{app_name}/s/{section_name}/publish")
def app_workflow_category_publish_submit(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    _, _sn, nv = vw.publish_app_workflow(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.post("/app-workflows/app/{app_name}/s/{section_name}/save-as-new")
def app_workflow_save_as_new(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    _, _sn, nv = vw.publish_app_workflow(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/app-workflows/app/{app_name}/s/{section_name}/v/{version}")
def app_workflow_version_view(
    request: Request,
    app_name: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    row = db.scalars(
        select(AppWorkflowVersion).where(
            AppWorkflowVersion.app_name == key,
            AppWorkflowVersion.section_name == sn,
            AppWorkflowVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(
            select(func.count()).where(
                AppWorkflowVersion.app_name == key,
                AppWorkflowVersion.section_name == sn,
            )
        ) or 0
    )
    return templates.TemplateResponse(
        request,
        "admin/workflows/version_view.html",
        {
            "request": request,
            "title": f"{key} / {_section_display(sn)} — v{version}",
            "row": row,
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "can_delete_version": n >= 1,
            "save_as_new_url": f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/save-as-new",
            "delete_version_url": f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{version}/delete",
            "back_url": f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}",
            "back_label": f"{key} / {_section_display(sn)}",
        },
    )


@router.post("/app-workflows/app/{app_name}/s/{section_name}/v/{version}/delete")
def app_workflow_version_delete(
    app_name: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    vw.delete_app_workflow_version(db, key, sn, version)
    n_after = int(
        db.scalar(
            select(func.count()).where(
                AppWorkflowVersion.app_name == key,
                AppWorkflowVersion.section_name == sn,
            )
        ) or 0
    )
    if n_after > 0:
        return RedirectResponse(
            f"/admin/app-workflows/app/{quote(key, safe='')}/s/{quote(sn, safe='')}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/app-workflows/app/{quote(key, safe='')}", status_code=303)


# ── Repo workflows ───────────────────────────────────────────────────────────


@router.get("/repo-workflows")
def repo_workflows_cards(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    q: str = "",
    domain: str = "",
    limit: int = 50,
    offset: int = 0,
):
    """레포 워크플로우 카드 목록 (서버사이드 페이지네이션: limit/offset)."""
    domain_filter = domain.strip() or None
    all_patterns = _sort_repo_patterns(vw.list_distinct_repo_patterns_with_workflows(db, domain=domain_filter))
    if q.strip():
        qn = q.strip().lower()
        all_patterns = [p for p in all_patterns if qn in (p or "").lower()]

    total = len(all_patterns) if q.strip() else vw.count_distinct_repo_patterns_with_workflows(db, domain=domain_filter)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    patterns = all_patterns[offset : offset + limit]

    cards: list[dict] = []
    for pat in patterns:
        latest = db.scalars(
            select(RepoWorkflowVersion)
            .where(RepoWorkflowVersion.pattern == pat)
            .order_by(RepoWorkflowVersion.version.desc())
            .limit(1)
        ).first()
        if latest is None:
            continue
        seg = vw.repo_workflow_pat_href_segment(pat)
        cards.append({
            "pattern": pat,
            "display": vw.repo_workflow_pattern_card_display(pat),
            "is_default": not (pat or "").strip(),
            "can_delete_stream": bool((pat or "").strip()),
            "latest_version": latest.version,
            "url": f"/admin/repo-workflows/pat/{seg}",
            "pat_segment": seg,
        })

    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/workflows/repo_workflows_cards.html",
        {
            "request": request,
            "title": f"Repository 워크플로우 — {domain_cfg['display']}" if domain_cfg else "Repository 워크플로우",
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


@router.get("/repo-workflows/new")
def new_repo_workflow_form(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    return templates.TemplateResponse(
        request,
        "admin/workflows/repo_workflow_new.html",
        {"request": request, "title": "새 Repository 패턴 워크플로우", "error": None},
    )


@router.post("/repo-workflows/new")
def new_repo_workflow_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    pattern: str = Form(...),
    body: str = Form(...),
):
    key = pattern.strip()
    existing = db.scalars(select(RepoWorkflowVersion).where(RepoWorkflowVersion.pattern == key).limit(1)).first()
    if existing is not None:
        return templates.TemplateResponse(
            request,
            "admin/workflows/repo_workflow_new.html",
            {"request": request, "title": "새 Repository 패턴 워크플로우",
             "error": f"이미 존재하는 패턴: {key or '(기본)'}"},
            status_code=400,
        )
    vw.publish_repo_workflow(db, key, body)
    seg = vw.repo_workflow_pat_href_segment(key)
    return RedirectResponse(f"/admin/repo-workflows/pat/{seg}", status_code=303)


@router.get("/repo-workflows/pat/{pat_segment}")
def repo_workflow_board(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_workflow_pattern_from_url_segment(pat_segment)
    if not db.scalars(select(RepoWorkflowVersion).where(RepoWorkflowVersion.pattern == key).limit(1)).first():
        raise HTTPException(404, "Unknown repository pattern")
    pat_url = vw.repo_workflow_pat_href_segment(key)
    display = vw.repo_workflow_pattern_card_display(key)
    can_delete_stream = bool((key or "").strip())
    section_rows = vw._repo_workflow_all_sections_latest(db, key)
    sections = [
        {
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/repo-workflows/pat/{pat_url}/s/{quote(r.section_name, safe='')}",
        }
        for r in section_rows
    ]
    return templates.TemplateResponse(
        request,
        "admin/workflows/repo_workflow_board.html",
        {
            "request": request,
            "title": f"Repo 워크플로우: {display}",
            "pattern": key,
            "pattern_display": display,
            "sections": sections,
            "pat_url": pat_url,
            "can_delete_stream": can_delete_stream,
        },
    )


@router.post("/repo-workflows/pat/{pat_segment}/delete")
def repo_workflow_delete_stream(
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_workflow_pattern_from_url_segment(pat_segment)
    if not (key or "").strip():
        raise HTTPException(400, "default 패턴은 삭제할 수 없습니다.")
    if vw.delete_repo_workflow_stream(db, key) == 0:
        raise HTTPException(404, "삭제할 항목이 없습니다.")
    return RedirectResponse("/admin/repo-workflows", status_code=303)


@router.get("/repo-workflows/pat/{pat_segment}/s/new")
def repo_workflow_category_new_form(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_workflow_pattern_from_url_segment(pat_segment)
    pat_url = vw.repo_workflow_pat_href_segment(key)
    display = vw.repo_workflow_pattern_card_display(key)
    return templates.TemplateResponse(
        request,
        "admin/workflows/category_new.html",
        {
            "request": request,
            "title": f"새 카테고리 — {display} 워크플로우",
            "existing_sections": vw.list_sections_for_repo_workflow(db, key),
            "form_action": f"/admin/repo-workflows/pat/{pat_url}/s/new",
            "cancel_url": f"/admin/repo-workflows/pat/{pat_url}",
            "error": None,
        },
    )


@router.post("/repo-workflows/pat/{pat_segment}/s/new")
def repo_workflow_category_new_submit(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    section_name: str = Form(...),
    body: str = Form(...),
):
    key = vw.repo_workflow_pattern_from_url_segment(pat_segment)
    pat_url = vw.repo_workflow_pat_href_segment(key)
    sn = section_name.strip().lower()
    if not sn:
        return templates.TemplateResponse(
            request,
            "admin/workflows/category_new.html",
            {
                "request": request,
                "title": f"새 카테고리 — {vw.repo_workflow_pattern_card_display(key)} 워크플로우",
                "existing_sections": vw.list_sections_for_repo_workflow(db, key),
                "form_action": f"/admin/repo-workflows/pat/{pat_url}/s/new",
                "cancel_url": f"/admin/repo-workflows/pat/{pat_url}",
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vw.list_sections_for_repo_workflow(db, key)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {"error": "already_exists", "message": f"카테고리 '{sn}' 이 이미 존재합니다."},
            status_code=409,
        )
    _, _sn, nv = vw.publish_repo_workflow(db, key, body, sn)
    return RedirectResponse(
        f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/repo-workflows/pat/{pat_segment}/s/{section_name}")
def repo_workflow_category_board(
    request: Request,
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_workflow_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_workflow_pat_href_segment(key)
    display = vw.repo_workflow_pattern_card_display(key)
    rows = db.scalars(
        select(RepoWorkflowVersion)
        .where(RepoWorkflowVersion.pattern == key, RepoWorkflowVersion.section_name == sn)
        .order_by(RepoWorkflowVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")
    n_ver = len(rows)
    can_delete_section = sn != vw.DEFAULT_SECTION

    def _can_del(v: int) -> bool:
        if not (key or "").strip() and sn == vw.DEFAULT_SECTION:
            return n_ver > 1
        return n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/workflows/category_board.html",
        {
            "request": request,
            "title": f"Repo 워크플로우: {display} — {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del,
            "breadcrumb_home": f"/admin/repo-workflows/pat/{pat_url}",
            "breadcrumb_home_label": f"Repo 워크플로우: {display}",
            "publish_url": f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}/publish",
            "delete_section_url": f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}/delete",
            "version_view_base": f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}/v",
        },
    )


@router.post("/repo-workflows/pat/{pat_segment}/s/{section_name}/delete")
def repo_workflow_category_delete(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_workflow_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_workflow_pat_href_segment(key)
    if sn == vw.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    if vw.delete_repo_workflow_section(db, key, sn) == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    return RedirectResponse(f"/admin/repo-workflows/pat/{pat_url}", status_code=303)


@router.get("/repo-workflows/pat/{pat_segment}/s/{section_name}/publish")
def repo_workflow_category_publish_form(
    request: Request,
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_workflow_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_workflow_pat_href_segment(key)
    latest = vw._repo_workflow_latest(db, key, sn)
    return templates.TemplateResponse(
        request,
        "admin/workflows/version_publish.html",
        {
            "request": request,
            "title": f"새 버전 — {vw.repo_workflow_pattern_card_display(key)} / {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "next_version": vw.next_repo_workflow_version(db, key, sn),
            "prefill_body": latest.body if latest else "",
            "form_action": f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}/publish",
            "cancel_url": f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}",
        },
    )


@router.post("/repo-workflows/pat/{pat_segment}/s/{section_name}/publish")
def repo_workflow_category_publish_submit(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    key = vw.repo_workflow_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_workflow_pat_href_segment(key)
    _, _sn, nv = vw.publish_repo_workflow(db, key, body, sn)
    return RedirectResponse(
        f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.post("/repo-workflows/pat/{pat_segment}/s/{section_name}/save-as-new")
def repo_workflow_save_as_new(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    key = vw.repo_workflow_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_workflow_pat_href_segment(key)
    _, _sn, nv = vw.publish_repo_workflow(db, key, body, sn)
    return RedirectResponse(
        f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/repo-workflows/pat/{pat_segment}/s/{section_name}/v/{version}")
def repo_workflow_version_view(
    request: Request,
    pat_segment: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_workflow_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_workflow_pat_href_segment(key)
    display = vw.repo_workflow_pattern_card_display(key)
    row = db.scalars(
        select(RepoWorkflowVersion).where(
            RepoWorkflowVersion.pattern == key,
            RepoWorkflowVersion.section_name == sn,
            RepoWorkflowVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(
            select(func.count()).where(
                RepoWorkflowVersion.pattern == key,
                RepoWorkflowVersion.section_name == sn,
            )
        ) or 0
    )
    can_delete = n > 1 if (not (key or "").strip() and sn == vw.DEFAULT_SECTION) else n >= 1
    return templates.TemplateResponse(
        request,
        "admin/workflows/version_view.html",
        {
            "request": request,
            "title": f"{display} / {_section_display(sn)} — v{version}",
            "row": row,
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "can_delete_version": can_delete,
            "save_as_new_url": f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}/save-as-new",
            "delete_version_url": f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}/v/{version}/delete",
            "back_url": f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}",
            "back_label": f"{display} / {_section_display(sn)}",
        },
    )


@router.post("/repo-workflows/pat/{pat_segment}/s/{section_name}/v/{version}/delete")
def repo_workflow_version_delete(
    pat_segment: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_workflow_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_workflow_pat_href_segment(key)
    n = int(
        db.scalar(
            select(func.count()).where(
                RepoWorkflowVersion.pattern == key,
                RepoWorkflowVersion.section_name == sn,
            )
        ) or 0
    )
    if not (key or "").strip() and sn == vw.DEFAULT_SECTION and n <= 1:
        raise HTTPException(400, "default 패턴 기본 카테고리는 최소 1개 버전이 필요합니다.")
    vw.delete_repo_workflow_version(db, key, sn, version)
    n_after = int(
        db.scalar(
            select(func.count()).where(
                RepoWorkflowVersion.pattern == key,
                RepoWorkflowVersion.section_name == sn,
            )
        ) or 0
    )
    if n_after > 0:
        return RedirectResponse(
            f"/admin/repo-workflows/pat/{pat_url}/s/{quote(sn, safe='')}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/repo-workflows/pat/{pat_url}", status_code=303)
