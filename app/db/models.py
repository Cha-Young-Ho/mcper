"""SQLAlchemy models for the specs store."""

from __future__ import annotations

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Spec(Base):
    """Planning document row stored for MCP tools."""

    __tablename__ = "specs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    app_target: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    base_branch: Mapped[str] = mapped_column(String(512), nullable=False)
    related_files: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
