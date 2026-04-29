"""Workflows 버전 관리 서비스 레이어.

Workflows = 오케스트레이터 (작업별 에이전트 팀 구성, 실행 순서, 기본 스킬)

MCP 응답 형식:
- get_global_workflow 호출 시 카테고리별로 별도 파일 블록 반환

저장 경로 규칙:
- Global:  .cursor/workflows/global/{section_name}.md
- Repo:    .cursor/workflows/repo/{pattern_slug}/{section_name}.md
- App:     .cursor/workflows/app/{app_name}/{section_name}.md
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.db.workflow_models import AppWorkflowVersion, GlobalWorkflowVersion, RepoWorkflowVersion
from app.workflow.service import make_default_workflow_service

logger = logging.getLogger(__name__)

DEFAULT_SECTION = "main"

# ── 저장 경로 헬퍼 ─────────────────────────────────────────────────────────


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\-.]", "_", s or "default")
    return s.strip("_") or "default"


def _global_workflow_save_path(section_name: str) -> str:
    return f".cursor/workflows/global/{_slug(section_name)}.md"


def _app_workflow_save_path(app_name: str, section_name: str) -> str:
    return f".cursor/workflows/app/{_slug(app_name)}/{_slug(section_name)}.md"


def _repo_workflow_save_path(pattern: str, section_name: str) -> str:
    pat_slug = _slug(pattern) if pattern else "default"
    return f".cursor/workflows/repo/{pat_slug}/{_slug(section_name)}.md"


# ── Domain filter ─────────────────────────────────────────────────────────


def _domain_filter(col, domain: str | None):
    if domain is None:
        return None
    if domain == "development":
        return (col == "development") | (col.is_(None))
    return col == domain


def _try_index_workflow(
    session: Session,
    workflow_type: str,
    workflow_entity_id: int,
    body: str,
    *,
    app_name: str | None = None,
    pattern: str | None = None,
    domain: str | None = None,
    section_name: str = DEFAULT_SECTION,
) -> None:
    """Best-effort workflow indexing after publish. Failure is logged, not raised."""
    try:
        svc = make_default_workflow_service(session)
        svc.index_workflow(
            workflow_type=workflow_type,
            workflow_entity_id=workflow_entity_id,
            body=body,
            app_name=app_name,
            pattern=pattern,
            domain=domain,
            section_name=section_name,
        )
    except Exception:
        logger.warning(
            "workflow indexing failed type=%s id=%s",
            workflow_type, workflow_entity_id, exc_info=True,
        )


# ── Global workflows ──────────────────────────────────────────────────────


def list_sections_for_global_workflow(session: Session) -> list[str]:
    """글로벌 워크플로의 모든 섹션 이름 (알파벳 순, 'main' 우선). DB 측에서 DISTINCT + ORDER BY 처리."""
    rank = case((GlobalWorkflowVersion.section_name == DEFAULT_SECTION, 0), else_=1)
    rows = session.execute(
        select(GlobalWorkflowVersion.section_name, rank)
        .distinct()
        .order_by(rank, GlobalWorkflowVersion.section_name)
    ).all()
    return [r[0] for r in rows if r[0]] or [DEFAULT_SECTION]


def _global_workflow_all_sections_latest(
    session: Session, *, domain: str | None = None
) -> list[GlobalWorkflowVersion]:
    base = select(
        GlobalWorkflowVersion.section_name.label("sn"),
        func.max(GlobalWorkflowVersion.version).label("mv"),
    )
    df = _domain_filter(GlobalWorkflowVersion.domain, domain)
    if df is not None:
        base = base.where(df)
    subq = base.group_by(GlobalWorkflowVersion.section_name).subquery()
    q = select(GlobalWorkflowVersion).join(
        subq,
        (GlobalWorkflowVersion.section_name == subq.c.sn)
        & (GlobalWorkflowVersion.version == subq.c.mv),
    )
    if df is not None:
        q = q.where(_domain_filter(GlobalWorkflowVersion.domain, domain))
    rows = session.scalars(q).all()
    return sorted(rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _global_workflow_latest(session: Session, section_name: str = DEFAULT_SECTION) -> GlobalWorkflowVersion | None:
    max_v = (
        select(func.max(GlobalWorkflowVersion.version))
        .where(GlobalWorkflowVersion.section_name == section_name)
        .scalar_subquery()
    )
    return session.scalars(
        select(GlobalWorkflowVersion).where(
            GlobalWorkflowVersion.section_name == section_name,
            GlobalWorkflowVersion.version == max_v,
        )
    ).first()


def next_global_workflow_version(session: Session, section_name: str = DEFAULT_SECTION) -> int:
    cur = session.scalar(
        select(func.max(GlobalWorkflowVersion.version)).where(
            GlobalWorkflowVersion.section_name == section_name
        )
    )
    return (cur or 0) + 1


def publish_global_workflow(
    session: Session, body: str, section_name: str = DEFAULT_SECTION, *, domain: str | None = None
) -> int:
    nv = next_global_workflow_version(session, section_name)
    row = GlobalWorkflowVersion(section_name=section_name, version=nv, body=body, domain=domain)
    session.add(row)
    session.commit()
    _try_index_workflow(
        session, "global", row.id, body,
        domain=domain, section_name=section_name,
    )
    return nv


def delete_global_workflow_version(session: Session, section_name: str, version: int) -> None:
    session.execute(
        delete(GlobalWorkflowVersion).where(
            GlobalWorkflowVersion.section_name == section_name,
            GlobalWorkflowVersion.version == version,
        )
    )
    session.commit()


def delete_global_workflow_section(session: Session, section_name: str) -> int:
    res = session.execute(
        delete(GlobalWorkflowVersion).where(GlobalWorkflowVersion.section_name == section_name)
    )
    session.commit()
    return res.rowcount


# ── App workflows ─────────────────────────────────────────────────────────


def list_distinct_apps_with_workflows(
    session: Session,
    *,
    domain: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[str]:
    q = select(AppWorkflowVersion.app_name).distinct()
    df = _domain_filter(AppWorkflowVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    rows = session.scalars(q).all()
    names = sorted({r for r in rows if r})
    if offset:
        names = names[offset:]
    if limit is not None:
        names = names[:limit]
    return names


def count_distinct_apps_with_workflows(session: Session, *, domain: str | None = None) -> int:
    """AppWorkflow 스트림 수. 페이지네이션 UI 용."""
    q = select(func.count(func.distinct(AppWorkflowVersion.app_name)))
    df = _domain_filter(AppWorkflowVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    return int(session.scalar(q) or 0)


def list_sections_for_app_workflow(session: Session, app_name: str) -> list[str]:
    """앱 워크플로의 모든 섹션 이름 (알파벳 순, 'main' 우선). DB 측에서 DISTINCT + ORDER BY 처리."""
    key = (app_name or "").lower().strip()
    rank = case((AppWorkflowVersion.section_name == DEFAULT_SECTION, 0), else_=1)
    rows = session.execute(
        select(AppWorkflowVersion.section_name, rank)
        .where(AppWorkflowVersion.app_name == key)
        .distinct()
        .order_by(rank, AppWorkflowVersion.section_name)
    ).all()
    return [r[0] for r in rows if r[0]] or [DEFAULT_SECTION]


def _app_workflow_all_sections_latest(session: Session, app_name: str) -> list[AppWorkflowVersion]:
    key = (app_name or "").lower().strip()
    subq = (
        select(
            AppWorkflowVersion.section_name.label("sn"),
            func.max(AppWorkflowVersion.version).label("mv"),
        )
        .where(AppWorkflowVersion.app_name == key)
        .group_by(AppWorkflowVersion.section_name)
        .subquery()
    )
    rows = session.scalars(
        select(AppWorkflowVersion).join(
            subq,
            (AppWorkflowVersion.app_name == key)
            & (AppWorkflowVersion.section_name == subq.c.sn)
            & (AppWorkflowVersion.version == subq.c.mv),
        )
    ).all()
    return sorted(rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _app_workflow_latest(
    session: Session, app_name: str, section_name: str = DEFAULT_SECTION
) -> AppWorkflowVersion | None:
    key = (app_name or "").lower().strip()
    max_v = (
        select(func.max(AppWorkflowVersion.version))
        .where(AppWorkflowVersion.app_name == key, AppWorkflowVersion.section_name == section_name)
        .scalar_subquery()
    )
    return session.scalars(
        select(AppWorkflowVersion).where(
            AppWorkflowVersion.app_name == key,
            AppWorkflowVersion.section_name == section_name,
            AppWorkflowVersion.version == max_v,
        )
    ).first()


def next_app_workflow_version(session: Session, app_name: str, section_name: str = DEFAULT_SECTION) -> int:
    key = (app_name or "").lower().strip()
    cur = session.scalar(
        select(func.max(AppWorkflowVersion.version)).where(
            AppWorkflowVersion.app_name == key,
            AppWorkflowVersion.section_name == section_name,
        )
    )
    return (cur or 0) + 1


def publish_app_workflow(
    session: Session, app_name: str, body: str, section_name: str = DEFAULT_SECTION, *, domain: str | None = None
) -> tuple[str, str, int]:
    key = (app_name or "").lower().strip()
    nv = next_app_workflow_version(session, key, section_name)
    row = AppWorkflowVersion(app_name=key, section_name=section_name, version=nv, body=body, domain=domain)
    session.add(row)
    session.commit()
    _try_index_workflow(
        session, "app", row.id, body,
        app_name=key, domain=domain, section_name=section_name,
    )
    return key, section_name, nv


def delete_app_workflow_version(session: Session, app_name: str, section_name: str, version: int) -> None:
    key = (app_name or "").lower().strip()
    session.execute(
        delete(AppWorkflowVersion).where(
            AppWorkflowVersion.app_name == key,
            AppWorkflowVersion.section_name == section_name,
            AppWorkflowVersion.version == version,
        )
    )
    session.commit()


def delete_app_workflow_section(session: Session, app_name: str, section_name: str) -> int:
    key = (app_name or "").lower().strip()
    res = session.execute(
        delete(AppWorkflowVersion).where(
            AppWorkflowVersion.app_name == key,
            AppWorkflowVersion.section_name == section_name,
        )
    )
    session.commit()
    return res.rowcount


def delete_app_workflow_stream(session: Session, app_name: str) -> int:
    key = (app_name or "").lower().strip()
    res = session.execute(delete(AppWorkflowVersion).where(AppWorkflowVersion.app_name == key))
    session.commit()
    return res.rowcount


# ── Repo workflows ────────────────────────────────────────────────────────


REPO_WORKFLOW_PATTERN_URL_DEFAULT = "__default__"


def repo_workflow_pat_href_segment(pattern: str) -> str:
    return REPO_WORKFLOW_PATTERN_URL_DEFAULT if not (pattern or "").strip() else pattern


def repo_workflow_pattern_from_url_segment(segment: str) -> str:
    return "" if segment == REPO_WORKFLOW_PATTERN_URL_DEFAULT else segment


def repo_workflow_pattern_card_display(pattern: str) -> str:
    return "(default)" if not (pattern or "").strip() else pattern


def list_distinct_repo_patterns_with_workflows(
    session: Session,
    *,
    domain: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[str]:
    q = select(RepoWorkflowVersion.pattern).distinct()
    df = _domain_filter(RepoWorkflowVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    rows = session.scalars(q).all()
    patterns = sorted({r or "" for r in rows}, key=lambda p: ("" if not p else p.lower()))
    if offset:
        patterns = patterns[offset:]
    if limit is not None:
        patterns = patterns[:limit]
    return patterns


def count_distinct_repo_patterns_with_workflows(session: Session, *, domain: str | None = None) -> int:
    """RepoWorkflow 스트림 수. 페이지네이션 UI 용."""
    q = select(func.count(func.distinct(RepoWorkflowVersion.pattern)))
    df = _domain_filter(RepoWorkflowVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    return int(session.scalar(q) or 0)


def list_sections_for_repo_workflow(session: Session, pattern: str) -> list[str]:
    """레포 워크플로의 모든 섹션 이름 (알파벳 순, 'main' 우선). DB 측에서 DISTINCT + ORDER BY 처리."""
    key = (pattern or "").strip()
    rank = case((RepoWorkflowVersion.section_name == DEFAULT_SECTION, 0), else_=1)
    rows = session.execute(
        select(RepoWorkflowVersion.section_name, rank)
        .where(RepoWorkflowVersion.pattern == key)
        .distinct()
        .order_by(rank, RepoWorkflowVersion.section_name)
    ).all()
    return [r[0] for r in rows if r[0]] or [DEFAULT_SECTION]


def _repo_workflow_all_sections_latest(session: Session, pattern: str) -> list[RepoWorkflowVersion]:
    key = (pattern or "").strip()
    subq = (
        select(
            RepoWorkflowVersion.section_name.label("sn"),
            func.max(RepoWorkflowVersion.version).label("mv"),
        )
        .where(RepoWorkflowVersion.pattern == key)
        .group_by(RepoWorkflowVersion.section_name)
        .subquery()
    )
    rows = session.scalars(
        select(RepoWorkflowVersion).join(
            subq,
            (RepoWorkflowVersion.pattern == key)
            & (RepoWorkflowVersion.section_name == subq.c.sn)
            & (RepoWorkflowVersion.version == subq.c.mv),
        )
    ).all()
    return sorted(rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _repo_workflow_latest(
    session: Session, pattern: str, section_name: str = DEFAULT_SECTION
) -> RepoWorkflowVersion | None:
    key = (pattern or "").strip()
    max_v = (
        select(func.max(RepoWorkflowVersion.version))
        .where(RepoWorkflowVersion.pattern == key, RepoWorkflowVersion.section_name == section_name)
        .scalar_subquery()
    )
    return session.scalars(
        select(RepoWorkflowVersion).where(
            RepoWorkflowVersion.pattern == key,
            RepoWorkflowVersion.section_name == section_name,
            RepoWorkflowVersion.version == max_v,
        )
    ).first()


def next_repo_workflow_version(session: Session, pattern: str, section_name: str = DEFAULT_SECTION) -> int:
    key = (pattern or "").strip()
    cur = session.scalar(
        select(func.max(RepoWorkflowVersion.version)).where(
            RepoWorkflowVersion.pattern == key,
            RepoWorkflowVersion.section_name == section_name,
        )
    )
    return (cur or 0) + 1


def publish_repo_workflow(
    session: Session,
    pattern: str,
    body: str,
    section_name: str = DEFAULT_SECTION,
    sort_order: int = 100,
    *,
    domain: str | None = None,
) -> tuple[str, str, int]:
    key = (pattern or "").strip()
    nv = next_repo_workflow_version(session, key, section_name)
    row = RepoWorkflowVersion(pattern=key, section_name=section_name, version=nv, body=body, sort_order=sort_order, domain=domain)
    session.add(row)
    session.commit()
    _try_index_workflow(
        session, "repo", row.id, body,
        pattern=key, domain=domain, section_name=section_name,
    )
    return key, section_name, nv


def delete_repo_workflow_version(session: Session, pattern: str, section_name: str, version: int) -> None:
    key = (pattern or "").strip()
    session.execute(
        delete(RepoWorkflowVersion).where(
            RepoWorkflowVersion.pattern == key,
            RepoWorkflowVersion.section_name == section_name,
            RepoWorkflowVersion.version == version,
        )
    )
    session.commit()


def delete_repo_workflow_section(session: Session, pattern: str, section_name: str) -> int:
    key = (pattern or "").strip()
    res = session.execute(
        delete(RepoWorkflowVersion).where(
            RepoWorkflowVersion.pattern == key,
            RepoWorkflowVersion.section_name == section_name,
        )
    )
    session.commit()
    return res.rowcount


def delete_repo_workflow_stream(session: Session, pattern: str) -> int:
    key = (pattern or "").strip()
    res = session.execute(delete(RepoWorkflowVersion).where(RepoWorkflowVersion.pattern == key))
    session.commit()
    return res.rowcount


# ── MCP 응답 생성 (카테고리별 독립 파일 블록) ──────────────────────────────

_FILE_SEP = "=" * 60


def _workflow_file_block(save_path: str, section_display: str, body: str) -> str:
    return (
        f"{_FILE_SEP}\n"
        f"WORKFLOW FILE: {save_path}\n"
        f"{_FILE_SEP}\n"
        f"{body}\n"
        f"{_FILE_SEP}\n"
        f"END WORKFLOW FILE: {save_path}\n"
        f"{_FILE_SEP}\n"
    )


_AGENT_WORKFLOW_SAVE_INSTRUCTIONS = """
---
[CRITICAL — 에이전트 필수 작업]

위 WORKFLOW FILE 블록들을 각각 독립 파일로 저장하세요.
저장 경로는 각 블록 헤더의 "WORKFLOW FILE: {경로}" 를 따르세요.

저장 규칙:
- 파일이 이미 존재하면 덮어쓰기
- 디렉터리가 없으면 생성

Workflows = 오케스트레이터 (작업별 에이전트 팀 구성, 실행 순서)
Skills    = 스킬 (시스템 구조, 환경, 패턴 등) ← get_global_skill 로 별도 관리
Rules     = 행동 지침 (반드시 따를 규칙) ← get_global_rule 로 별도 관리

워크플로우 실행 중 필요한 스킬은 search_skills 로 on-demand 검색하여 사용하세요.
"""


def get_workflows_markdown(
    session: Session,
    app_name: str | None = None,
    origin_url: str | None = None,
) -> str:
    blocks: list[str] = []

    global_rows = _global_workflow_all_sections_latest(session)
    for row in global_rows:
        path = _global_workflow_save_path(row.section_name)
        display = "기본" if row.section_name == DEFAULT_SECTION else row.section_name
        blocks.append(_workflow_file_block(path, display, row.body))

    if origin_url:
        all_patterns = list_distinct_repo_patterns_with_workflows(session)
        matched_patterns = [p for p in all_patterns if p and p in origin_url]
        if "" in all_patterns:
            matched_patterns = [""] + matched_patterns

        for pattern in matched_patterns:
            repo_rows = _repo_workflow_all_sections_latest(session, pattern)
            for row in repo_rows:
                path = _repo_workflow_save_path(pattern, row.section_name)
                display = "기본" if row.section_name == DEFAULT_SECTION else row.section_name
                blocks.append(_workflow_file_block(path, display, row.body))

    if app_name:
        key = (app_name or "").lower().strip()
        app_rows = _app_workflow_all_sections_latest(session, key)
        for row in app_rows:
            path = _app_workflow_save_path(key, row.section_name)
            display = "기본" if row.section_name == DEFAULT_SECTION else row.section_name
            blocks.append(_workflow_file_block(path, display, row.body))

    if not blocks:
        return "# Workflows\n\n등록된 워크플로우가 없습니다. 어드민 > 워크플로우 메뉴에서 추가하세요."

    header = f"# Workflows (워크플로우)\n\n총 {len(blocks)}개 워크플로우\n\n"
    return header + "\n".join(blocks) + _AGENT_WORKFLOW_SAVE_INSTRUCTIONS


# ── 워크플로우 검색 (하이브리드 벡터 + FTS, fallback: ILIKE) ──────────────


def _legacy_ilike_search_workflows(
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
            select(GlobalWorkflowVersion)
            .where(
                (GlobalWorkflowVersion.section_name.ilike(like_pattern))
                | (GlobalWorkflowVersion.body.ilike(like_pattern))
            )
            .order_by(GlobalWorkflowVersion.version.desc())
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
            select(AppWorkflowVersion)
            .where(
                AppWorkflowVersion.app_name == key,
                (AppWorkflowVersion.section_name.ilike(like_pattern))
                | (AppWorkflowVersion.body.ilike(like_pattern)),
            )
            .order_by(AppWorkflowVersion.version.desc())
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
            select(RepoWorkflowVersion)
            .where(
                (RepoWorkflowVersion.section_name.ilike(like_pattern))
                | (RepoWorkflowVersion.body.ilike(like_pattern))
            )
            .order_by(RepoWorkflowVersion.version.desc())
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
    """하이브리드 청크 결과 → 레거시 search_workflows 응답 포맷으로 변환.

    scope/section_name별로 최신 version 테이블 row를 조회해 body/version/domain 필드를 채운다.
    같은 (workflow_type, section_name, app_name/pattern) 조합은 한 번만 반환.
    """
    seen: set[tuple] = set()
    out: list[dict] = []
    for ch in chunks:
        wtype = ch.get("workflow_type")
        section = ch.get("section_name") or DEFAULT_SECTION
        app = ch.get("app_name")
        pat = ch.get("pattern")

        key_tuple = (wtype, section, app, pat)
        if key_tuple in seen:
            continue
        seen.add(key_tuple)

        if wtype == "global":
            row = _global_workflow_latest(session, section)
            if row is not None:
                out.append({
                    "scope": "global",
                    "section_name": row.section_name,
                    "version": row.version,
                    "body": row.body,
                    "domain": row.domain,
                })
        elif wtype == "app" and app:
            row = _app_workflow_latest(session, app, section)
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
            row = _repo_workflow_latest(session, pat or "", section)
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


def search_workflows(
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
        from app.services.search_workflows import hybrid_workflow_search

        chunks, mode = hybrid_workflow_search(
            session, query=q, app_name=app_name, scope=scope, top_n=top_n,
        )
        if mode == "hybrid_ok" and chunks:
            enriched = _enrich_chunks_with_version_rows(session, chunks)
            if enriched:
                return enriched[:top_n]
    except Exception:
        logger.warning("hybrid workflow search failed, falling back to ILIKE", exc_info=True)

    return _legacy_ilike_search_workflows(session, q, app_name, scope, top_n)


def update_app_workflow(
    session: Session,
    app_name: str,
    section_name: str,
    body: str,
    *,
    domain: str | None = None,
) -> tuple[str, str, int]:
    """기존 워크플로우의 새 버전을 발행하여 업데이트한다."""
    return publish_app_workflow(session, app_name, body, section_name, domain=domain)


# ── Mermaid 다이어그램 저장 (버전 단위, 제자리 업데이트) ────────────────


def set_workflow_mermaid(
    session: Session,
    *,
    scope: str,
    section_name: str,
    version: int,
    mermaid: str,
    app_name: str | None = None,
    pattern: str | None = None,
) -> bool:
    """특정 워크플로우 버전의 `mermaid` 필드를 업데이트한다 (새 버전 발행 아님).

    Args:
        scope: "global" | "app" | "repo"
        section_name: 섹션 이름
        version: 대상 버전 번호
        mermaid: Mermaid 다이어그램 텍스트 (예: ``flowchart TD\n  A --> B``)
        app_name: scope="app" 시 필수
        pattern: scope="repo" 시 사용 (빈 문자열 = default 스트림)

    Returns:
        업데이트 성공 시 True, 대상 행 없으면 False.
    """
    mermaid = (mermaid or "").strip() or None
    scope = (scope or "").lower().strip()

    if scope == "global":
        row = _global_workflow_latest(session, section_name)
        if row is None or row.version != version:
            row = session.scalars(
                select(GlobalWorkflowVersion).where(
                    GlobalWorkflowVersion.section_name == section_name,
                    GlobalWorkflowVersion.version == version,
                )
            ).first()
    elif scope == "app":
        if not app_name:
            return False
        key = (app_name or "").lower().strip()
        row = session.scalars(
            select(AppWorkflowVersion).where(
                AppWorkflowVersion.app_name == key,
                AppWorkflowVersion.section_name == section_name,
                AppWorkflowVersion.version == version,
            )
        ).first()
    elif scope == "repo":
        pat = (pattern or "").strip()
        row = session.scalars(
            select(RepoWorkflowVersion).where(
                RepoWorkflowVersion.pattern == pat,
                RepoWorkflowVersion.section_name == section_name,
                RepoWorkflowVersion.version == version,
            )
        ).first()
    else:
        return False

    if row is None:
        return False
    row.mermaid = mermaid
    session.commit()
    return True


def get_workflow_mermaid(
    session: Session,
    *,
    scope: str,
    section_name: str,
    version: int,
    app_name: str | None = None,
    pattern: str | None = None,
) -> str | None:
    """특정 워크플로우 버전의 `mermaid` 필드를 조회."""
    scope = (scope or "").lower().strip()
    if scope == "global":
        row = session.scalars(
            select(GlobalWorkflowVersion).where(
                GlobalWorkflowVersion.section_name == section_name,
                GlobalWorkflowVersion.version == version,
            )
        ).first()
    elif scope == "app":
        if not app_name:
            return None
        key = (app_name or "").lower().strip()
        row = session.scalars(
            select(AppWorkflowVersion).where(
                AppWorkflowVersion.app_name == key,
                AppWorkflowVersion.section_name == section_name,
                AppWorkflowVersion.version == version,
            )
        ).first()
    elif scope == "repo":
        pat = (pattern or "").strip()
        row = session.scalars(
            select(RepoWorkflowVersion).where(
                RepoWorkflowVersion.pattern == pat,
                RepoWorkflowVersion.section_name == section_name,
                RepoWorkflowVersion.version == version,
            )
        ).first()
    else:
        return None
    return row.mermaid if row else None
