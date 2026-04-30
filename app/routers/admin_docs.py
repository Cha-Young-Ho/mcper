"""Admin 문서(Docs) 관리 — Global / App / Repo 카테고리별 CRUD."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.db.doc_models import AppDocVersion, GlobalDocVersion, RepoDocVersion
from app.routers.admin_base import DOMAIN_CONFIG, templates
from app.routers.admin_common import (
    _sort_app_names,
    _sort_repo_patterns,
    _section_display as _section_display_base,
)
from app.services import versioned_docs as vw

router = APIRouter(prefix="/admin", tags=["admin-docs"])


def _section_display(sn: str) -> str:
    return _section_display_base(sn, vw.DEFAULT_SECTION)


# ── 개발 도메인 허브 ──────────────────────────────────────────────────────────


@router.get("/docs-dev")
def docs_dev_hub(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    """개발 도메인 문서 허브 (Global / Repository / App 선택)."""
    return templates.TemplateResponse(
        request,
        "admin/docs_hub.html",
        {"request": request, "title": "문서 — 개발"},
    )


# ── Global docs ────────────────────────────────────────────────────────


@router.get("/global-docs")
def global_docs_board(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    domain: str = "",
):
    domain_filter = domain.strip() or None
    section_rows = vw._global_doc_all_sections_latest(db, domain=domain_filter)
    sections = [
        {
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/global-docs/s/{quote(r.section_name, safe='')}",
        }
        for r in section_rows
    ]
    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/docs/global_docs_board.html",
        {
            "request": request,
            "title": f"Global 문서 — {domain_cfg['display']}"
            if domain_cfg
            else "Global 문서",
            "sections": sections,
            "domain": domain_filter or "",
        },
    )


@router.get("/global-docs/s/new")
def global_doc_category_new_form(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "admin/docs/category_new.html",
        {
            "request": request,
            "title": "새 카테고리 — Global 문서",
            "existing_sections": vw.list_sections_for_global_doc(db),
            "form_action": "/admin/global-docs/s/new",
            "cancel_url": "/admin/global-docs",
            "error": None,
        },
    )


@router.post("/global-docs/s/new")
def global_doc_category_new_submit(
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
            "admin/docs/category_new.html",
            {
                "request": request,
                "title": "새 카테고리 — Global 문서",
                "existing_sections": vw.list_sections_for_global_doc(db),
                "form_action": "/admin/global-docs/s/new",
                "cancel_url": "/admin/global-docs",
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vw.list_sections_for_global_doc(db)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {
                "error": "already_exists",
                "message": f"카테고리 '{sn}' 이 이미 존재합니다.",
            },
            status_code=409,
        )
    nv = vw.publish_global_doc(db, body, sn)
    return RedirectResponse(
        f"/admin/global-docs/s/{quote(sn, safe='')}/v/{nv}", status_code=303
    )


@router.get("/global-docs/s/{section_name}")
def global_doc_category_board(
    request: Request,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    sn = section_name.strip()
    rows = db.scalars(
        select(GlobalDocVersion)
        .where(GlobalDocVersion.section_name == sn)
        .order_by(GlobalDocVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")
    n_ver = len(rows)
    can_delete_section = sn != vw.DEFAULT_SECTION

    def _can_del(v: int) -> bool:
        return n_ver > 1 if sn == vw.DEFAULT_SECTION else n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/docs/category_board.html",
        {
            "request": request,
            "title": f"Global 문서 — {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del,
            "breadcrumb_home": "/admin/global-docs",
            "breadcrumb_home_label": "Global 문서",
            "publish_url": f"/admin/global-docs/s/{quote(sn, safe='')}/publish",
            "delete_section_url": f"/admin/global-docs/s/{quote(sn, safe='')}/delete",
            "version_view_base": f"/admin/global-docs/s/{quote(sn, safe='')}/v",
        },
    )


@router.post("/global-docs/s/{section_name}/delete")
def global_doc_category_delete(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    sn = section_name.strip()
    if sn == vw.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    if vw.delete_global_doc_section(db, sn) == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    return RedirectResponse("/admin/global-docs", status_code=303)


@router.get("/global-docs/s/{section_name}/publish")
def global_doc_category_publish_form(
    request: Request,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    sn = section_name.strip()
    latest = vw._global_doc_latest(db, sn)
    return templates.TemplateResponse(
        request,
        "admin/docs/version_publish.html",
        {
            "request": request,
            "title": f"새 버전 — Global / {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "next_version": vw.next_global_doc_version(db, sn),
            "prefill_body": latest.body if latest else "",
            "form_action": f"/admin/global-docs/s/{quote(sn, safe='')}/publish",
            "cancel_url": f"/admin/global-docs/s/{quote(sn, safe='')}",
        },
    )


@router.post("/global-docs/s/{section_name}/publish")
def global_doc_category_publish_submit(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    sn = section_name.strip()
    nv = vw.publish_global_doc(db, body, sn)
    return RedirectResponse(
        f"/admin/global-docs/s/{quote(sn, safe='')}/v/{nv}", status_code=303
    )


@router.post("/global-docs/s/{section_name}/save-as-new")
def global_doc_save_as_new(
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    sn = section_name.strip()
    nv = vw.publish_global_doc(db, body, sn)
    return RedirectResponse(
        f"/admin/global-docs/s/{quote(sn, safe='')}/v/{nv}", status_code=303
    )


@router.get("/global-docs/s/{section_name}/v/{version}")
def global_doc_version_view(
    request: Request,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    sn = section_name.strip()
    row = db.scalars(
        select(GlobalDocVersion).where(
            GlobalDocVersion.section_name == sn,
            GlobalDocVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(select(func.count()).where(GlobalDocVersion.section_name == sn)) or 0
    )
    can_delete = n > 1 if sn == vw.DEFAULT_SECTION else n >= 1
    return templates.TemplateResponse(
        request,
        "admin/docs/version_view.html",
        {
            "request": request,
            "title": f"Global / {_section_display(sn)} — v{version}",
            "row": row,
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "can_delete_version": can_delete,
            "save_as_new_url": f"/admin/global-docs/s/{quote(sn, safe='')}/save-as-new",
            "delete_version_url": f"/admin/global-docs/s/{quote(sn, safe='')}/v/{version}/delete",
            "back_url": f"/admin/global-docs/s/{quote(sn, safe='')}",
            "back_label": f"Global 문서 / {_section_display(sn)}",
        },
    )


@router.post("/global-docs/s/{section_name}/v/{version}/delete")
def global_doc_version_delete(
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    sn = section_name.strip()
    n = int(
        db.scalar(select(func.count()).where(GlobalDocVersion.section_name == sn)) or 0
    )
    if sn == vw.DEFAULT_SECTION and n <= 1:
        raise HTTPException(400, "기본(main) 카테고리는 최소 1개 버전이 필요합니다.")
    vw.delete_global_doc_version(db, sn, version)
    n_after = int(
        db.scalar(select(func.count()).where(GlobalDocVersion.section_name == sn)) or 0
    )
    if n_after > 0:
        return RedirectResponse(
            f"/admin/global-docs/s/{quote(sn, safe='')}", status_code=303
        )
    return RedirectResponse("/admin/global-docs", status_code=303)


# ── App docs ────────────────────────────────────────────────────────────


@router.get("/app-docs")
def app_docs_cards(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    q: str = "",
    domain: str = "",
    limit: int = 50,
    offset: int = 0,
):
    """앱 문서 카드 목록 (서버사이드 페이지네이션: limit/offset)."""
    domain_filter = domain.strip() or None
    all_names = _sort_app_names(
        vw.list_distinct_apps_with_docs(db, domain=domain_filter)
    )
    if q.strip():
        all_names = [n for n in all_names if q.strip().lower() in n.lower()]

    total = (
        len(all_names)
        if q.strip()
        else vw.count_distinct_apps_with_docs(db, domain=domain_filter)
    )
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    names = all_names[offset : offset + limit]

    cards: list[dict] = []
    for name in names:
        latest = db.scalars(
            select(AppDocVersion)
            .where(AppDocVersion.app_name == name)
            .order_by(AppDocVersion.version.desc())
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
                "url": f"/admin/app-docs/app/{quote(name, safe='')}",
                "can_delete_stream": True,
            }
        )

    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/docs/app_docs_cards.html",
        {
            "request": request,
            "title": f"App 문서 — {domain_cfg['display']}"
            if domain_cfg
            else "App 문서",
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


@router.get("/app-docs/new")
def new_app_doc_form(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    return templates.TemplateResponse(
        request,
        "admin/docs/app_doc_new.html",
        {"request": request, "title": "새 앱 문서", "error": None},
    )


@router.post("/app-docs/new")
def new_app_doc_submit(
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
            "admin/docs/app_doc_new.html",
            {
                "request": request,
                "title": "새 앱 문서",
                "error": "앱 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = db.scalars(
        select(AppDocVersion).where(AppDocVersion.app_name == key).limit(1)
    ).first()
    if existing is not None:
        return JSONResponse(
            {"error": "already_exists", "message": f"'{key}' 앱이 이미 존재합니다."},
            status_code=409,
        )
    vw.publish_app_doc(db, key, body)
    return RedirectResponse(
        f"/admin/app-docs/app/{quote(key, safe='')}/s/{vw.DEFAULT_SECTION}",
        status_code=303,
    )


@router.get("/app-docs/app/{app_name}")
def app_doc_board(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    if not db.scalars(
        select(AppDocVersion).where(AppDocVersion.app_name == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown app")
    section_rows = vw._app_doc_all_sections_latest(db, key)
    sections = [
        {
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(r.section_name, safe='')}",
        }
        for r in section_rows
    ]
    return templates.TemplateResponse(
        request,
        "admin/docs/app_doc_board.html",
        {
            "request": request,
            "title": f"App 문서: {key}",
            "app_name": key,
            "app_display": key,
            "app_url_encoded": quote(key, safe=""),
            "sections": sections,
            "can_delete_stream": True,
        },
    )


@router.post("/app-docs/app/{app_name}/delete")
def app_doc_delete_stream(
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    if vw.delete_app_doc_stream(db, key) == 0:
        raise HTTPException(404, "삭제할 항목이 없습니다.")
    return RedirectResponse("/admin/app-docs", status_code=303)


@router.get("/app-docs/app/{app_name}/s/new")
def app_doc_category_new_form(
    request: Request,
    app_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    if not db.scalars(
        select(AppDocVersion).where(AppDocVersion.app_name == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown app")
    return templates.TemplateResponse(
        request,
        "admin/docs/category_new.html",
        {
            "request": request,
            "title": f"새 카테고리 — {key} 문서",
            "existing_sections": vw.list_sections_for_app_doc(db, key),
            "form_action": f"/admin/app-docs/app/{quote(key, safe='')}/s/new",
            "cancel_url": f"/admin/app-docs/app/{quote(key, safe='')}",
            "error": None,
        },
    )


@router.post("/app-docs/app/{app_name}/s/new")
def app_doc_category_new_submit(
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
            "admin/docs/category_new.html",
            {
                "request": request,
                "title": f"새 카테고리 — {key} 문서",
                "existing_sections": vw.list_sections_for_app_doc(db, key),
                "form_action": f"/admin/app-docs/app/{quote(key, safe='')}/s/new",
                "cancel_url": f"/admin/app-docs/app/{quote(key, safe='')}",
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vw.list_sections_for_app_doc(db, key)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {
                "error": "already_exists",
                "message": f"카테고리 '{sn}' 이 이미 존재합니다.",
            },
            status_code=409,
        )
    _, _sn, nv = vw.publish_app_doc(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/app-docs/app/{app_name}/s/{section_name}")
def app_doc_category_board(
    request: Request,
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    rows = db.scalars(
        select(AppDocVersion)
        .where(AppDocVersion.app_name == key, AppDocVersion.section_name == sn)
        .order_by(AppDocVersion.version.desc())
    ).all()
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")
    n_ver = len(rows)
    can_delete_section = sn != vw.DEFAULT_SECTION

    def _can_del(v: int) -> bool:
        return n_ver >= 1

    return templates.TemplateResponse(
        request,
        "admin/docs/category_board.html",
        {
            "request": request,
            "title": f"App 문서: {key} — {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del,
            "breadcrumb_home": f"/admin/app-docs/app/{quote(key, safe='')}",
            "breadcrumb_home_label": f"App 문서: {key}",
            "publish_url": f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/publish",
            "delete_section_url": f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/delete",
            "version_view_base": f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v",
        },
    )


@router.post("/app-docs/app/{app_name}/s/{section_name}/delete")
def app_doc_category_delete(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    if sn == vw.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    if vw.delete_app_doc_section(db, key, sn) == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    return RedirectResponse(
        f"/admin/app-docs/app/{quote(key, safe='')}", status_code=303
    )


@router.get("/app-docs/app/{app_name}/s/{section_name}/publish")
def app_doc_category_publish_form(
    request: Request,
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    latest = vw._app_doc_latest(db, key, sn)
    return templates.TemplateResponse(
        request,
        "admin/docs/version_publish.html",
        {
            "request": request,
            "title": f"새 버전 — {key} / {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "next_version": vw.next_app_doc_version(db, key, sn),
            "prefill_body": latest.body if latest else "",
            "form_action": f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/publish",
            "cancel_url": f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}",
        },
    )


@router.post("/app-docs/app/{app_name}/s/{section_name}/publish")
def app_doc_category_publish_submit(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    _, _sn, nv = vw.publish_app_doc(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.post("/app-docs/app/{app_name}/s/{section_name}/save-as-new")
def app_doc_save_as_new(
    app_name: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    _, _sn, nv = vw.publish_app_doc(db, key, body, sn)
    return RedirectResponse(
        f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/app-docs/app/{app_name}/s/{section_name}/v/{version}")
def app_doc_version_view(
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
        select(AppDocVersion).where(
            AppDocVersion.app_name == key,
            AppDocVersion.section_name == sn,
            AppDocVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(
            select(func.count()).where(
                AppDocVersion.app_name == key,
                AppDocVersion.section_name == sn,
            )
        )
        or 0
    )
    return templates.TemplateResponse(
        request,
        "admin/docs/version_view.html",
        {
            "request": request,
            "title": f"{key} / {_section_display(sn)} — v{version}",
            "row": row,
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "can_delete_version": n >= 1,
            "save_as_new_url": f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/save-as-new",
            "delete_version_url": f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}/v/{version}/delete",
            "back_url": f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}",
            "back_label": f"{key} / {_section_display(sn)}",
        },
    )


@router.post("/app-docs/app/{app_name}/s/{section_name}/v/{version}/delete")
def app_doc_version_delete(
    app_name: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = app_name.lower().strip()
    sn = section_name.strip()
    vw.delete_app_doc_version(db, key, sn, version)
    n_after = int(
        db.scalar(
            select(func.count()).where(
                AppDocVersion.app_name == key,
                AppDocVersion.section_name == sn,
            )
        )
        or 0
    )
    if n_after > 0:
        return RedirectResponse(
            f"/admin/app-docs/app/{quote(key, safe='')}/s/{quote(sn, safe='')}",
            status_code=303,
        )
    return RedirectResponse(
        f"/admin/app-docs/app/{quote(key, safe='')}", status_code=303
    )


# ── Repo docs ───────────────────────────────────────────────────────────


@router.get("/repo-docs")
def repo_docs_cards(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    q: str = "",
    domain: str = "",
    limit: int = 50,
    offset: int = 0,
):
    """레포 문서 카드 목록 (서버사이드 페이지네이션: limit/offset)."""
    domain_filter = domain.strip() or None
    all_patterns = _sort_repo_patterns(
        vw.list_distinct_repo_patterns_with_docs(db, domain=domain_filter)
    )
    if q.strip():
        qn = q.strip().lower()
        all_patterns = [p for p in all_patterns if qn in (p or "").lower()]

    total = (
        len(all_patterns)
        if q.strip()
        else vw.count_distinct_repo_patterns_with_docs(db, domain=domain_filter)
    )
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    patterns = all_patterns[offset : offset + limit]

    cards: list[dict] = []
    for pat in patterns:
        latest = db.scalars(
            select(RepoDocVersion)
            .where(RepoDocVersion.pattern == pat)
            .order_by(RepoDocVersion.version.desc())
            .limit(1)
        ).first()
        if latest is None:
            continue
        seg = vw.repo_doc_pat_href_segment(pat)
        cards.append(
            {
                "pattern": pat,
                "display": vw.repo_doc_pattern_card_display(pat),
                "is_default": not (pat or "").strip(),
                "can_delete_stream": bool((pat or "").strip()),
                "latest_version": latest.version,
                "url": f"/admin/repo-docs/pat/{seg}",
                "pat_segment": seg,
            }
        )

    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/docs/repo_docs_cards.html",
        {
            "request": request,
            "title": f"Repository 문서 — {domain_cfg['display']}"
            if domain_cfg
            else "Repository 문서",
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


@router.get("/repo-docs/new")
def new_repo_doc_form(
    request: Request,
    _user: str = Depends(require_admin_user),
):
    return templates.TemplateResponse(
        request,
        "admin/docs/repo_doc_new.html",
        {"request": request, "title": "새 Repository 패턴 문서", "error": None},
    )


@router.post("/repo-docs/new")
def new_repo_doc_submit(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    pattern: str = Form(...),
    body: str = Form(...),
):
    key = pattern.strip()
    existing = db.scalars(
        select(RepoDocVersion).where(RepoDocVersion.pattern == key).limit(1)
    ).first()
    if existing is not None:
        return templates.TemplateResponse(
            request,
            "admin/docs/repo_doc_new.html",
            {
                "request": request,
                "title": "새 Repository 패턴 문서",
                "error": f"이미 존재하는 패턴: {key or '(기본)'}",
            },
            status_code=400,
        )
    vw.publish_repo_doc(db, key, body)
    seg = vw.repo_doc_pat_href_segment(key)
    return RedirectResponse(f"/admin/repo-docs/pat/{seg}", status_code=303)


@router.get("/repo-docs/pat/{pat_segment}")
def repo_doc_board(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_doc_pattern_from_url_segment(pat_segment)
    if not db.scalars(
        select(RepoDocVersion).where(RepoDocVersion.pattern == key).limit(1)
    ).first():
        raise HTTPException(404, "Unknown repository pattern")
    pat_url = vw.repo_doc_pat_href_segment(key)
    display = vw.repo_doc_pattern_card_display(key)
    can_delete_stream = bool((key or "").strip())
    section_rows = vw._repo_doc_all_sections_latest(db, key)
    sections = [
        {
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
            "created_at": r.created_at,
            "url": f"/admin/repo-docs/pat/{pat_url}/s/{quote(r.section_name, safe='')}",
        }
        for r in section_rows
    ]
    return templates.TemplateResponse(
        request,
        "admin/docs/repo_doc_board.html",
        {
            "request": request,
            "title": f"Repo 문서: {display}",
            "pattern": key,
            "pattern_display": display,
            "sections": sections,
            "pat_url": pat_url,
            "can_delete_stream": can_delete_stream,
        },
    )


@router.post("/repo-docs/pat/{pat_segment}/delete")
def repo_doc_delete_stream(
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_doc_pattern_from_url_segment(pat_segment)
    if not (key or "").strip():
        raise HTTPException(400, "default 패턴은 삭제할 수 없습니다.")
    if vw.delete_repo_doc_stream(db, key) == 0:
        raise HTTPException(404, "삭제할 항목이 없습니다.")
    return RedirectResponse("/admin/repo-docs", status_code=303)


@router.get("/repo-docs/pat/{pat_segment}/s/new")
def repo_doc_category_new_form(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_doc_pattern_from_url_segment(pat_segment)
    pat_url = vw.repo_doc_pat_href_segment(key)
    display = vw.repo_doc_pattern_card_display(key)
    return templates.TemplateResponse(
        request,
        "admin/docs/category_new.html",
        {
            "request": request,
            "title": f"새 카테고리 — {display} 문서",
            "existing_sections": vw.list_sections_for_repo_doc(db, key),
            "form_action": f"/admin/repo-docs/pat/{pat_url}/s/new",
            "cancel_url": f"/admin/repo-docs/pat/{pat_url}",
            "error": None,
        },
    )


@router.post("/repo-docs/pat/{pat_segment}/s/new")
def repo_doc_category_new_submit(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    section_name: str = Form(...),
    body: str = Form(...),
):
    key = vw.repo_doc_pattern_from_url_segment(pat_segment)
    pat_url = vw.repo_doc_pat_href_segment(key)
    sn = section_name.strip().lower()
    if not sn:
        return templates.TemplateResponse(
            request,
            "admin/docs/category_new.html",
            {
                "request": request,
                "title": f"새 카테고리 — {vw.repo_doc_pattern_card_display(key)} 문서",
                "existing_sections": vw.list_sections_for_repo_doc(db, key),
                "form_action": f"/admin/repo-docs/pat/{pat_url}/s/new",
                "cancel_url": f"/admin/repo-docs/pat/{pat_url}",
                "error": "카테고리 이름은 필수입니다.",
            },
            status_code=400,
        )
    existing = vw.list_sections_for_repo_doc(db, key)
    if sn in [s.lower() for s in existing]:
        return JSONResponse(
            {
                "error": "already_exists",
                "message": f"카테고리 '{sn}' 이 이미 존재합니다.",
            },
            status_code=409,
        )
    _, _sn, nv = vw.publish_repo_doc(db, key, body, sn)
    return RedirectResponse(
        f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/repo-docs/pat/{pat_segment}/s/{section_name}")
def repo_doc_category_board(
    request: Request,
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_doc_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_doc_pat_href_segment(key)
    display = vw.repo_doc_pattern_card_display(key)
    rows = db.scalars(
        select(RepoDocVersion)
        .where(RepoDocVersion.pattern == key, RepoDocVersion.section_name == sn)
        .order_by(RepoDocVersion.version.desc())
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
        "admin/docs/category_board.html",
        {
            "request": request,
            "title": f"Repo 문서: {display} — {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "rows": rows,
            "can_delete_section": can_delete_section,
            "can_delete_version": _can_del,
            "breadcrumb_home": f"/admin/repo-docs/pat/{pat_url}",
            "breadcrumb_home_label": f"Repo 문서: {display}",
            "publish_url": f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}/publish",
            "delete_section_url": f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}/delete",
            "version_view_base": f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}/v",
        },
    )


@router.post("/repo-docs/pat/{pat_segment}/s/{section_name}/delete")
def repo_doc_category_delete(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_doc_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_doc_pat_href_segment(key)
    if sn == vw.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    if vw.delete_repo_doc_section(db, key, sn) == 0:
        raise HTTPException(404, "삭제할 카테고리가 없습니다.")
    return RedirectResponse(f"/admin/repo-docs/pat/{pat_url}", status_code=303)


@router.get("/repo-docs/pat/{pat_segment}/s/{section_name}/publish")
def repo_doc_category_publish_form(
    request: Request,
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_doc_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_doc_pat_href_segment(key)
    latest = vw._repo_doc_latest(db, key, sn)
    return templates.TemplateResponse(
        request,
        "admin/docs/version_publish.html",
        {
            "request": request,
            "title": f"새 버전 — {vw.repo_doc_pattern_card_display(key)} / {_section_display(sn)}",
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "next_version": vw.next_repo_doc_version(db, key, sn),
            "prefill_body": latest.body if latest else "",
            "form_action": f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}/publish",
            "cancel_url": f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}",
        },
    )


@router.post("/repo-docs/pat/{pat_segment}/s/{section_name}/publish")
def repo_doc_category_publish_submit(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    key = vw.repo_doc_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_doc_pat_href_segment(key)
    _, _sn, nv = vw.publish_repo_doc(db, key, body, sn)
    return RedirectResponse(
        f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.post("/repo-docs/pat/{pat_segment}/s/{section_name}/save-as-new")
def repo_doc_save_as_new(
    pat_segment: str,
    section_name: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    body: str = Form(...),
):
    key = vw.repo_doc_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_doc_pat_href_segment(key)
    _, _sn, nv = vw.publish_repo_doc(db, key, body, sn)
    return RedirectResponse(
        f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}/v/{nv}",
        status_code=303,
    )


@router.get("/repo-docs/pat/{pat_segment}/s/{section_name}/v/{version}")
def repo_doc_version_view(
    request: Request,
    pat_segment: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_doc_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_doc_pat_href_segment(key)
    display = vw.repo_doc_pattern_card_display(key)
    row = db.scalars(
        select(RepoDocVersion).where(
            RepoDocVersion.pattern == key,
            RepoDocVersion.section_name == sn,
            RepoDocVersion.version == version,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Not found")
    n = int(
        db.scalar(
            select(func.count()).where(
                RepoDocVersion.pattern == key,
                RepoDocVersion.section_name == sn,
            )
        )
        or 0
    )
    can_delete = (
        n > 1 if (not (key or "").strip() and sn == vw.DEFAULT_SECTION) else n >= 1
    )
    return templates.TemplateResponse(
        request,
        "admin/docs/version_view.html",
        {
            "request": request,
            "title": f"{display} / {_section_display(sn)} — v{version}",
            "row": row,
            "section_name": sn,
            "section_display": _section_display(sn),
            "section_url_encoded": quote(sn, safe=""),
            "can_delete_version": can_delete,
            "save_as_new_url": f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}/save-as-new",
            "delete_version_url": f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}/v/{version}/delete",
            "back_url": f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}",
            "back_label": f"{display} / {_section_display(sn)}",
        },
    )


@router.post("/repo-docs/pat/{pat_segment}/s/{section_name}/v/{version}/delete")
def repo_doc_version_delete(
    pat_segment: str,
    section_name: str,
    version: int,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    key = vw.repo_doc_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    pat_url = vw.repo_doc_pat_href_segment(key)
    n = int(
        db.scalar(
            select(func.count()).where(
                RepoDocVersion.pattern == key,
                RepoDocVersion.section_name == sn,
            )
        )
        or 0
    )
    if not (key or "").strip() and sn == vw.DEFAULT_SECTION and n <= 1:
        raise HTTPException(
            400, "default 패턴 기본 카테고리는 최소 1개 버전이 필요합니다."
        )
    vw.delete_repo_doc_version(db, key, sn, version)
    n_after = int(
        db.scalar(
            select(func.count()).where(
                RepoDocVersion.pattern == key,
                RepoDocVersion.section_name == sn,
            )
        )
        or 0
    )
    if n_after > 0:
        return RedirectResponse(
            f"/admin/repo-docs/pat/{pat_url}/s/{quote(sn, safe='')}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/repo-docs/pat/{pat_url}", status_code=303)
