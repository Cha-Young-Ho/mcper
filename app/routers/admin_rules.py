"""Admin 규칙 관리 라우터 shell.

실제 라우트는 도메인별 서브모듈에 분리돼 있다:
- admin_rules_global: Global rules (카테고리 포함)
- admin_rules_app:    App rules (앱별, 카테고리 포함)
- admin_rules_repo:   Repository rules (URL 패턴별, 카테고리 포함)

이 파일은 공통 허브(`/rules-dev`), 앱 추가 마법사(`/apps/new`), 그리고
diff / rollback / export / import 편의성 라우트만 담당한다. 외부에는
기존처럼 `admin_rules.router` 하나만 노출돼 기존 include 경로를 유지한다.
"""

from __future__ import annotations

import difflib
import json
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.routers.admin_base import templates
from app.routers.admin_common import _sort_repo_patterns
from app.services import admin_rules_service as svc
from app.services import versioned_rules as vr

router = APIRouter(prefix="/admin", tags=["admin"])


# ----- 개발 도메인 허브 -----


@router.get("/rules-dev")
def rules_dev_hub(
    request: Request,
    _user: str = Depends(require_admin_user),
) -> Response:
    """개발 도메인 행동 지침 허브 (Global / Repository / App 선택)."""
    return templates.TemplateResponse(
        request,
        "admin/rules_dev_hub.html",
        {"request": request, "title": "행동 지침 — 개발"},
    )


# ----- 앱 추가 마법사 -----


@router.get("/apps/new")
def new_app_wizard_form(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> Response:
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
) -> Response:
    """앱 추가 마법사 처리.

    - app_name 이미 존재 → 409 JSON (프론트에서 alert 표시)
    - repo 패턴 미존재 → 플레이스홀더 본문으로 신규 생성
    - app 신규 생성 후 앱 보드로 이동
    """
    app_key = app_name.strip().lower()
    if not app_key:
        return _wizard_error(request, db, "앱 이름은 필수입니다.")

    if svc.app_exists(db, app_key):
        return JSONResponse(
            {
                "error": "already_exists",
                "message": f"'{app_key}' 앱이 이미 존재합니다. 기존 앱 화면에서 새 버전을 추가하세요.",
            },
            status_code=409,
        )

    repo_pattern = (repo_new_pattern if repo_mode == "new" else repo_existing).strip()

    if repo_mode == "new" and repo_pattern:
        if not svc.repo_pattern_exists(db, repo_pattern):
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
        {"pattern": p, "display": vr.repo_pattern_card_display(p)} for p in raw_patterns
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


# ----- Rule 편의성 기능 (diff / rollback / export-import) -----


@router.get("/rules/{rule_id}/diff")
def rule_diff(
    rule_id: int,
    v1: int,
    v2: int,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin_user),
) -> Response:
    """
    Return unified diff between two versions of a global rule.
    rule_id is accepted for API consistency but global rules use a single stream.
    Returns JSON: {"v1": int, "v2": int, "diff": str}
    """
    row1 = svc.get_global_version_row(db, v1)
    row2 = svc.get_global_version_row(db, v2)

    if row1 is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Global rule version {v1} not found"
        )
    if row2 is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Global rule version {v2} not found"
        )

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
) -> Response:
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
) -> Response:
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
) -> Response:
    """
    Import rules from a JSON export file.
    Expects the same structure produced by GET /admin/rules/export.
    Each rule type is published as a new version (append-only).
    """
    raw = await file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Invalid JSON: {exc}"
        ) from exc

    results: dict[str, object] = {}

    # global
    global_section = data.get("global", {})
    global_body = (
        (global_section.get("body") or "").strip()
        if isinstance(global_section, dict)
        else ""
    )
    if global_body:
        new_gv = vr.publish_global(db, global_body)
        results["global"] = {"new_version": new_gv}

    # apps (섹션별 import 지원: {"app_name": {"main": {"body": ...}, "admin_rules": {...}}})
    # 기존 구현은 sections 을 2번 순회하며, 두 번째 순회에서 new_v 가 마지막 루프 값으로 고정되는
    # 버그가 있었다. 1회 순회로 섹션별 new_v 를 정확히 기록한다.
    apps_imported: dict[str, object] = {}
    for app_name, info in (data.get("apps") or {}).items():
        if not isinstance(info, dict):
            continue
        # new format: {section_name: {version, body}}
        section_entries = {
            k: (v.get("body") or "").strip()
            for k, v in info.items()
            if isinstance(v, dict) and v.get("body")
        }
        if section_entries:
            per_section: dict[str, int] = {}
            for sn, body in section_entries.items():
                if body:
                    _, _sn, new_v = vr.publish_app(db, app_name, body, sn)
                    per_section[sn] = new_v
            if per_section:
                apps_imported[app_name] = per_section
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
        if not isinstance(info, dict):
            continue
        pattern = "" if pat_key == "__default__" else pat_key
        section_entries = {
            k: (v.get("body") or "").strip()
            for k, v in info.items()
            if isinstance(v, dict) and v.get("body")
        }
        if section_entries:
            per_section: dict[str, int] = {}
            for sn, body in section_entries.items():
                if body:
                    _, _sn, new_v = vr.publish_repo(db, pattern, body, section_name=sn)
                    per_section[sn] = new_v
            if per_section:
                repos_imported[pat_key] = per_section
        else:
            body = (info.get("body") or "").strip()
            if body:
                _, _sn, new_v = vr.publish_repo(db, pattern, body)
                repos_imported[pat_key] = new_v
    if repos_imported:
        results["repos"] = repos_imported

    return JSONResponse({"ok": True, "imported": results})
