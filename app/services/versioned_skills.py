"""Skills 버전 관리 서비스 레이어.

Skills = 스킬 / 시스템 이해 (Rules = 행동 지침과 구분)

MCP 응답 형식:
- get_global_skill 호출 시 카테고리별로 별도 파일 블록 반환
- 에이전트는 각 블록을 독립 파일로 저장

저장 경로 규칙:
- Global:  .cursor/skills/global/{section_name}.md
- Repo:    .cursor/skills/repo/{pattern_slug}/{section_name}.md
- App:     .cursor/skills/app/{app_name}/{section_name}.md
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.db.skill_models import AppSkillVersion, GlobalSkillVersion, RepoSkillVersion
from app.skill.service import make_default_skill_service

logger = logging.getLogger(__name__)

DEFAULT_SECTION = "main"

# ── 저장 경로 헬퍼 ─────────────────────────────────────────────────────────


def _slug(s: str) -> str:
    """패턴/이름을 파일시스템 안전 슬러그로 변환."""
    s = re.sub(r"[^\w\-.]", "_", s or "default")
    return s.strip("_") or "default"


def _global_skill_save_path(section_name: str) -> str:
    return f".cursor/skills/global/{_slug(section_name)}.md"


def _app_skill_save_path(app_name: str, section_name: str) -> str:
    return f".cursor/skills/app/{_slug(app_name)}/{_slug(section_name)}.md"


def _repo_skill_save_path(pattern: str, section_name: str) -> str:
    pat_slug = _slug(pattern) if pattern else "default"
    return f".cursor/skills/repo/{pat_slug}/{_slug(section_name)}.md"


# ── Global skills ──────────────────────────────────────────────────────────


def list_sections_for_global_skill(session: Session) -> list[str]:
    """글로벌 스킬의 모든 섹션 이름 (알파벳 순, 'main' 우선). DB 측에서 DISTINCT + ORDER BY 처리."""
    rank = case((GlobalSkillVersion.section_name == DEFAULT_SECTION, 0), else_=1)
    rows = session.execute(
        select(GlobalSkillVersion.section_name, rank)
        .distinct()
        .order_by(rank, GlobalSkillVersion.section_name)
    ).all()
    return [r[0] for r in rows if r[0]] or [DEFAULT_SECTION]


def _domain_filter(col, domain: str | None):
    """domain 필터 조건 생성. development는 NULL도 포함."""
    if domain is None:
        return None
    if domain == "development":
        return (col == "development") | (col.is_(None))
    return col == domain


def _global_skill_all_sections_latest(
    session: Session, *, domain: str | None = None
) -> list[GlobalSkillVersion]:
    base = select(
        GlobalSkillVersion.section_name.label("sn"),
        func.max(GlobalSkillVersion.version).label("mv"),
    )
    df = _domain_filter(GlobalSkillVersion.domain, domain)
    if df is not None:
        base = base.where(df)
    subq = base.group_by(GlobalSkillVersion.section_name).subquery()
    q = select(GlobalSkillVersion).join(
        subq,
        (GlobalSkillVersion.section_name == subq.c.sn)
        & (GlobalSkillVersion.version == subq.c.mv),
    )
    if df is not None:
        q = q.where(_domain_filter(GlobalSkillVersion.domain, domain))
    rows = session.scalars(q).all()
    return sorted(rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _global_skill_latest(session: Session, section_name: str = DEFAULT_SECTION) -> GlobalSkillVersion | None:
    max_v = (
        select(func.max(GlobalSkillVersion.version))
        .where(GlobalSkillVersion.section_name == section_name)
        .scalar_subquery()
    )
    return session.scalars(
        select(GlobalSkillVersion).where(
            GlobalSkillVersion.section_name == section_name,
            GlobalSkillVersion.version == max_v,
        )
    ).first()


def next_global_skill_version(session: Session, section_name: str = DEFAULT_SECTION) -> int:
    cur = session.scalar(
        select(func.max(GlobalSkillVersion.version)).where(
            GlobalSkillVersion.section_name == section_name
        )
    )
    return (cur or 0) + 1


def _try_index_skill(
    session: Session,
    skill_type: str,
    skill_entity_id: int,
    body: str,
    *,
    app_name: str | None = None,
    domain: str | None = None,
    section_name: str = DEFAULT_SECTION,
) -> None:
    """Best-effort skill indexing after publish. Failure is logged, not raised."""
    try:
        svc = make_default_skill_service(session)
        svc.index_skill(
            skill_type=skill_type,
            skill_entity_id=skill_entity_id,
            body=body,
            app_name=app_name,
            domain=domain,
            section_name=section_name,
        )
    except Exception:
        logger.warning("skill indexing failed type=%s id=%s", skill_type, skill_entity_id, exc_info=True)


def publish_global_skill(
    session: Session, body: str, section_name: str = DEFAULT_SECTION, *, domain: str | None = None
) -> int:
    nv = next_global_skill_version(session, section_name)
    row = GlobalSkillVersion(section_name=section_name, version=nv, body=body, domain=domain)
    session.add(row)
    session.commit()
    _try_index_skill(session, "global", row.id, body, domain=domain, section_name=section_name)
    return nv


def delete_global_skill_version(session: Session, section_name: str, version: int) -> None:
    session.execute(
        delete(GlobalSkillVersion).where(
            GlobalSkillVersion.section_name == section_name,
            GlobalSkillVersion.version == version,
        )
    )
    session.commit()


def delete_global_skill_section(session: Session, section_name: str) -> int:
    res = session.execute(
        delete(GlobalSkillVersion).where(GlobalSkillVersion.section_name == section_name)
    )
    session.commit()
    return res.rowcount


# ── App skills ─────────────────────────────────────────────────────────────


def list_distinct_apps_with_skills(
    session: Session,
    *,
    domain: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[str]:
    q = select(AppSkillVersion.app_name).distinct()
    df = _domain_filter(AppSkillVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    rows = session.scalars(q).all()
    names = sorted({r for r in rows if r})
    if offset:
        names = names[offset:]
    if limit is not None:
        names = names[:limit]
    return names


def count_distinct_apps_with_skills(session: Session, *, domain: str | None = None) -> int:
    """AppSkill 스트림 수. 페이지네이션 UI 용."""
    q = select(func.count(func.distinct(AppSkillVersion.app_name)))
    df = _domain_filter(AppSkillVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    return int(session.scalar(q) or 0)


def list_sections_for_app_skill(session: Session, app_name: str) -> list[str]:
    """앱 스킬의 모든 섹션 이름 (알파벳 순, 'main' 우선). DB 측에서 DISTINCT + ORDER BY 처리."""
    key = (app_name or "").lower().strip()
    rank = case((AppSkillVersion.section_name == DEFAULT_SECTION, 0), else_=1)
    rows = session.execute(
        select(AppSkillVersion.section_name, rank)
        .where(AppSkillVersion.app_name == key)
        .distinct()
        .order_by(rank, AppSkillVersion.section_name)
    ).all()
    return [r[0] for r in rows if r[0]] or [DEFAULT_SECTION]


def _app_skill_all_sections_latest(session: Session, app_name: str) -> list[AppSkillVersion]:
    key = (app_name or "").lower().strip()
    subq = (
        select(
            AppSkillVersion.section_name.label("sn"),
            func.max(AppSkillVersion.version).label("mv"),
        )
        .where(AppSkillVersion.app_name == key)
        .group_by(AppSkillVersion.section_name)
        .subquery()
    )
    rows = session.scalars(
        select(AppSkillVersion).join(
            subq,
            (AppSkillVersion.app_name == key)
            & (AppSkillVersion.section_name == subq.c.sn)
            & (AppSkillVersion.version == subq.c.mv),
        )
    ).all()
    return sorted(rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _app_skill_latest(
    session: Session, app_name: str, section_name: str = DEFAULT_SECTION
) -> AppSkillVersion | None:
    key = (app_name or "").lower().strip()
    max_v = (
        select(func.max(AppSkillVersion.version))
        .where(AppSkillVersion.app_name == key, AppSkillVersion.section_name == section_name)
        .scalar_subquery()
    )
    return session.scalars(
        select(AppSkillVersion).where(
            AppSkillVersion.app_name == key,
            AppSkillVersion.section_name == section_name,
            AppSkillVersion.version == max_v,
        )
    ).first()


def next_app_skill_version(session: Session, app_name: str, section_name: str = DEFAULT_SECTION) -> int:
    key = (app_name or "").lower().strip()
    cur = session.scalar(
        select(func.max(AppSkillVersion.version)).where(
            AppSkillVersion.app_name == key,
            AppSkillVersion.section_name == section_name,
        )
    )
    return (cur or 0) + 1


def publish_app_skill(
    session: Session, app_name: str, body: str, section_name: str = DEFAULT_SECTION, *, domain: str | None = None
) -> tuple[str, str, int]:
    key = (app_name or "").lower().strip()
    nv = next_app_skill_version(session, key, section_name)
    row = AppSkillVersion(app_name=key, section_name=section_name, version=nv, body=body, domain=domain)
    session.add(row)
    session.commit()
    _try_index_skill(session, "app", row.id, body, app_name=key, domain=domain, section_name=section_name)
    return key, section_name, nv


def delete_app_skill_version(session: Session, app_name: str, section_name: str, version: int) -> None:
    key = (app_name or "").lower().strip()
    session.execute(
        delete(AppSkillVersion).where(
            AppSkillVersion.app_name == key,
            AppSkillVersion.section_name == section_name,
            AppSkillVersion.version == version,
        )
    )
    session.commit()


def delete_app_skill_section(session: Session, app_name: str, section_name: str) -> int:
    key = (app_name or "").lower().strip()
    res = session.execute(
        delete(AppSkillVersion).where(
            AppSkillVersion.app_name == key,
            AppSkillVersion.section_name == section_name,
        )
    )
    session.commit()
    return res.rowcount


def delete_app_skill_stream(session: Session, app_name: str) -> int:
    key = (app_name or "").lower().strip()
    res = session.execute(delete(AppSkillVersion).where(AppSkillVersion.app_name == key))
    session.commit()
    return res.rowcount


# ── Repo skills ────────────────────────────────────────────────────────────


REPO_SKILL_PATTERN_URL_DEFAULT = "__default__"


def repo_skill_pat_href_segment(pattern: str) -> str:
    return REPO_SKILL_PATTERN_URL_DEFAULT if not (pattern or "").strip() else pattern


def repo_skill_pattern_from_url_segment(segment: str) -> str:
    return "" if segment == REPO_SKILL_PATTERN_URL_DEFAULT else segment


def repo_skill_pattern_card_display(pattern: str) -> str:
    return "(default)" if not (pattern or "").strip() else pattern


def list_distinct_repo_patterns_with_skills(
    session: Session,
    *,
    domain: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[str]:
    q = select(RepoSkillVersion.pattern).distinct()
    df = _domain_filter(RepoSkillVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    rows = session.scalars(q).all()
    patterns = sorted({r or "" for r in rows}, key=lambda p: ("" if not p else p.lower()))
    if offset:
        patterns = patterns[offset:]
    if limit is not None:
        patterns = patterns[:limit]
    return patterns


def count_distinct_repo_patterns_with_skills(session: Session, *, domain: str | None = None) -> int:
    """RepoSkill 스트림 수. 페이지네이션 UI 용."""
    q = select(func.count(func.distinct(RepoSkillVersion.pattern)))
    df = _domain_filter(RepoSkillVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    return int(session.scalar(q) or 0)


def list_sections_for_repo_skill(session: Session, pattern: str) -> list[str]:
    """레포 스킬의 모든 섹션 이름 (알파벳 순, 'main' 우선). DB 측에서 DISTINCT + ORDER BY 처리."""
    key = (pattern or "").strip()
    rank = case((RepoSkillVersion.section_name == DEFAULT_SECTION, 0), else_=1)
    rows = session.execute(
        select(RepoSkillVersion.section_name, rank)
        .where(RepoSkillVersion.pattern == key)
        .distinct()
        .order_by(rank, RepoSkillVersion.section_name)
    ).all()
    return [r[0] for r in rows if r[0]] or [DEFAULT_SECTION]


def _repo_skill_all_sections_latest(session: Session, pattern: str) -> list[RepoSkillVersion]:
    key = (pattern or "").strip()
    subq = (
        select(
            RepoSkillVersion.section_name.label("sn"),
            func.max(RepoSkillVersion.version).label("mv"),
        )
        .where(RepoSkillVersion.pattern == key)
        .group_by(RepoSkillVersion.section_name)
        .subquery()
    )
    rows = session.scalars(
        select(RepoSkillVersion).join(
            subq,
            (RepoSkillVersion.pattern == key)
            & (RepoSkillVersion.section_name == subq.c.sn)
            & (RepoSkillVersion.version == subq.c.mv),
        )
    ).all()
    return sorted(rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _repo_skill_latest(
    session: Session, pattern: str, section_name: str = DEFAULT_SECTION
) -> RepoSkillVersion | None:
    key = (pattern or "").strip()
    max_v = (
        select(func.max(RepoSkillVersion.version))
        .where(RepoSkillVersion.pattern == key, RepoSkillVersion.section_name == section_name)
        .scalar_subquery()
    )
    return session.scalars(
        select(RepoSkillVersion).where(
            RepoSkillVersion.pattern == key,
            RepoSkillVersion.section_name == section_name,
            RepoSkillVersion.version == max_v,
        )
    ).first()


def next_repo_skill_version(session: Session, pattern: str, section_name: str = DEFAULT_SECTION) -> int:
    key = (pattern or "").strip()
    cur = session.scalar(
        select(func.max(RepoSkillVersion.version)).where(
            RepoSkillVersion.pattern == key,
            RepoSkillVersion.section_name == section_name,
        )
    )
    return (cur or 0) + 1


def publish_repo_skill(
    session: Session,
    pattern: str,
    body: str,
    section_name: str = DEFAULT_SECTION,
    sort_order: int = 100,
    *,
    domain: str | None = None,
) -> tuple[str, str, int]:
    key = (pattern or "").strip()
    nv = next_repo_skill_version(session, key, section_name)
    row = RepoSkillVersion(pattern=key, section_name=section_name, version=nv, body=body, sort_order=sort_order, domain=domain)
    session.add(row)
    session.commit()
    _try_index_skill(session, "repo", row.id, body, domain=domain, section_name=section_name)
    return key, section_name, nv


def delete_repo_skill_version(session: Session, pattern: str, section_name: str, version: int) -> None:
    key = (pattern or "").strip()
    session.execute(
        delete(RepoSkillVersion).where(
            RepoSkillVersion.pattern == key,
            RepoSkillVersion.section_name == section_name,
            RepoSkillVersion.version == version,
        )
    )
    session.commit()


def delete_repo_skill_section(session: Session, pattern: str, section_name: str) -> int:
    key = (pattern or "").strip()
    res = session.execute(
        delete(RepoSkillVersion).where(
            RepoSkillVersion.pattern == key,
            RepoSkillVersion.section_name == section_name,
        )
    )
    session.commit()
    return res.rowcount


def delete_repo_skill_stream(session: Session, pattern: str) -> int:
    key = (pattern or "").strip()
    res = session.execute(delete(RepoSkillVersion).where(RepoSkillVersion.pattern == key))
    session.commit()
    return res.rowcount


# ── MCP 응답 생성 (카테고리별 독립 파일 블록) ──────────────────────────────

_FILE_SEP = "=" * 60


def _skill_file_block(save_path: str, section_display: str, body: str) -> str:
    return (
        f"{_FILE_SEP}\n"
        f"SKILL FILE: {save_path}\n"
        f"{_FILE_SEP}\n"
        f"{body}\n"
        f"{_FILE_SEP}\n"
        f"END SKILL FILE: {save_path}\n"
        f"{_FILE_SEP}\n"
    )


_AGENT_SKILL_SAVE_INSTRUCTIONS = """
---
[CRITICAL — 에이전트 필수 작업]

위 SKILL FILE 블록들을 각각 독립 파일로 저장하세요.
저장 경로는 각 블록 헤더의 "SKILL FILE: {경로}" 를 따르세요.

저장 규칙:
- 파일이 이미 존재하면 덮어쓰기
- 디렉터리가 없으면 생성
- 저장 후 커서에서 .cursor/skills/ 폴더가 Agent Context로 로드됩니다

Skills = 스킬 (시스템 구조, 환경, 아키텍처 등)
Rules  = 행동 지침 (반드시 따를 규칙) ← get_global_rule 로 별도 관리
"""


def get_skills_markdown(
    session: Session,
    app_name: str | None = None,
    origin_url: str | None = None,
) -> str:
    """MCP 응답: 카테고리별 독립 파일 블록으로 반환."""
    blocks: list[str] = []

    # 1. Global skills
    global_rows = _global_skill_all_sections_latest(session)
    for row in global_rows:
        path = _global_skill_save_path(row.section_name)
        display = "기본" if row.section_name == DEFAULT_SECTION else row.section_name
        blocks.append(_skill_file_block(path, display, row.body))

    # 2. Repo skills (origin_url 패턴 매칭)
    if origin_url:
        all_patterns = list_distinct_repo_patterns_with_skills(session)
        matched_patterns = [p for p in all_patterns if p and p in origin_url]
        # 빈 패턴(default) 항상 포함
        if "" in all_patterns:
            matched_patterns = [""] + matched_patterns

        for pattern in matched_patterns:
            repo_rows = _repo_skill_all_sections_latest(session, pattern)
            for row in repo_rows:
                path = _repo_skill_save_path(pattern, row.section_name)
                display = "기본" if row.section_name == DEFAULT_SECTION else row.section_name
                blocks.append(_skill_file_block(path, display, row.body))

    # 3. App skills
    if app_name:
        key = (app_name or "").lower().strip()
        app_rows = _app_skill_all_sections_latest(session, key)
        for row in app_rows:
            path = _app_skill_save_path(key, row.section_name)
            display = "기본" if row.section_name == DEFAULT_SECTION else row.section_name
            blocks.append(_skill_file_block(path, display, row.body))

    if not blocks:
        return "# Skills\n\n등록된 스킬(Skills)이 없습니다. 어드민 > 스킬 메뉴에서 추가하세요."

    header = f"# Skills (스킬)\n\n총 {len(blocks)}개 카테고리\n\n"
    return header + "\n".join(blocks) + _AGENT_SKILL_SAVE_INSTRUCTIONS
