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

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.workflow_models import AppWorkflowVersion, GlobalWorkflowVersion, RepoWorkflowVersion

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


# ── Global workflows ──────────────────────────────────────────────────────


def list_sections_for_global_workflow(session: Session) -> list[str]:
    rows = session.scalars(select(GlobalWorkflowVersion.section_name).distinct()).all()
    return sorted({r for r in rows if r}, key=lambda s: ("" if s == DEFAULT_SECTION else s)) or [DEFAULT_SECTION]


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


def list_distinct_apps_with_workflows(session: Session, *, domain: str | None = None) -> list[str]:
    q = select(AppWorkflowVersion.app_name).distinct()
    df = _domain_filter(AppWorkflowVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    rows = session.scalars(q).all()
    return sorted({r for r in rows if r})


def list_sections_for_app_workflow(session: Session, app_name: str) -> list[str]:
    key = (app_name or "").lower().strip()
    rows = session.scalars(
        select(AppWorkflowVersion.section_name)
        .where(AppWorkflowVersion.app_name == key)
        .distinct()
    ).all()
    return sorted({r for r in rows if r}, key=lambda s: ("" if s == DEFAULT_SECTION else s)) or [DEFAULT_SECTION]


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


def list_distinct_repo_patterns_with_workflows(session: Session, *, domain: str | None = None) -> list[str]:
    q = select(RepoWorkflowVersion.pattern).distinct()
    df = _domain_filter(RepoWorkflowVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    rows = session.scalars(q).all()
    return sorted({r or "" for r in rows}, key=lambda p: ("" if not p else p.lower()))


def list_sections_for_repo_workflow(session: Session, pattern: str) -> list[str]:
    key = (pattern or "").strip()
    rows = session.scalars(
        select(RepoWorkflowVersion.section_name)
        .where(RepoWorkflowVersion.pattern == key)
        .distinct()
    ).all()
    return sorted({r for r in rows if r}, key=lambda s: ("" if s == DEFAULT_SECTION else s)) or [DEFAULT_SECTION]


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


# ── 워크플로우 검색 (ILIKE 기반, 소수 데이터이므로 벡터 불필요) ──────────────


def search_workflows(
    session: Session,
    query: str,
    app_name: str | None = None,
    scope: str = "all",
    top_n: int = 10,
) -> list[dict]:
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
