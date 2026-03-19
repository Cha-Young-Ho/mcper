"""Database engine, session factory, and schema initialization."""

from __future__ import annotations

import os
import time
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base

import app.db.rule_models  # noqa: F401 — register rule_* tables on Base.metadata
import app.db.mcp_tool_stats  # noqa: F401 — mcp_tool_call_stats

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/mcpdb",
)

engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


def _apply_lightweight_migrations(connection) -> None:
    """
    Alembic 없이 기존 Postgres에만 필요한 additive 변경.
    create_all 은 이미 있는 테이블에 컬럼을 안 붙이므로, 예전 specs 행만 있던 DB용.
    """
    connection.execute(
        text(
            "ALTER TABLE specs ADD COLUMN IF NOT EXISTS title VARCHAR(512)"
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS mcp_rule_return_options (
                id INTEGER PRIMARY KEY,
                include_app_default BOOLEAN NOT NULL DEFAULT false,
                include_repo_default BOOLEAN NOT NULL DEFAULT false
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO mcp_rule_return_options (id, include_app_default, include_repo_default)
            SELECT 1, false, false
            WHERE NOT EXISTS (SELECT 1 FROM mcp_rule_return_options WHERE id = 1)
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS mcp_app_pull_options (
                app_name VARCHAR(128) PRIMARY KEY,
                include_app_default BOOLEAN NOT NULL DEFAULT false
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO mcp_app_pull_options (app_name, include_app_default)
            SELECT DISTINCT arv.app_name, COALESCE(mro.include_app_default, false)
            FROM app_rule_versions arv
            LEFT JOIN mcp_rule_return_options mro ON mro.id = 1
            ON CONFLICT (app_name) DO NOTHING
            """
        )
    )


def init_db(
    *,
    max_attempts: int = 30,
    delay_sec: float = 1.0,
) -> None:
    """
    Create tables if they do not exist (idempotent).

    Retries on connection errors (e.g. Postgres still booting in Docker).
    """
    for attempt in range(1, max_attempts + 1):
        try:
            Base.metadata.create_all(bind=engine)
            with engine.begin() as conn:
                # 예전 볼륨: specs 는 있는데 title 컬럼 없음 → 시드 INSERT 실패 방지 (Postgres)
                _apply_lightweight_migrations(conn)
            return
        except OperationalError as exc:
            if attempt == max_attempts:
                raise exc
            time.sleep(delay_sec)


def get_db() -> Generator[Session, None, None]:
    """FastAPI-style dependency generator for request-scoped sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> bool:
    """Return True if a simple query succeeds."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
