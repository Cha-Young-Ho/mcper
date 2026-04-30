"""Admin 규칙 관리 — App rules (앱별, 카테고리 지원)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.routers.admin_base import DOMAIN_CONFIG, templates
from app.routers.admin_common import _sort_app_names
from app.services import admin_rules_service as svc
from app.services import versioned_rules as vr

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/app-rules")
def app_rules_cards(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
    q: str = "",
    domain: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Response:
    """앱 규칙 카드 목록 (서버사이드 페이지네이션: limit/offset)."""
    domain_filter = domain.strip() or None
    # 전체 목록 가져오고 in-Python으로 q 필터 후 limit/offset 적용.
    all_names = _sort_app_names(vr.list_distinct_apps(db, domain=domain_filter))
    qn = q.strip().lower()
    if qn:
        all_names = [n for n in all_names if qn in n.lower()]

    total = len(all_names) if qn else vr.count_distinct_apps(db, domain=domain_filter)
    # 안전 범위 체크.
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    names = all_names[offset : offset + limit]

    # N+1 방지: 앱당 최신 행을 2 쿼리(집계 + 조인)로 일괄 조회 후 dict 룩업.
    latest_by_app = {
        row.app_name: row for row in vr.get_latest_app_rules(db, domain=domain_filter)
    }

    cards: list[dict] = []
    for name in names:
        latest = latest_by_app.get(name)
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
                    vr.get_mcp_include_app_default_for_app(db, name)
                    if not is_def
                    else False
                ),
            }
        )

    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/app_rules_cards.html",
        {
            "request": request,
            "title": f"App rules — {domain_cfg['display']}"
            if domain_cfg
            else "App rules",
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


@router.get("/app-rules/new")
def new_app_form(
    request: Request,
    _user: str = Depends(require_admin_user),
) -> Response:
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
) -> Response:
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
    if svc.app_exists(db, key):
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
) -> Response:
    """앱 규칙 섹션 오버뷰 (섹션 카드 목록)."""
    key = app_name.lower().strip()
    if not svc.app_exists(db, key):
        raise HTTPException(404, "Unknown app")

    # 모든 섹션의 최신 버전 — 카드용 preview 필드만 (body TEXT 전체 로드 회피)
    section_rows = svc.list_app_section_previews(db, key)
    sections = [
        {
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.preview,
            "created_at": r.created_at,
            "url": f"/admin/app-rules/app/{quote(key, safe='')}/s/{quote(r.section_name, safe='')}",
        }
        for r in section_rows
    ]

    can_delete_stream = key != "__default__"
    show_pull_default_toggle = key != "__default__"
    include_app_pull_default = (
        vr.get_mcp_include_app_default_for_app(db, key)
        if show_pull_default_toggle
        else False
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
) -> Response:
    """이 앱으로 `get_global_rule` 호출 시 `__default__` 앱 스트림을 함께 내려줄지 (앱별)."""
    key = app_name.lower().strip()
    if key == "__default__":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "default 스트림만 조회할 때는 이 옵션이 적용되지 않습니다.",
        )
    if not svc.app_exists(db, key):
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
) -> Response:
    """해당 app_name 의 모든 app_rule_versions 행 삭제 (`__default__` 제외)."""
    key = app_name.lower().strip()
    if key == "__default__":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "__default__(default) 앱 스트림은 삭제할 수 없습니다.",
        )
    if svc.delete_app_stream(db, key) == 0:
        raise HTTPException(404, "삭제할 행이 없습니다.")
    return RedirectResponse("/admin/app-rules", status_code=303)


@router.post("/app-rules/app/{app_name}/v/{version}/delete")
def app_rule_delete_one_version_legacy(
    app_name: str,
    version: int,
) -> Response:
    """backward-compat: 섹션 없는 버전 삭제 → main 섹션으로 리다이렉트."""
    key = app_name.lower().strip()
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}/s/{vr.DEFAULT_SECTION}/v/{version}/delete",
        status_code=307,
    )


@router.get("/app-rules/app/{app_name}/publish")
def app_rule_publish_form_legacy(
    app_name: str,
) -> Response:
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
) -> Response:
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
) -> Response:
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
) -> Response:
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
) -> Response:
    """새 섹션 생성 폼."""
    key = app_name.lower().strip()
    if not svc.app_exists(db, key):
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
) -> Response:
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
            {
                "error": "already_exists",
                "message": f"카테고리 '{sn}' 이 이미 존재합니다. 기존 카테고리에서 새 버전을 추가하세요.",
            },
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
) -> Response:
    """앱 규칙 특정 섹션의 버전 보드."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    rows = svc.list_app_section_versions(db, key, sn)
    if not rows:
        raise HTTPException(404, "카테고리를 찾을 수 없습니다.")

    n_ver = len(rows)
    can_delete_stream = key != "__default__"
    can_delete_section = sn != vr.DEFAULT_SECTION

    def _can_del_ver(_v: int) -> bool:
        """해당 버전을 삭제해도 되는지 판정."""
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
) -> Response:
    """섹션 전체 삭제 (main 섹션 제외)."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    if sn == vr.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    if svc.delete_app_section(db, key, sn) == 0:
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
) -> Response:
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
) -> Response:
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
) -> Response:
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
) -> Response:
    """앱 규칙 섹션 특정 버전 조회."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    row, n = svc.get_app_section_version(db, key, sn, version)
    if row is None:
        raise HTTPException(404, "Not found")
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
) -> Response:
    """앱 규칙 섹션 특정 버전 삭제."""
    key = app_name.lower().strip()
    sn = section_name.strip()
    _, n = svc.get_app_section_version(db, key, sn, version)
    if key == "__default__" and sn == vr.DEFAULT_SECTION and n <= 1:
        raise HTTPException(
            400, "default 앱 기본(main) 카테고리는 최소 1개 버전이 필요합니다."
        )
    rowcount, n_after = svc.delete_app_section_version(db, key, sn, version)
    if rowcount == 0:
        raise HTTPException(404, "Not found")
    if n_after > 0:
        return RedirectResponse(
            f"/admin/app-rules/app/{quote(key, safe='')}/s/{quote(sn, safe='')}",
            status_code=303,
        )
    return RedirectResponse(
        f"/admin/app-rules/app/{quote(key, safe='')}",
        status_code=303,
    )
