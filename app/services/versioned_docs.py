"""Docs 버전 관리 서비스 레이어.

Docs = 일반 문서 (레퍼런스, 가이드, 메모 등 자유 형식 문서)

MCP 응답 형식:
- get_global_doc 호출 시 카테고리별로 별도 파일 블록 반환

저장 경로 규칙:
- Global:  .cursor/docs/global/{section_name}.md
- Repo:    .cursor/docs/repo/{pattern_slug}/{section_name}.md
- App:     .cursor/docs/app/{app_name}/{section_name}.md
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.doc_models import AppDocVersion, GlobalDocVersion, RepoDocVersion
from app.doc.service import make_default_doc_service

logger = logging.getLogger(__name__)

DEFAULT_SECTION = "main"

# ── 저장 경로 헬퍼 ─────────────────────────────────────────────────────────


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\-.]", "_", s or "default")
    return s.strip("_") or "default"


def _global_doc_save_path(section_name: str) -> str:
    return f".cursor/docs/global/{_slug(section_name)}.md"


def _app_doc_save_path(app_name: str, section_name: str) -> str:
    return f".cursor/docs/app/{_slug(app_name)}/{_slug(section_name)}.md"


def _repo_doc_save_path(pattern: str, section_name: str) -> str:
    pat_slug = _slug(pattern) if pattern else "default"
    return f".cursor/docs/repo/{pat_slug}/{_slug(section_name)}.md"


# ── Domain filter ─────────────────────────────────────────────────────────


def _domain_filter(col, domain: str | None):
    if domain is None:
        return None
    if domain == "development":
        return (col == "development") | (col.is_(None))
    return col == domain


def _try_index_doc(
    session: Session,
    doc_type: str,
    doc_entity_id: int,
    body: str,
    *,
    app_name: str | None = None,
    pattern: str | None = None,
    domain: str | None = None,
    section_name: str = DEFAULT_SECTION,
) -> None:
    """Best-effort doc indexing after publish. Failure is logged, not raised."""
    try:
        svc = make_default_doc_service(session)
        svc.index_doc(
            doc_type=doc_type,
            doc_entity_id=doc_entity_id,
            body=body,
            app_name=app_name,
            pattern=pattern,
            domain=domain,
            section_name=section_name,
        )
    except Exception:
        logger.warning(
            "doc indexing failed type=%s id=%s",
            doc_type, doc_entity_id, exc_info=True,
        )


# ── Global docs ──────────────────────────────────────────────────────


def list_sections_for_global_doc(session: Session) -> list[str]:
    rows = session.scalars(select(GlobalDocVersion.section_name).distinct()).all()
    return sorted({r for r in rows if r}, key=lambda s: ("" if s == DEFAULT_SECTION else s)) or [DEFAULT_SECTION]


def _global_doc_all_sections_latest(
    session: Session, *, domain: str | None = None
) -> list[GlobalDocVersion]:
    base = select(
        GlobalDocVersion.section_name.label("sn"),
        func.max(GlobalDocVersion.version).label("mv"),
    )
    df = _domain_filter(GlobalDocVersion.domain, domain)
    if df is not None:
        base = base.where(df)
    subq = base.group_by(GlobalDocVersion.section_name).subquery()
    q = select(GlobalDocVersion).join(
        subq,
        (GlobalDocVersion.section_name == subq.c.sn)
        & (GlobalDocVersion.version == subq.c.mv),
    )
    if df is not None:
        q = q.where(_domain_filter(GlobalDocVersion.domain, domain))
    rows = session.scalars(q).all()
    return sorted(rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _global_doc_latest(session: Session, section_name: str = DEFAULT_SECTION) -> GlobalDocVersion | None:
    max_v = (
        select(func.max(GlobalDocVersion.version))
        .where(GlobalDocVersion.section_name == section_name)
        .scalar_subquery()
    )
    return session.scalars(
        select(GlobalDocVersion).where(
            GlobalDocVersion.section_name == section_name,
            GlobalDocVersion.version == max_v,
        )
    ).first()


def next_global_doc_version(session: Session, section_name: str = DEFAULT_SECTION) -> int:
    cur = session.scalar(
        select(func.max(GlobalDocVersion.version)).where(
            GlobalDocVersion.section_name == section_name
        )
    )
    return (cur or 0) + 1


def publish_global_doc(
    session: Session, body: str, section_name: str = DEFAULT_SECTION, *, domain: str | None = None
) -> int:
    nv = next_global_doc_version(session, section_name)
    row = GlobalDocVersion(section_name=section_name, version=nv, body=body, domain=domain)
    session.add(row)
    session.commit()
    _try_index_doc(
        session, "global", row.id, body,
        domain=domain, section_name=section_name,
    )
    return nv


def delete_global_doc_version(session: Session, section_name: str, version: int) -> None:
    session.execute(
        delete(GlobalDocVersion).where(
            GlobalDocVersion.section_name == section_name,
            GlobalDocVersion.version == version,
        )
    )
    session.commit()


def delete_global_doc_section(session: Session, section_name: str) -> int:
    res = session.execute(
        delete(GlobalDocVersion).where(GlobalDocVersion.section_name == section_name)
    )
    session.commit()
    return res.rowcount


# ── App docs ─────────────────────────────────────────────────────────


def list_distinct_apps_with_docs(
    session: Session,
    *,
    domain: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[str]:
    q = select(AppDocVersion.app_name).distinct()
    df = _domain_filter(AppDocVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    rows = session.scalars(q).all()
    names = sorted({r for r in rows if r})
    if offset:
        names = names[offset:]
    if limit is not None:
        names = names[:limit]
    return names


def count_distinct_apps_with_docs(session: Session, *, domain: str | None = None) -> int:
    """AppDoc 스트림 수. 페이지네이션 UI 용."""
    q = select(func.count(func.distinct(AppDocVersion.app_name)))
    df = _domain_filter(AppDocVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    return int(session.scalar(q) or 0)


def list_sections_for_app_doc(session: Session, app_name: str) -> list[str]:
    key = (app_name or "").lower().strip()
    rows = session.scalars(
        select(AppDocVersion.section_name)
        .where(AppDocVersion.app_name == key)
        .distinct()
    ).all()
    return sorted({r for r in rows if r}, key=lambda s: ("" if s == DEFAULT_SECTION else s)) or [DEFAULT_SECTION]


def _app_doc_all_sections_latest(session: Session, app_name: str) -> list[AppDocVersion]:
    key = (app_name or "").lower().strip()
    subq = (
        select(
            AppDocVersion.section_name.label("sn"),
            func.max(AppDocVersion.version).label("mv"),
        )
        .where(AppDocVersion.app_name == key)
        .group_by(AppDocVersion.section_name)
        .subquery()
    )
    rows = session.scalars(
        select(AppDocVersion).join(
            subq,
            (AppDocVersion.app_name == key)
            & (AppDocVersion.section_name == subq.c.sn)
            & (AppDocVersion.version == subq.c.mv),
        )
    ).all()
    return sorted(rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _app_doc_latest(
    session: Session, app_name: str, section_name: str = DEFAULT_SECTION
) -> AppDocVersion | None:
    key = (app_name or "").lower().strip()
    max_v = (
        select(func.max(AppDocVersion.version))
        .where(AppDocVersion.app_name == key, AppDocVersion.section_name == section_name)
        .scalar_subquery()
    )
    return session.scalars(
        select(AppDocVersion).where(
            AppDocVersion.app_name == key,
            AppDocVersion.section_name == section_name,
            AppDocVersion.version == max_v,
        )
    ).first()


def next_app_doc_version(session: Session, app_name: str, section_name: str = DEFAULT_SECTION) -> int:
    key = (app_name or "").lower().strip()
    cur = session.scalar(
        select(func.max(AppDocVersion.version)).where(
            AppDocVersion.app_name == key,
            AppDocVersion.section_name == section_name,
        )
    )
    return (cur or 0) + 1


def publish_app_doc(
    session: Session, app_name: str, body: str, section_name: str = DEFAULT_SECTION, *, domain: str | None = None
) -> tuple[str, str, int]:
    key = (app_name or "").lower().strip()
    nv = next_app_doc_version(session, key, section_name)
    row = AppDocVersion(app_name=key, section_name=section_name, version=nv, body=body, domain=domain)
    session.add(row)
    session.commit()
    _try_index_doc(
        session, "app", row.id, body,
        app_name=key, domain=domain, section_name=section_name,
    )
    return key, section_name, nv


def delete_app_doc_version(session: Session, app_name: str, section_name: str, version: int) -> None:
    key = (app_name or "").lower().strip()
    session.execute(
        delete(AppDocVersion).where(
            AppDocVersion.app_name == key,
            AppDocVersion.section_name == section_name,
            AppDocVersion.version == version,
        )
    )
    session.commit()


def delete_app_doc_section(session: Session, app_name: str, section_name: str) -> int:
    key = (app_name or "").lower().strip()
    res = session.execute(
        delete(AppDocVersion).where(
            AppDocVersion.app_name == key,
            AppDocVersion.section_name == section_name,
        )
    )
    session.commit()
    return res.rowcount


def delete_app_doc_stream(session: Session, app_name: str) -> int:
    key = (app_name or "").lower().strip()
    res = session.execute(delete(AppDocVersion).where(AppDocVersion.app_name == key))
    session.commit()
    return res.rowcount


# ── Repo docs ────────────────────────────────────────────────────────


REPO_DOC_PATTERN_URL_DEFAULT = "__default__"


def repo_doc_pat_href_segment(pattern: str) -> str:
    return REPO_DOC_PATTERN_URL_DEFAULT if not (pattern or "").strip() else pattern


def repo_doc_pattern_from_url_segment(segment: str) -> str:
    return "" if segment == REPO_DOC_PATTERN_URL_DEFAULT else segment


def repo_doc_pattern_card_display(pattern: str) -> str:
    return "(default)" if not (pattern or "").strip() else pattern


def list_distinct_repo_patterns_with_docs(
    session: Session,
    *,
    domain: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[str]:
    q = select(RepoDocVersion.pattern).distinct()
    df = _domain_filter(RepoDocVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    rows = session.scalars(q).all()
    patterns = sorted({r or "" for r in rows}, key=lambda p: ("" if not p else p.lower()))
    if offset:
        patterns = patterns[offset:]
    if limit is not None:
        patterns = patterns[:limit]
    return patterns


def count_distinct_repo_patterns_with_docs(session: Session, *, domain: str | None = None) -> int:
    """RepoDoc 스트림 수. 페이지네이션 UI 용."""
    q = select(func.count(func.distinct(RepoDocVersion.pattern)))
    df = _domain_filter(RepoDocVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    return int(session.scalar(q) or 0)


def list_sections_for_repo_doc(session: Session, pattern: str) -> list[str]:
    key = (pattern or "").strip()
    rows = session.scalars(
        select(RepoDocVersion.section_name)
        .where(RepoDocVersion.pattern == key)
        .distinct()
    ).all()
    return sorted({r for r in rows if r}, key=lambda s: ("" if s == DEFAULT_SECTION else s)) or [DEFAULT_SECTION]


def _repo_doc_all_sections_latest(session: Session, pattern: str) -> list[RepoDocVersion]:
    key = (pattern or "").strip()
    subq = (
        select(
            RepoDocVersion.section_name.label("sn"),
            func.max(RepoDocVersion.version).label("mv"),
        )
        .where(RepoDocVersion.pattern == key)
        .group_by(RepoDocVersion.section_name)
        .subquery()
    )
    rows = session.scalars(
        select(RepoDocVersion).join(
            subq,
            (RepoDocVersion.pattern == key)
            & (RepoDocVersion.section_name == subq.c.sn)
            & (RepoDocVersion.version == subq.c.mv),
        )
    ).all()
    return sorted(rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _repo_doc_latest(
    session: Session, pattern: str, section_name: str = DEFAULT_SECTION
) -> RepoDocVersion | None:
    key = (pattern or "").strip()
    max_v = (
        select(func.max(RepoDocVersion.version))
        .where(RepoDocVersion.pattern == key, RepoDocVersion.section_name == section_name)
        .scalar_subquery()
    )
    return session.scalars(
        select(RepoDocVersion).where(
            RepoDocVersion.pattern == key,
            RepoDocVersion.section_name == section_name,
            RepoDocVersion.version == max_v,
        )
    ).first()


def next_repo_doc_version(session: Session, pattern: str, section_name: str = DEFAULT_SECTION) -> int:
    key = (pattern or "").strip()
    cur = session.scalar(
        select(func.max(RepoDocVersion.version)).where(
            RepoDocVersion.pattern == key,
            RepoDocVersion.section_name == section_name,
        )
    )
    return (cur or 0) + 1


def publish_repo_doc(
    session: Session,
    pattern: str,
    body: str,
    section_name: str = DEFAULT_SECTION,
    sort_order: int = 100,
    *,
    domain: str | None = None,
) -> tuple[str, str, int]:
    key = (pattern or "").strip()
    nv = next_repo_doc_version(session, key, section_name)
    row = RepoDocVersion(pattern=key, section_name=section_name, version=nv, body=body, sort_order=sort_order, domain=domain)
    session.add(row)
    session.commit()
    _try_index_doc(
        session, "repo", row.id, body,
        pattern=key, domain=domain, section_name=section_name,
    )
    return key, section_name, nv


def delete_repo_doc_version(session: Session, pattern: str, section_name: str, version: int) -> None:
    key = (pattern or "").strip()
    session.execute(
        delete(RepoDocVersion).where(
            RepoDocVersion.pattern == key,
            RepoDocVersion.section_name == section_name,
            RepoDocVersion.version == version,
        )
    )
    session.commit()


def delete_repo_doc_section(session: Session, pattern: str, section_name: str) -> int:
    key = (pattern or "").strip()
    res = session.execute(
        delete(RepoDocVersion).where(
            RepoDocVersion.pattern == key,
            RepoDocVersion.section_name == section_name,
        )
    )
    session.commit()
    return res.rowcount


def delete_repo_doc_stream(session: Session, pattern: str) -> int:
    key = (pattern or "").strip()
    res = session.execute(delete(RepoDocVersion).where(RepoDocVersion.pattern == key))
    session.commit()
    return res.rowcount


# ── MCP 응답 생성 (카테고리별 독립 파일 블록) ──────────────────────────────

_FILE_SEP = "=" * 60


def _doc_file_block(save_path: str, section_display: str, body: str) -> str:
    return (
        f"{_FILE_SEP}\n"
        f"DOC FILE: {save_path}\n"
        f"{_FILE_SEP}\n"
        f"{body}\n"
        f"{_FILE_SEP}\n"
        f"END DOC FILE: {save_path}\n"
        f"{_FILE_SEP}\n"
    )


_AGENT_DOC_SAVE_INSTRUCTIONS = """
---
[CRITICAL — 에이전트 필수 작업]

위 DOC FILE 블록들을 각각 독립 파일로 저장하세요.
저장 경로는 각 블록 헤더의 "DOC FILE: {경로}" 를 따르세요.

저장 규칙:
- 파일이 이미 존재하면 덮어쓰기
- 디렉터리가 없으면 생성

Docs      = 일반 문서 (레퍼런스, 가이드, 메모 등 자유 형식 문서)
Workflows = 오케스트레이터 (작업별 에이전트 팀 구성, 실행 순서) ← get_global_workflow 로 별도 관리
Skills    = 스킬 (시스템 구조, 환경, 패턴 등) ← get_global_skill 로 별도 관리
Rules     = 행동 지침 (반드시 따를 규칙) ← get_global_rule 로 별도 관리

문서 조회 후 관련 스킬이 필요하면 search_skills, 워크플로우는 get_global_workflow 를 사용하세요.
"""


def get_docs_markdown(
    session: Session,
    app_name: str | None = None,
    origin_url: str | None = None,
) -> str:
    blocks: list[str] = []

    global_rows = _global_doc_all_sections_latest(session)
    for row in global_rows:
        path = _global_doc_save_path(row.section_name)
        display = "기본" if row.section_name == DEFAULT_SECTION else row.section_name
        blocks.append(_doc_file_block(path, display, row.body))

    if origin_url:
        all_patterns = list_distinct_repo_patterns_with_docs(session)
        matched_patterns = [p for p in all_patterns if p and p in origin_url]
        if "" in all_patterns:
            matched_patterns = [""] + matched_patterns

        for pattern in matched_patterns:
            repo_rows = _repo_doc_all_sections_latest(session, pattern)
            for row in repo_rows:
                path = _repo_doc_save_path(pattern, row.section_name)
                display = "기본" if row.section_name == DEFAULT_SECTION else row.section_name
                blocks.append(_doc_file_block(path, display, row.body))

    if app_name:
        key = (app_name or "").lower().strip()
        app_rows = _app_doc_all_sections_latest(session, key)
        for row in app_rows:
            path = _app_doc_save_path(key, row.section_name)
            display = "기본" if row.section_name == DEFAULT_SECTION else row.section_name
            blocks.append(_doc_file_block(path, display, row.body))

    if not blocks:
        return "# Docs\n\n등록된 문서가 없습니다. 어드민 > 문서 메뉴에서 추가하세요."

    header = f"# Docs (문서)\n\n총 {len(blocks)}개 문서\n\n"
    return header + "\n".join(blocks) + _AGENT_DOC_SAVE_INSTRUCTIONS


# ── 문서 검색 (하이브리드 벡터 + FTS, fallback: ILIKE) ────────────────────


def _legacy_ilike_search_docs(
    session: Session,
    query: str,
    app_name: str | None,
    scope: str,
    top_n: int,
) -> list[dict]:
    """Fallback: 레거시 ILIKE 기반 키워드 검색 (벡터 인덱스 부재 시)."""
    q = (query or "").strip()
    if not q:
        return []

    like_pattern = f"%{q}%"
    results: list[dict] = []

    if scope in ("all", "global"):
        rows = session.scalars(
            select(GlobalDocVersion)
            .where(
                (GlobalDocVersion.section_name.ilike(like_pattern))
                | (GlobalDocVersion.body.ilike(like_pattern))
            )
            .order_by(GlobalDocVersion.version.desc())
            .limit(top_n)
        ).all()
        for r in rows:
            results.append({
                "scope": "global",
                "section_name": r.section_name,
                "version": r.version,
                "body": r.body,
                "domain": r.domain,
            })

    if scope in ("all", "app") and app_name:
        key = app_name.lower().strip()
        rows = session.scalars(
            select(AppDocVersion)
            .where(
                AppDocVersion.app_name == key,
                (AppDocVersion.section_name.ilike(like_pattern))
                | (AppDocVersion.body.ilike(like_pattern)),
            )
            .order_by(AppDocVersion.version.desc())
            .limit(top_n)
        ).all()
        for r in rows:
            results.append({
                "scope": "app",
                "app_name": r.app_name,
                "section_name": r.section_name,
                "version": r.version,
                "body": r.body,
                "domain": r.domain,
            })

    if scope in ("all", "repo"):
        rows = session.scalars(
            select(RepoDocVersion)
            .where(
                (RepoDocVersion.section_name.ilike(like_pattern))
                | (RepoDocVersion.body.ilike(like_pattern))
            )
            .order_by(RepoDocVersion.version.desc())
            .limit(top_n)
        ).all()
        for r in rows:
            results.append({
                "scope": "repo",
                "pattern": r.pattern,
                "section_name": r.section_name,
                "version": r.version,
                "body": r.body,
                "domain": r.domain,
            })

    return results[:top_n]


def _enrich_chunks_with_version_rows(
    session: Session,
    chunks: list[dict],
) -> list[dict]:
    """하이브리드 청크 결과 → 레거시 search_docs 응답 포맷으로 변환.

    scope/section_name별로 최신 version 테이블 row를 조회해 body/version/domain 필드를 채운다.
    같은 (doc_type, section_name, app_name/pattern) 조합은 한 번만 반환.
    """
    seen: set[tuple] = set()
    out: list[dict] = []
    for ch in chunks:
        wtype = ch.get("doc_type")
        section = ch.get("section_name") or DEFAULT_SECTION
        app = ch.get("app_name")
        pat = ch.get("pattern")

        key_tuple = (wtype, section, app, pat)
        if key_tuple in seen:
            continue
        seen.add(key_tuple)

        if wtype == "global":
            row = _global_doc_latest(session, section)
            if row is not None:
                out.append({
                    "scope": "global",
                    "section_name": row.section_name,
                    "version": row.version,
                    "body": row.body,
                    "domain": row.domain,
                })
        elif wtype == "app" and app:
            row = _app_doc_latest(session, app, section)
            if row is not None:
                out.append({
                    "scope": "app",
                    "app_name": row.app_name,
                    "section_name": row.section_name,
                    "version": row.version,
                    "body": row.body,
                    "domain": row.domain,
                })
        elif wtype == "repo":
            row = _repo_doc_latest(session, pat or "", section)
            if row is not None:
                out.append({
                    "scope": "repo",
                    "pattern": row.pattern,
                    "section_name": row.section_name,
                    "version": row.version,
                    "body": row.body,
                    "domain": row.domain,
                })
    return out


def search_docs(
    session: Session,
    query: str,
    app_name: str | None = None,
    scope: str = "all",
    top_n: int = 10,
) -> list[dict]:
    """하이브리드 벡터+FTS 검색. 인덱스 미존재 또는 매칭 없음 시 ILIKE 폴백."""
    q = (query or "").strip()
    if not q:
        return []

    try:
        from app.services.search_docs import hybrid_doc_search

        chunks, mode = hybrid_doc_search(
            session, query=q, app_name=app_name, scope=scope, top_n=top_n,
        )
        if mode == "hybrid_ok" and chunks:
            enriched = _enrich_chunks_with_version_rows(session, chunks)
            if enriched:
                return enriched[:top_n]
    except Exception:
        logger.warning("hybrid doc search failed, falling back to ILIKE", exc_info=True)

    return _legacy_ilike_search_docs(session, q, app_name, scope, top_n)


def update_app_doc(
    session: Session,
    app_name: str,
    section_name: str,
    body: str,
    *,
    domain: str | None = None,
) -> tuple[str, str, int]:
    """기존 문서의 새 버전을 발행하여 업데이트한다."""
    return publish_app_doc(session, app_name, body, section_name, domain=domain)
