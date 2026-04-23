"""ORM models: versioned global + repository + per-app WORKFLOWS (워크플로우 / 오케스트레이터).

Workflows는 Rules, Skills와 별개의 개념:
- Rules     = 행동 지침 (반드시 따라야 할 것)
- Skills    = 스킬 / 시스템 이해 (문맥 정보, 독립적으로 공유 가능)
- Workflows = 오케스트레이터 (작업별 에이전트 팀 구성, 실행 순서, 기본 스킬)

구조는 skill_models.py와 동일:
- section_name 으로 카테고리 분리 (기본: "main")
- 버전은 (entity, section_name) 단위로 독립 증가 (append-only)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

_DEFAULT_SECTION = "main"


class GlobalWorkflowVersion(Base):
    """글로벌 워크플로우; section_name 별로 독립 버전 스트림."""

    __tablename__ = "global_workflow_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default=_DEFAULT_SECTION, server_default=_DEFAULT_SECTION, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("section_name", "version", name="uq_global_workflow_versions_section_version"),
    )


class AppWorkflowVersion(Base):
    """앱별 워크플로우; (app_name, section_name) 단위로 독립 버전 스트림."""

    __tablename__ = "app_workflow_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    section_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default=_DEFAULT_SECTION, server_default=_DEFAULT_SECTION, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "app_name", "section_name", "version",
            name="uq_app_workflow_versions_app_section_version",
        ),
    )


class RepoWorkflowVersion(Base):
    """Git remote URL 부분문자열 매칭; (pattern, section_name) 단위 버전 스트림."""

    __tablename__ = "repo_workflow_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern: Mapped[str] = mapped_column(String(256), nullable=False, default="", index=True)
    section_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default=_DEFAULT_SECTION, server_default=_DEFAULT_SECTION, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "pattern", "section_name", "version",
            name="uq_repo_workflow_versions_pattern_section_version",
        ),
    )
