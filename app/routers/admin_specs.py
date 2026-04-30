"""Admin 기획서 관리 (CRUD, 검색, 일괄 업로드)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.db.models import Spec
from app.routers.admin_base import (
    ADMIN_UPLOAD_ALLOWED_EXTENSIONS,
    _related_files_from_textarea,
    _spec_app_cards,
    templates,
)
from app.services.celery_client import (
    enqueue_index_spec,
    enqueue_or_index_sync,
    enqueue_parse_and_index_upload,
)
from app.services.document_parser import fetch_url_as_text
from app.services.spec_admin import (
    content_looks_like_vector_or_blob,
    spec_display_title,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/plans")
def plans_app_index(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """기획서 앱 카드 목록."""
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
    """앱별 기획서 목록."""
    key = app_name.strip()
    rows = db.scalars(
        select(Spec).where(Spec.app_target == key).order_by(Spec.id.desc())
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
    """기획서 상세 조회."""
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
    """기획서 편집 폼."""
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
    """기획서 편집 처리."""
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
    """기획서 삭제 확인 페이지."""
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
    """기획서 삭제 처리."""
    if confirm.strip().upper() != "DELETE":
        raise HTTPException(400, "확인 입력란에 대문자 DELETE 를 입력하세요.")
    row = db.get(Spec, spec_id)
    if row is None:
        raise HTTPException(404, "Not found")
    app_enc = quote(row.app_target, safe="")
    db.delete(row)
    db.commit()
    return RedirectResponse(f"/admin/plans/app/{app_enc}", status_code=303)


@router.get("/plans/bulk-upload")
def plan_bulk_upload_form(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """기획서 일괄 업로드 폼."""
    apps = sorted(
        {row for (row,) in db.execute(select(Spec.app_target).distinct()).all()}
    )
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
    """
    기획서 일괄 업로드.

    - 파일 파싱(PDF/DOCX 포함) + 임베딩은 Celery worker에서 처리 (CPU-bound off event loop)
    - 파일 바이너리는 Redis에 30분 TTL로 보관; Celery 메시지엔 Redis key만 전달 (base64 없음)
    - Celery 미설정 시 동기 fallback
    """
    app_key = app_target.strip().lower()
    if not app_key:
        raise HTTPException(400, "app_target 필수")

    branch = (base_branch or "main").strip() or "main"
    results = []

    for f in files:
        filename = f.filename or "unnamed"
        ext = Path(filename).suffix.lower()

        if ext not in ADMIN_UPLOAD_ALLOWED_EXTENSIONS:
            results.append(
                {
                    "file": filename,
                    "ok": False,
                    "queued": False,
                    "error": f"지원하지 않는 형식: {ext}",
                }
            )
            continue

        try:
            raw = await f.read()
            result = enqueue_parse_and_index_upload(filename, raw, app_key, branch)
            results.append({"file": filename, **result})
        except Exception as exc:
            results.append(
                {"file": filename, "ok": False, "queued": False, "error": str(exc)}
            )

    queued_count = sum(1 for r in results if r.get("queued"))
    ok_count = sum(1 for r in results if r.get("ok") is True)  # 동기 fallback 성공 수

    return templates.TemplateResponse(
        request,
        "admin/plan_bulk_upload.html",
        {
            "request": request,
            "title": "기획서 일괄 업로드",
            "known_apps": sorted(
                {row for (row,) in db.execute(select(Spec.app_target).distinct()).all()}
            ),
            "results": results,
            "queued_count": queued_count,
            "ok_count": ok_count,
            "total": len(results),
            "app_target": app_key,
        },
        status_code=200,
    )


# ----- 기획서–코드 (연결 파일) -----


@router.get("/plan-code")
def plan_code_app_index(
    request: Request,
    _user: str = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """기획서–코드 앱 카드 목록."""
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
    """앱별 기획서–코드 목록."""
    key = app_name.strip()
    rows = db.scalars(
        select(Spec).where(Spec.app_target == key).order_by(Spec.id.desc())
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
    """기획서–코드 상세 조회."""
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


# ----- URL 일괄 등록 -----


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
                results.append(
                    {"url": url, "ok": False, "error": "URL 내용이 비어 있습니다"}
                )
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
    return JSONResponse(
        {"ok_count": ok_count, "fail_count": fail_count, "results": results}
    )
