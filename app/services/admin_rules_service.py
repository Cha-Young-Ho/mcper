"""Admin rules 라우터 전용 서비스 계층.

라우터가 SQLAlchemy `select()` / `delete()` / `func.count()` 를 직접
호출하지 않고 이 모듈을 거치도록 분리한다. 라우터는 HTTP 파싱·템플릿
렌더링에만 집중하고, 비즈니스 로직은 여기에서 한 번에 표현한다.

새 함수 추가 시 반환값은 라우터가 즉시 사용 가능한 형태(행·카운트·튜플)로
통일한다. 라우터에서 `raise HTTPException` 은 유지한다 (HTTP 응답과 맞물려야
하므로). 서비스는 ValueError 등으로 신호만 주거나, 단순 카운트를 돌려준다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from app.db.rule_models import (
    AppRuleVersion,
    GlobalRuleVersion,
    McpAppPullOption,
    RepoRuleVersion,
)


# 카드 미리보기용 경량 레코드 — 카드 UI 에서 필요한 최소 필드만. 본문(body)
# TEXT 전체 로드를 피하기 위해 SQL SUBSTRING 으로 잘라 가져온다.
_PREVIEW_CHARS = 200
_PREVIEW_FETCH = _PREVIEW_CHARS + 1  # 잘림 여부 판정용 +1


@dataclass(frozen=True)
class SectionPreview:
    section_name: str
    version: int
    preview: str
    created_at: datetime


# ──────────────────────────────────────────────────────────────────────
# Global rules
# ──────────────────────────────────────────────────────────────────────


def list_global_category_versions(
    db: Session, section_name: str
) -> list[GlobalRuleVersion]:
    """해당 섹션의 전체 버전 행을 최신순으로 반환."""
    return list(
        db.scalars(
            select(GlobalRuleVersion)
            .where(GlobalRuleVersion.section_name == section_name)
            .order_by(GlobalRuleVersion.version.desc())
        ).all()
    )


def delete_global_category(db: Session, section_name: str) -> int:
    """섹션 전체 삭제. 삭제된 행 수 반환."""
    res = db.execute(
        delete(GlobalRuleVersion).where(GlobalRuleVersion.section_name == section_name)
    )
    db.commit()
    return int(res.rowcount or 0)


def get_global_category_version(
    db: Session, section_name: str, version: int
) -> tuple[GlobalRuleVersion | None, int]:
    """특정 (섹션, 버전) 행과 섹션 내 총 버전 수 반환."""
    row = db.scalars(
        select(GlobalRuleVersion).where(
            GlobalRuleVersion.section_name == section_name,
            GlobalRuleVersion.version == version,
        )
    ).first()
    n = int(
        db.scalar(
            select(func.count()).where(GlobalRuleVersion.section_name == section_name)
        )
        or 0
    )
    return row, n


def delete_global_category_version(
    db: Session, section_name: str, version: int
) -> tuple[int, int]:
    """(삭제된 행 수, 삭제 후 섹션 내 남은 버전 수) 반환."""
    res = db.execute(
        delete(GlobalRuleVersion).where(
            and_(
                GlobalRuleVersion.section_name == section_name,
                GlobalRuleVersion.version == version,
            )
        )
    )
    db.commit()
    n_after = int(
        db.scalar(
            select(func.count()).where(GlobalRuleVersion.section_name == section_name)
        )
        or 0
    )
    return int(res.rowcount or 0), n_after


def count_global_category(db: Session, section_name: str) -> int:
    return int(
        db.scalar(
            select(func.count()).where(GlobalRuleVersion.section_name == section_name)
        )
        or 0
    )


# ──────────────────────────────────────────────────────────────────────
# App rules
# ──────────────────────────────────────────────────────────────────────


def app_exists(db: Session, app_name: str) -> bool:
    return (
        db.scalars(
            select(AppRuleVersion).where(AppRuleVersion.app_name == app_name).limit(1)
        ).first()
        is not None
    )


def delete_app_stream(db: Session, app_name: str) -> int:
    """app_name 의 모든 app_rule_versions 행 + 짝을 이루는 pull-option 행 삭제.

    삭제된 rule 버전 수(rowcount) 만 반환 — pull option 수는 서비스 내부 정리용.
    """
    res = db.execute(delete(AppRuleVersion).where(AppRuleVersion.app_name == app_name))
    db.execute(delete(McpAppPullOption).where(McpAppPullOption.app_name == app_name))
    db.commit()
    return int(res.rowcount or 0)


def list_app_section_versions(
    db: Session, app_name: str, section_name: str
) -> list[AppRuleVersion]:
    return list(
        db.scalars(
            select(AppRuleVersion)
            .where(
                AppRuleVersion.app_name == app_name,
                AppRuleVersion.section_name == section_name,
            )
            .order_by(AppRuleVersion.version.desc())
        ).all()
    )


def delete_app_section(db: Session, app_name: str, section_name: str) -> int:
    res = db.execute(
        delete(AppRuleVersion).where(
            and_(
                AppRuleVersion.app_name == app_name,
                AppRuleVersion.section_name == section_name,
            )
        )
    )
    db.commit()
    return int(res.rowcount or 0)


def get_app_section_version(
    db: Session, app_name: str, section_name: str, version: int
) -> tuple[AppRuleVersion | None, int]:
    row = db.scalars(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == app_name,
            AppRuleVersion.section_name == section_name,
            AppRuleVersion.version == version,
        )
    ).first()
    n = int(
        db.scalar(
            select(func.count()).where(
                AppRuleVersion.app_name == app_name,
                AppRuleVersion.section_name == section_name,
            )
        )
        or 0
    )
    return row, n


def delete_app_section_version(
    db: Session, app_name: str, section_name: str, version: int
) -> tuple[int, int]:
    res = db.execute(
        delete(AppRuleVersion).where(
            and_(
                AppRuleVersion.app_name == app_name,
                AppRuleVersion.section_name == section_name,
                AppRuleVersion.version == version,
            )
        )
    )
    db.commit()
    n_after = int(
        db.scalar(
            select(func.count()).where(
                AppRuleVersion.app_name == app_name,
                AppRuleVersion.section_name == section_name,
            )
        )
        or 0
    )
    return int(res.rowcount or 0), n_after


# ──────────────────────────────────────────────────────────────────────
# Repository rules
# ──────────────────────────────────────────────────────────────────────


def repo_pattern_exists(db: Session, pattern: str) -> bool:
    return (
        db.scalars(
            select(RepoRuleVersion).where(RepoRuleVersion.pattern == pattern).limit(1)
        ).first()
        is not None
    )


def delete_repo_stream(db: Session, pattern: str) -> int:
    res = db.execute(delete(RepoRuleVersion).where(RepoRuleVersion.pattern == pattern))
    db.commit()
    return int(res.rowcount or 0)


def list_repo_category_versions(
    db: Session, pattern: str, section_name: str
) -> list[RepoRuleVersion]:
    return list(
        db.scalars(
            select(RepoRuleVersion)
            .where(
                RepoRuleVersion.pattern == pattern,
                RepoRuleVersion.section_name == section_name,
            )
            .order_by(RepoRuleVersion.version.desc())
        ).all()
    )


def delete_repo_category(db: Session, pattern: str, section_name: str) -> int:
    res = db.execute(
        delete(RepoRuleVersion).where(
            and_(
                RepoRuleVersion.pattern == pattern,
                RepoRuleVersion.section_name == section_name,
            )
        )
    )
    db.commit()
    return int(res.rowcount or 0)


def get_repo_category_version(
    db: Session, pattern: str, section_name: str, version: int
) -> tuple[RepoRuleVersion | None, int]:
    row = db.scalars(
        select(RepoRuleVersion).where(
            RepoRuleVersion.pattern == pattern,
            RepoRuleVersion.section_name == section_name,
            RepoRuleVersion.version == version,
        )
    ).first()
    n = int(
        db.scalar(
            select(func.count()).where(
                RepoRuleVersion.pattern == pattern,
                RepoRuleVersion.section_name == section_name,
            )
        )
        or 0
    )
    return row, n


def delete_repo_category_version(
    db: Session, pattern: str, section_name: str, version: int
) -> tuple[int, int]:
    res = db.execute(
        delete(RepoRuleVersion).where(
            and_(
                RepoRuleVersion.pattern == pattern,
                RepoRuleVersion.section_name == section_name,
                RepoRuleVersion.version == version,
            )
        )
    )
    db.commit()
    n_after = int(
        db.scalar(
            select(func.count()).where(
                RepoRuleVersion.pattern == pattern,
                RepoRuleVersion.section_name == section_name,
            )
        )
        or 0
    )
    return int(res.rowcount or 0), n_after


# ──────────────────────────────────────────────────────────────────────
# 카드 미리보기 전용 경량 조회 (P11: body 전체 로드 회피)
# ──────────────────────────────────────────────────────────────────────


def _preview_string(head: str) -> str:
    """SQL SUBSTRING 결과를 preview 문자열로 가공 — `_PREVIEW_CHARS` 초과분은 `…` 로 표시."""
    if head is None:
        return ""
    if len(head) > _PREVIEW_CHARS:
        return head[:_PREVIEW_CHARS] + "…"
    return head


def list_global_section_previews(
    db: Session, *, domain: str | None = None
) -> list[SectionPreview]:
    """모든 섹션의 최신 global 룰을 카드용 필드만 추려 가져온다."""
    base = select(
        GlobalRuleVersion.section_name.label("sn"),
        func.max(GlobalRuleVersion.version).label("mv"),
    )
    if domain is not None:
        base = base.where(GlobalRuleVersion.domain == domain)
    subq = base.group_by(GlobalRuleVersion.section_name).subquery()

    body_head = func.substring(GlobalRuleVersion.body, 1, _PREVIEW_FETCH)
    q = select(
        GlobalRuleVersion.section_name,
        GlobalRuleVersion.version,
        body_head.label("body_head"),
        GlobalRuleVersion.created_at,
    ).join(
        subq,
        (GlobalRuleVersion.section_name == subq.c.sn)
        & (GlobalRuleVersion.version == subq.c.mv),
    )
    if domain is not None:
        q = q.where(GlobalRuleVersion.domain == domain)

    rows = db.execute(q).all()
    out = [
        SectionPreview(
            section_name=sn,
            version=v,
            preview=_preview_string(head),
            created_at=ca,
        )
        for sn, v, head, ca in rows
    ]
    out.sort(key=lambda r: "" if r.section_name == "main" else r.section_name)
    return out


def list_app_section_previews(db: Session, app_name: str) -> list[SectionPreview]:
    """앱 규칙 섹션 보드 카드용 경량 조회."""
    base = (
        select(
            AppRuleVersion.section_name.label("sn"),
            func.max(AppRuleVersion.version).label("mv"),
        )
        .where(AppRuleVersion.app_name == app_name)
        .group_by(AppRuleVersion.section_name)
    ).subquery()

    body_head = func.substring(AppRuleVersion.body, 1, _PREVIEW_FETCH)
    q = select(
        AppRuleVersion.section_name,
        AppRuleVersion.version,
        body_head.label("body_head"),
        AppRuleVersion.created_at,
    ).join(
        base,
        (AppRuleVersion.app_name == app_name)
        & (AppRuleVersion.section_name == base.c.sn)
        & (AppRuleVersion.version == base.c.mv),
    )
    rows = db.execute(q).all()
    out = [
        SectionPreview(
            section_name=sn,
            version=v,
            preview=_preview_string(head),
            created_at=ca,
        )
        for sn, v, head, ca in rows
    ]
    out.sort(key=lambda r: "" if r.section_name == "main" else r.section_name)
    return out


def list_repo_section_previews(db: Session, pattern: str) -> list[SectionPreview]:
    """레포 규칙 패턴별 카드용 경량 조회."""
    base = (
        select(
            RepoRuleVersion.section_name.label("sn"),
            func.max(RepoRuleVersion.version).label("mv"),
        )
        .where(RepoRuleVersion.pattern == pattern)
        .group_by(RepoRuleVersion.section_name)
    ).subquery()

    body_head = func.substring(RepoRuleVersion.body, 1, _PREVIEW_FETCH)
    q = select(
        RepoRuleVersion.section_name,
        RepoRuleVersion.version,
        body_head.label("body_head"),
        RepoRuleVersion.created_at,
    ).join(
        base,
        (RepoRuleVersion.pattern == pattern)
        & (RepoRuleVersion.section_name == base.c.sn)
        & (RepoRuleVersion.version == base.c.mv),
    )
    rows = db.execute(q).all()
    out = [
        SectionPreview(
            section_name=sn,
            version=v,
            preview=_preview_string(head),
            created_at=ca,
        )
        for sn, v, head, ca in rows
    ]
    out.sort(key=lambda r: "" if r.section_name == "main" else r.section_name)
    return out


# ──────────────────────────────────────────────────────────────────────
# 공통 — diff / rollback / export / import 에서 사용
# ──────────────────────────────────────────────────────────────────────


def get_global_version_row(db: Session, version: int) -> GlobalRuleVersion | None:
    return db.scalars(
        select(GlobalRuleVersion).where(GlobalRuleVersion.version == version)
    ).first()


__all__ = [
    "app_exists",
    "count_global_category",
    "delete_app_section_version",
    "delete_app_section",
    "delete_app_stream",
    "delete_global_category_version",
    "delete_global_category",
    "delete_repo_category_version",
    "delete_repo_category",
    "delete_repo_stream",
    "get_app_section_version",
    "get_global_category_version",
    "get_global_version_row",
    "get_repo_category_version",
    "list_app_section_versions",
    "list_global_category_versions",
    "list_app_section_previews",
    "list_global_section_previews",
    "list_repo_category_versions",
    "list_repo_section_previews",
    "repo_pattern_exists",
    "SectionPreview",
]
