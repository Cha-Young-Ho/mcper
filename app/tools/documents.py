"""MCP tools: document upload and search."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy import cast, or_, select
from sqlalchemy.types import String

from app.db.database import SessionLocal
from app.db.models import Spec
from app.services.celery_client import enqueue_index_spec
from app.services.mcp_tool_stats import record_mcp_tool_call
from app.services.search_hybrid import hybrid_spec_search
from app.tools._auth_check import check_read, check_write
from app.tools._common import error_json


def _normalize_related_files(related_files: Any) -> list[str]:
    """Accept list, JSON string, or comma-separated paths from MCP clients."""
    if related_files is None:
        return []
    if isinstance(related_files, list):
        return [str(x) for x in related_files]
    if isinstance(related_files, str):
        s = related_files.strip()
        if not s:
            return []
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [str(x) for x in data]
        except json.JSONDecodeError:
            pass
        return [p.strip() for p in s.split(",") if p.strip()]
    return [str(related_files)]


def _ilike_pattern(term: str) -> str:
    """Build ILIKE pattern with % / _ escaped (PostgreSQL backslash escape)."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def upload_document_impl(
    content: str,
    app_target: str,
    base_branch: str,
    related_files: Any,
    title: str | None = None,
) -> str:
    """Insert one document row. Returns JSON message with new id."""
    record_mcp_tool_call("upload_document")
    with SessionLocal() as db:
        denied = check_write(db)
        if denied:
            return denied
    paths = _normalize_related_files(related_files)
    t = (title or "").strip() or None
    row = Spec(
        title=t,
        content=content,
        app_target=app_target,
        base_branch=base_branch,
        related_files=paths,
    )
    with SessionLocal() as db:
        try:
            db.add(row)
            db.commit()
            db.refresh(row)
            queued = enqueue_index_spec(row.id)
            return json.dumps(
                {
                    "ok": True,
                    "id": row.id,
                    "message": "inserted",
                    "chunk_index_queued": queued,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            db.rollback()
            return error_json(str(exc))


def search_documents_impl(query: str, app_target: str) -> str:
    """Hybrid vector + FTS (RRF) when document chunks exist; else legacy ILIKE on documents."""
    record_mcp_tool_call("search_documents")
    with SessionLocal() as db:
        try:
            denied = check_read(db)
            if denied:
                return denied
            chunks, mode = hybrid_spec_search(
                db, query=query, app_target=app_target, top_n=15
            )
            if mode == "hybrid_ok" and chunks:
                return json.dumps(
                    {
                        "ok": True,
                        "search_mode": "hybrid_rrf",
                        "count": len(chunks),
                        "chunks": chunks,
                    },
                    ensure_ascii=False,
                )

            pattern = _ilike_pattern(query)
            json_text = cast(Spec.related_files, String)
            stmt = (
                select(Spec)
                .where(Spec.app_target == app_target)
                .where(
                    or_(
                        Spec.content.ilike(pattern, escape="\\"),
                        json_text.ilike(pattern, escape="\\"),
                    )
                )
                .order_by(Spec.id.desc())
                .limit(50)
            )
            rows = list(db.scalars(stmt).all())
            legacy = [
                {
                    "id": r.id,
                    "title": r.title,
                    "content": r.content,
                    "related_files": r.related_files,
                    "base_branch": r.base_branch,
                }
                for r in rows
            ]
            if mode == "indexed_no_match":
                sm = "legacy_ilike_supplement"
            else:
                sm = "legacy_ilike"
            return json.dumps(
                {
                    "ok": True,
                    "search_mode": sm,
                    "count": len(legacy),
                    "results": legacy,
                    "chunks": [],
                    "hybrid_note": mode,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "action_required": "check DB, EMBEDDING_DIM vs LOCAL_EMBEDDING_MODEL, sentence-transformers",
                },
                ensure_ascii=False,
            )


def register_document_tools(mcp: FastMCP) -> None:
    """Register upload / search tools on a FastMCP instance."""

    @mcp.tool()
    def upload_document(
        content: str,
        app_target: str,
        base_branch: str,
        related_files: list[str] | str | None = None,
        title: str | None = None,
    ) -> str:
        """
        기획서(스펙) 1건을 DB에 저장하고, 자동으로 청킹·임베딩 색인을 예약한다.

        언제 쓰는가:
        - 새 기획서를 작성했거나 사용자가 기획서 내용을 넘겨줬을 때
        - 기존 기획서를 수정해서 최신 내용으로 교체하려 할 때

        related_files: 이 기획서와 관련된 소스 파일 경로 목록 (예: ["src/payment/service.py"])
        title: 어드민 UI 목록에 표시되는 제목. 나중에 검색할 때 식별자 역할.

        저장 후 Celery 워커가 백그라운드에서 청킹·임베딩을 처리하므로
        search_documents로 검색되기까지 수 초~수십 초 소요된다.
        """
        return upload_document_impl(
            content=content,
            app_target=app_target,
            base_branch=base_branch,
            related_files=related_files,
            title=title,
        )

    @mcp.tool()
    def search_documents(query: str, app_target: str) -> str:
        """
        현재 작업과 관련된 기획서나 코드 문서를 검색한다 (벡터+FTS 하이브리드).

        언제 쓰는가:
        - "결제 모듈 기획서 찾아줘"처럼 특정 기능/주제의 기획서를 찾을 때
        - 코드 작성 전 관련 기획 내용을 참고하고 싶을 때
        - 특정 파일 경로나 키워드가 포함된 기획서를 찾을 때

        find_historical_reference와의 차이:
        - search_documents: 키워드·주제로 관련 기획서를 찾는 "일반 검색"
        - find_historical_reference: 내가 지금 쓰려는 기획서 초안을 넘겨서
          "과거에 유사한 기획이 있었는지" 비교할 때 쓰는 "유사 기획 탐색"

        임베딩 인덱스가 없으면 키워드 ILIKE 검색으로 자동 대체된다.
        """
        return search_documents_impl(query=query, app_target=app_target)

    @mcp.tool()
    def upload_documents_batch(documents: list[dict]) -> dict:
        """
        기획서 여러 건을 한 번에 DB에 저장한다.

        언제 쓰는가:
        - 기존 기획서 파일들을 일괄 등록할 때
        - 어드민 UI의 "문서 일괄 업로드" 기능과 동일한 동작

        각 문서 dict 형식:
          - title (str): 기획서 제목 (검색 및 식별용)
          - content (str): 기획서 전체 내용
          - app_target (str, optional): 앱 식별자
          - base_branch (str, optional): 기준 브랜치 (기본값: main)
          - related_files (list[str] | str | None, optional): 관련 파일 경로

        반환: { succeeded: N, failed: N, errors: [...] }
        """
        succeeded = 0
        failed = 0
        errors: list[dict] = []
        for doc in documents:
            content = doc.get("content", "")
            app_target = doc.get("app_target", "")
            base_branch = doc.get("base_branch", "main") or "main"
            related_files = doc.get("related_files")
            title = doc.get("title")
            result_str = upload_document_impl(
                content=content,
                app_target=app_target,
                base_branch=base_branch,
                related_files=related_files,
                title=title,
            )
            result = json.loads(result_str)
            if result.get("ok"):
                succeeded += 1
            else:
                failed += 1
                errors.append({"title": title, "error": result.get("error", "unknown")})
        return {"succeeded": succeeded, "failed": failed, "errors": errors}


# Deprecated aliases — kept for backward compatibility
upload_spec_to_db = upload_document_impl
search_spec_and_code = search_documents_impl
register_spec_tools = register_document_tools
