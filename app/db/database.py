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
import app.db.rag_models  # noqa: F401 — spec_chunks, code_nodes, code_edges
import app.db.mcp_security  # noqa: F401 — mcp_allowed_hosts


def _resolve_database_url() -> str:
    try:
        from app.config import settings as app_settings

        if app_settings.database.url:
            return str(app_settings.database.url)
    except Exception:
        pass
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://user:password@localhost:5432/mcpdb",
    )


DATABASE_URL = _resolve_database_url()

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
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS mcp_repo_pattern_pull_options (
                pattern VARCHAR(256) PRIMARY KEY,
                include_repo_default BOOLEAN NOT NULL DEFAULT false
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO mcp_repo_pattern_pull_options (pattern, include_repo_default)
            SELECT DISTINCT r.pattern,
                COALESCE((SELECT include_repo_default FROM mcp_rule_return_options WHERE id = 1), false)
            FROM repo_rule_versions r
            WHERE NOT EXISTS (
                SELECT 1 FROM mcp_repo_pattern_pull_options o
                WHERE o.pattern = r.pattern
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS mcp_allowed_hosts (
                id SERIAL PRIMARY KEY,
                host_entry VARCHAR(255) NOT NULL UNIQUE,
                note VARCHAR(512),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )


def _apply_rag_indexes(connection) -> None:
    """FTS generated columns + GIN + HNSW for RAG tables (idempotent)."""
    connection.execute(
        text(
            """
            DO $$
            BEGIN
              IF to_regclass('public.spec_chunks') IS NOT NULL THEN
                IF NOT EXISTS (
                  SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'public' AND table_name = 'spec_chunks'
                    AND column_name = 'content_tsv'
                ) THEN
                  ALTER TABLE spec_chunks ADD COLUMN content_tsv tsvector
                    GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED;
                END IF;
              END IF;
            END $$;
            """
        )
    )
    connection.execute(
        text(
            """
            DO $$
            BEGIN
              IF to_regclass('public.spec_chunks') IS NOT NULL THEN
                EXECUTE $idx$
                  CREATE INDEX IF NOT EXISTS spec_chunks_content_tsv_idx
                  ON spec_chunks USING GIN (content_tsv);
                $idx$;
                EXECUTE $idx$
                  CREATE INDEX IF NOT EXISTS spec_chunks_embedding_hnsw_idx
                  ON spec_chunks USING hnsw (embedding vector_cosine_ops)
                  WITH (m = 16, ef_construction = 64);
                $idx$;
              END IF;
            END $$;
            """
        )
    )
    connection.execute(
        text(
            """
            DO $$
            BEGIN
              IF to_regclass('public.code_nodes') IS NOT NULL THEN
                IF NOT EXISTS (
                  SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'public' AND table_name = 'code_nodes'
                    AND column_name = 'content_tsv'
                ) THEN
                  ALTER TABLE code_nodes ADD COLUMN content_tsv tsvector
                    GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED;
                END IF;
              END IF;
            END $$;
            """
        )
    )
    connection.execute(
        text(
            """
            DO $$
            BEGIN
              IF to_regclass('public.code_nodes') IS NOT NULL THEN
                EXECUTE $idx$
                  CREATE INDEX IF NOT EXISTS code_nodes_content_tsv_idx
                  ON code_nodes USING GIN (content_tsv);
                $idx$;
                EXECUTE $idx$
                  CREATE INDEX IF NOT EXISTS code_nodes_embedding_hnsw_idx
                  ON code_nodes USING hnsw (embedding vector_cosine_ops)
                  WITH (m = 16, ef_construction = 64);
                $idx$;
              END IF;
            END $$;
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
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            Base.metadata.create_all(bind=engine)
            with engine.begin() as conn:
                # 예전 볼륨: specs 는 있는데 title 컬럼 없음 → 시드 INSERT 실패 방지 (Postgres)
                _apply_lightweight_migrations(conn)
                _apply_rag_indexes(conn)
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
