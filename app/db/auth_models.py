"""User / ApiKey ORM 모델 — MCPER_AUTH_ENABLED=true 시 사용."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.database import Base


class User(Base):
    __tablename__ = "mcper_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(256), unique=True, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # OAuth 전용 유저는 hashed_password=None
    oauth_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    oauth_sub: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ApiKey(Base):
    """MCP 클라이언트가 Bearer 토큰으로 사용하는 API 키."""

    __tablename__ = "mcper_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mcper_users.id", ondelete="CASCADE")
    )
    key_hash: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)  # 예: "Cursor laptop"
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
