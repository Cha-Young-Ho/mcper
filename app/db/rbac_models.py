"""ORM models: Domain-based RBAC — domains, user permissions, content restrictions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.database import Base


class Domain(Base):
    """도메인 (기획 / 개발 / 분석)."""

    __tablename__ = "mcper_domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserPermission(Base):
    """유저별 도메인+앱 권한.

    domain_slug=NULL → 모든 도메인에 적용.
    app_name=NULL    → 해당 도메인의 모든 앱에 적용.
    role: 'admin' | 'editor' | 'viewer'.
    """

    __tablename__ = "mcper_user_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mcper_users.id", ondelete="CASCADE"), nullable=False
    )
    domain_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    app_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="viewer"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "domain_slug", "app_name",
            name="uq_user_perm_user_domain_app",
        ),
    )


class ContentRestriction(Base):
    """특정 섹션을 특정 역할 이하에게 차단.

    restricted_role='viewer' → viewer 역할 유저는 해당 section_name 조회 불가.
    restricted_role='editor' → editor 이하 조회 불가 (admin만 조회 가능).
    """

    __tablename__ = "mcper_content_restrictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    app_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    section_name: Mapped[str] = mapped_column(String(128), nullable=False)
    restricted_role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="viewer"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "domain_slug", "app_name", "section_name", "restricted_role",
            name="uq_content_restriction",
        ),
    )
