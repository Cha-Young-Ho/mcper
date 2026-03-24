"""ORM models: versioned global + repository + per-app rules (immutable versions)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class GlobalRuleVersion(Base):
    """Single stream of global defaults; monotonically increasing version."""

    __tablename__ = "global_rule_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class AppRuleVersion(Base):
    """Per-app rule stream; each app has its own version sequence (1, 2, 3…)."""

    __tablename__ = "app_rule_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("app_name", "version", name="uq_app_rule_versions_app_version"),
    )


class RepoRuleVersion(Base):
    """Git remote URL 부분문자열 매칭 + 빈 pattern 폴백. pattern 별로 버전 스트림."""

    __tablename__ = "repo_rule_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern: Mapped[str] = mapped_column(String(256), nullable=False, default="", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("pattern", "version", name="uq_repo_rule_versions_pattern_version"),
    )


class McpRuleReturnOptions(Base):
    """
    MCP `get_global_rule` 이 **repository** `default`(빈 패턴) 스트림을 추가로 붙일지 (행 1건, id=1).
    어드민 Repository rules 카드 화면에서 토글.
    앱 쪽 `__default__` 스트림 병합 여부는 `McpAppPullOption` (앱별).
    """

    __tablename__ = "mcp_rule_return_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    include_app_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    include_repo_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )


class McpRepoPatternPullOption(Base):
    """
    Repository 패턴(카드)마다 MCP 응답에 빈 패턴(default) repo 스트림을 추가로 붙일지.
    `pattern` 은 `repo_rule_versions.pattern` 과 동일(빈 문자열 = default 스트림).
    """

    __tablename__ = "mcp_repo_pattern_pull_options"

    pattern: Mapped[str] = mapped_column(String(256), primary_key=True)
    include_repo_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )


class McpAppPullOption(Base):
    """
    `get_global_rule` / `check_rule_versions` 에서 **요청한 app_name** 기준으로
    `__default__` 앱 스트림을 추가로 붙일지 (앱마다 1행).
    """

    __tablename__ = "mcp_app_pull_options"

    app_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    include_app_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
