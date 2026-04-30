"""Admin 규칙 관리 — Global rules (카테고리 지원)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.routers.admin_base import DOMAIN_CONFIG, templates
from app.services import admin_rules_service as svc
from app.services import versioned_rules as vr

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/global-rules")
def global_rules_board(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    domain: str = "",
):
    """글로벌 규칙 카테고리 오버뷰."""
    domain_filter = domain.strip() or None
    section_rows = vr._global_all_sections_latest(db, domain=domain_filter)
    sections = []
    for r in section_rows:
        sections.append(
            {
                "section_name": r.section_name,
                "version": r.version,
                "preview": r.body[:200] + ("…" if len(r.body) > 200 else ""),
                "created_at": r.created_at,
                "url": f"/admin/global-rules/s/{quote(r.section_name, safe='')}",
            }
        )
    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/global_rules_board.html",
        {
            "request": request,
            "title": f"Global rules — {domain_cfg['display']}"
            if domain_cfg
            else "Global rules",
            "sections": sections,
            "include_app_default_global": vr.get_mcp_include_app_default_global(db),
            "domain": domain_filter or "",
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
            {
                "error": "already_exists",
                "message": f"카테고리 '{sn}' 이 이미 존재합니다.",
            },
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
    rows = svc.list_global_category_versions(db, sn)
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
    if svc.delete_global_category(db, sn) == 0:
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
    row, n = svc.get_global_category_version(db, sn, version)
    if row is None:
        raise HTTPException(404, "Not found")
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
    n = svc.count_global_category(db, sn)
    if sn == vr.DEFAULT_SECTION and n <= 1:
        raise HTTPException(400, "기본(main) 카테고리는 최소 1개 버전이 필요합니다.")
    rowcount, n_after = svc.delete_global_category_version(db, sn, version)
    if rowcount == 0:
        raise HTTPException(404, "Not found")
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
