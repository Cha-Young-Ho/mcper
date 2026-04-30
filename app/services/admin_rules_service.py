"""Admin rules 라우터 전용 서비스 계층.

라우터가 SQLAlchemy `select()` / `delete()` / `func.count()` 를 직접
호출하지 않고 이 모듈을 거치도록 분리한다. 라우터는 HTTP 파싱·템플릿
렌더링에만 집중하고, 비즈니스 로직은 여기에서 한 번에 표현한다.

새 함수 추가 시 반환값은 라우터가 즉시 사용 가능한 형태(행·카운트·튜플)로
통일한다. 라우터에서 `raise HTTPException` 은 유지한다 (HTTP 응답과 맞물려야
하므로). 서비스는 ValueError 등으로 신호만 주거나, 단순 카운트를 돌려준다.
"""

from __future__ import annotations

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from app.db.rule_models import (
    AppRuleVersion,
    GlobalRuleVersion,
    McpAppPullOption,
    RepoRuleVersion,
)


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
    "list_repo_category_versions",
    "repo_pattern_exists",
]
