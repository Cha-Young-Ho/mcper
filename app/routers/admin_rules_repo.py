"""Admin 규칙 관리 — Repository rules (URL 패턴별)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.routers.admin_base import DOMAIN_CONFIG, templates
from app.routers.admin_common import _sort_repo_patterns
from app.services import admin_rules_service as svc
from app.services import versioned_rules as vr

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/repo-rules/pat/{pat_segment}/include-repo-default-toggle")
def repo_pattern_include_repo_default_toggle(
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """패턴(카드)마다 repository default 스트림 병합 여부."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    if not svc.repo_pattern_exists(db, key):
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
    domain: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Response:
    """레포 규칙 카드 목록 (서버사이드 페이지네이션: limit/offset)."""
    domain_filter = domain.strip() or None
    all_patterns = _sort_repo_patterns(
        vr.list_distinct_repo_patterns(db, domain=domain_filter)
    )
    qn = q.strip().lower()
    if qn:

        def _repo_pattern_matches_query(pat: str) -> bool:
            pl = (pat or "").lower()
            if qn in pl:
                return True
            if not pl and qn in ("default", "fallback", "폴백", "__default__"):
                return True
            return False

        all_patterns = [p for p in all_patterns if _repo_pattern_matches_query(p)]

    total = (
        len(all_patterns)
        if qn
        else vr.count_distinct_repo_patterns(db, domain=domain_filter)
    )
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    patterns = all_patterns[offset : offset + limit]

    # N+1 방지: 패턴당 최신 행을 2 쿼리로 일괄 조회.
    latest_by_pat = {
        row.pattern: row for row in vr.get_latest_repo_rules(db, domain=domain_filter)
    }

    cards: list[dict] = []
    for pat in patterns:
        latest = latest_by_pat.get(pat)
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
                "include_repo_default": vr.get_mcp_include_repo_default_for_pattern(
                    db, pat
                ),
            }
        )

    domain_cfg = DOMAIN_CONFIG.get(domain_filter) if domain_filter else None
    return templates.TemplateResponse(
        request,
        "admin/repo_rules_cards.html",
        {
            "request": request,
            "title": f"Repository rules — {domain_cfg['display']}"
            if domain_cfg
            else "Repository rules",
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


@router.get("/repo-rules/new")
def new_repo_pattern_form(
    request: Request,
    _user: str = Depends(require_admin_user),
) -> Response:
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
) -> Response:
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
    if svc.repo_pattern_exists(db, key):
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
) -> Response:
    """레포 규칙 카테고리 오버뷰."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    if not svc.repo_pattern_exists(db, key):
        raise HTTPException(404, "Unknown repository pattern")
    pat_url = vr.repo_pat_href_segment(key)
    display = vr.repo_pattern_card_display(key)
    can_delete_stream = (key or "").strip() != ""

    section_rows = svc.list_repo_section_previews(db, key)
    sections = [
        {
            "section_name": r.section_name,
            "version": r.version,
            "preview": r.preview,
            "created_at": r.created_at,
            "url": f"/admin/repo-rules/pat/{pat_url}/s/{quote(r.section_name, safe='')}",
        }
        for r in section_rows
    ]

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
) -> Response:
    """레포 규칙 패턴 전체 삭제."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    if not (key or "").strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "default(빈 패턴) Repository 스트림은 삭제할 수 없습니다.",
        )
    if svc.delete_repo_stream(db, key) == 0:
        raise HTTPException(404, "삭제할 행이 없습니다.")
    return RedirectResponse("/admin/repo-rules", status_code=303)


# ── 레포 카테고리 라우트 ────────────────────────────────────────────────────


@router.get("/repo-rules/pat/{pat_segment}/s/new")
def repo_category_new_form(
    request: Request,
    pat_segment: str,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    """레포 룰 새 카테고리 생성 폼."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    if not svc.repo_pattern_exists(db, key):
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
) -> Response:
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
            {
                "error": "already_exists",
                "message": f"카테고리 '{sn}' 이 이미 존재합니다.",
            },
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
) -> Response:
    """레포 룰 특정 카테고리의 버전 보드."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    rows = svc.list_repo_category_versions(db, key, sn)
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
) -> Response:
    """레포 룰 카테고리 전체 삭제 (main 제외)."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    if sn == vr.DEFAULT_SECTION:
        raise HTTPException(400, "'기본(main)' 카테고리는 삭제할 수 없습니다.")
    if svc.delete_repo_category(db, key, sn) == 0:
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
) -> Response:
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
) -> Response:
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
) -> Response:
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
) -> Response:
    """레포 룰 카테고리 특정 버전 조회."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    row, n = svc.get_repo_category_version(db, key, sn, version)
    if row is None:
        raise HTTPException(404, "Not found")
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
) -> Response:
    """레포 룰 카테고리 특정 버전 삭제."""
    key = vr.repo_pattern_from_url_segment(pat_segment)
    sn = section_name.strip()
    _, n = svc.get_repo_category_version(db, key, sn, version)
    if not (key or "").strip() and sn == vr.DEFAULT_SECTION and n <= 1:
        raise HTTPException(
            400, "default 패턴 기본 카테고리는 최소 1개 버전이 필요합니다."
        )
    rowcount, n_after = svc.delete_repo_category_version(db, key, sn, version)
    if rowcount == 0:
        raise HTTPException(404, "Not found")
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
) -> Response:
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
) -> Response:
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
) -> Response:
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
