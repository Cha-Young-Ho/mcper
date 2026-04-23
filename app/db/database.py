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
import app.db.skill_models  # noqa: F401 — register skill_* tables on Base.metadata
import app.db.mcp_tool_stats  # noqa: F401 — mcp_tool_call_stats
import app.db.rag_models  # noqa: F401 — spec_chunks, code_nodes, code_edges
import app.db.mcp_security  # noqa: F401 — mcp_allowed_hosts
import app.db.auth_models  # noqa: F401 — mcper_users, mcper_api_keys
import app.db.rbac_models  # noqa: F401 — mcper_domains, mcper_user_permissions, mcper_content_restrictions
import app.db.celery_models  # noqa: F401 — failed_tasks, celery_task_stats
import app.db.workflow_models  # noqa: F401 — register workflow_* tables on Base.metadata


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
    # User 테이블에 password_changed_at 컬럼 추가 (없을 경우)
    connection.execute(
        text(
            "ALTER TABLE mcper_users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP WITH TIME ZONE NULL"
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
    # code_edges 중복 방지 unique constraint (기존 테이블에 추가)
    connection.execute(
        text(
            """
            DO $$
            BEGIN
              IF to_regclass('public.code_edges') IS NOT NULL THEN
                IF NOT EXISTS (
                  SELECT 1 FROM pg_constraint
                  WHERE conname = 'uq_code_edges_app_src_tgt_rel'
                ) THEN
                  ALTER TABLE code_edges
                    ADD CONSTRAINT uq_code_edges_app_src_tgt_rel
                    UNIQUE (app_target, source_id, target_id, relation);
                END IF;
              END IF;
            END $$;
            """
        )
    )
    # ── section_name 컬럼 + 고유 제약 마이그레이션 ────────────────────
    # 기존 행이 있는 DB에서 section_name='main' 기본값으로 컬럼 추가.
    # 구 unique constraint를 삭제하고 section_name 포함 복합 unique를 추가.
    connection.execute(
        text(
            """
            ALTER TABLE global_rule_versions
                ADD COLUMN IF NOT EXISTS section_name VARCHAR(128) NOT NULL DEFAULT 'main';
            ALTER TABLE app_rule_versions
                ADD COLUMN IF NOT EXISTS section_name VARCHAR(128) NOT NULL DEFAULT 'main';
            ALTER TABLE repo_rule_versions
                ADD COLUMN IF NOT EXISTS section_name VARCHAR(128) NOT NULL DEFAULT 'main';
            """
        )
    )
    connection.execute(
        text(
            """
            DO $$
            BEGIN
              -- global_rule_versions: 구 unique(version) → unique(section_name, version)
              IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'global_rule_versions_version_key'
              ) THEN
                ALTER TABLE global_rule_versions DROP CONSTRAINT global_rule_versions_version_key;
              END IF;
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_global_rule_versions_section_version'
              ) THEN
                ALTER TABLE global_rule_versions
                  ADD CONSTRAINT uq_global_rule_versions_section_version
                  UNIQUE (section_name, version);
              END IF;

              -- app_rule_versions: 구 unique(app_name, version) → unique(app_name, section_name, version)
              IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_app_rule_versions_app_version'
              ) THEN
                ALTER TABLE app_rule_versions DROP CONSTRAINT uq_app_rule_versions_app_version;
              END IF;
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_app_rule_versions_app_section_version'
              ) THEN
                ALTER TABLE app_rule_versions
                  ADD CONSTRAINT uq_app_rule_versions_app_section_version
                  UNIQUE (app_name, section_name, version);
              END IF;

              -- repo_rule_versions: 구 unique(pattern, version) → unique(pattern, section_name, version)
              IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_repo_rule_versions_pattern_version'
              ) THEN
                ALTER TABLE repo_rule_versions DROP CONSTRAINT uq_repo_rule_versions_pattern_version;
              END IF;
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_repo_rule_versions_pattern_section_version'
              ) THEN
                ALTER TABLE repo_rule_versions
                  ADD CONSTRAINT uq_repo_rule_versions_pattern_section_version
                  UNIQUE (pattern, section_name, version);
              END IF;
            END $$;
            """
        )
    )


    # ── Skills 테이블 생성 (Rules와 완전 별개) ─────────────────────────
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS global_skill_versions (
                id SERIAL PRIMARY KEY,
                section_name VARCHAR(128) NOT NULL DEFAULT 'main',
                version INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_global_skill_versions_section_version UNIQUE (section_name, version)
            );
            CREATE TABLE IF NOT EXISTS app_skill_versions (
                id SERIAL PRIMARY KEY,
                app_name VARCHAR(128) NOT NULL,
                section_name VARCHAR(128) NOT NULL DEFAULT 'main',
                version INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_app_skill_versions_app_section_version UNIQUE (app_name, section_name, version)
            );
            CREATE INDEX IF NOT EXISTS ix_app_skill_versions_app_name ON app_skill_versions (app_name);
            CREATE INDEX IF NOT EXISTS ix_app_skill_versions_section_name ON app_skill_versions (section_name);
            CREATE TABLE IF NOT EXISTS repo_skill_versions (
                id SERIAL PRIMARY KEY,
                pattern VARCHAR(256) NOT NULL DEFAULT '',
                section_name VARCHAR(128) NOT NULL DEFAULT 'main',
                sort_order INTEGER NOT NULL DEFAULT 100,
                version INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_repo_skill_versions_pattern_section_version UNIQUE (pattern, section_name, version)
            );
            CREATE INDEX IF NOT EXISTS ix_repo_skill_versions_pattern ON repo_skill_versions (pattern);
            CREATE INDEX IF NOT EXISTS ix_repo_skill_versions_section_name ON repo_skill_versions (section_name);
            CREATE INDEX IF NOT EXISTS ix_global_skill_versions_section_name ON global_skill_versions (section_name);
            """
        )
    )

    # ── domain 컬럼 추가 (skill + rule 모든 테이블) ──────────────────────
    connection.execute(
        text(
            """
            ALTER TABLE global_skill_versions ADD COLUMN IF NOT EXISTS domain VARCHAR(64) NULL;
            ALTER TABLE app_skill_versions ADD COLUMN IF NOT EXISTS domain VARCHAR(64) NULL;
            ALTER TABLE repo_skill_versions ADD COLUMN IF NOT EXISTS domain VARCHAR(64) NULL;
            ALTER TABLE global_rule_versions ADD COLUMN IF NOT EXISTS domain VARCHAR(64) NULL;
            ALTER TABLE app_rule_versions ADD COLUMN IF NOT EXISTS domain VARCHAR(64) NULL;
            ALTER TABLE repo_rule_versions ADD COLUMN IF NOT EXISTS domain VARCHAR(64) NULL;
            CREATE INDEX IF NOT EXISTS ix_global_skill_versions_domain ON global_skill_versions (domain);
            CREATE INDEX IF NOT EXISTS ix_app_skill_versions_domain ON app_skill_versions (domain);
            CREATE INDEX IF NOT EXISTS ix_repo_skill_versions_domain ON repo_skill_versions (domain);
            CREATE INDEX IF NOT EXISTS ix_global_rule_versions_domain ON global_rule_versions (domain);
            CREATE INDEX IF NOT EXISTS ix_app_rule_versions_domain ON app_rule_versions (domain);
            CREATE INDEX IF NOT EXISTS ix_repo_rule_versions_domain ON repo_rule_versions (domain);
            """
        )
    )

    # ── RBAC 테이블 (도메인, 권한, 콘텐츠 제한) ─────────────────────────
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS mcper_domains (
                id SERIAL PRIMARY KEY,
                slug VARCHAR(64) NOT NULL UNIQUE,
                display_name VARCHAR(128) NOT NULL,
                description TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            INSERT INTO mcper_domains (slug, display_name, description)
            VALUES
                ('planning', '기획', '기획 도메인 — 기획서, 요구사항, 유저스토리'),
                ('development', '개발', '개발 도메인 — 코드 규칙, 아키텍처, 패턴'),
                ('analysis', '분석', '분석 도메인 — 데이터 분석, 리포트, 메트릭')
            ON CONFLICT (slug) DO NOTHING;

            CREATE TABLE IF NOT EXISTS mcper_user_permissions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES mcper_users(id) ON DELETE CASCADE,
                domain_slug VARCHAR(64),
                app_name VARCHAR(128),
                role VARCHAR(16) NOT NULL DEFAULT 'viewer',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_user_perm_user_domain_app UNIQUE (user_id, domain_slug, app_name)
            );
            CREATE INDEX IF NOT EXISTS ix_user_perm_user ON mcper_user_permissions (user_id);
            CREATE INDEX IF NOT EXISTS ix_user_perm_domain ON mcper_user_permissions (domain_slug);

            CREATE TABLE IF NOT EXISTS mcper_content_restrictions (
                id SERIAL PRIMARY KEY,
                domain_slug VARCHAR(64),
                app_name VARCHAR(128),
                section_name VARCHAR(128) NOT NULL,
                restricted_role VARCHAR(16) NOT NULL DEFAULT 'viewer',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_content_restriction UNIQUE (domain_slug, app_name, section_name, restricted_role)
            );
            """
        )
    )

    # ── skill_chunks 테이블 (스킬 벡터 검색용) ──────────────────────────
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS skill_chunks (
                id SERIAL PRIMARY KEY,
                skill_type VARCHAR(16) NOT NULL,
                skill_entity_id INTEGER NOT NULL,
                app_name VARCHAR(128),
                domain VARCHAR(64),
                section_name VARCHAR(128) NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding vector(384),
                metadata JSONB NOT NULL DEFAULT '{}',
                chunk_type VARCHAR(16) NOT NULL DEFAULT 'child',
                parent_chunk_id INTEGER REFERENCES skill_chunks(id) ON DELETE SET NULL,
                CONSTRAINT uq_skill_chunks_type_entity_idx UNIQUE (skill_type, skill_entity_id, chunk_index)
            );
            CREATE INDEX IF NOT EXISTS ix_skill_chunks_skill_type ON skill_chunks (skill_type);
            CREATE INDEX IF NOT EXISTS ix_skill_chunks_entity_id ON skill_chunks (skill_entity_id);
            CREATE INDEX IF NOT EXISTS ix_skill_chunks_app_name ON skill_chunks (app_name);
            CREATE INDEX IF NOT EXISTS ix_skill_chunks_domain ON skill_chunks (domain);
            CREATE INDEX IF NOT EXISTS ix_skill_chunks_chunk_type ON skill_chunks (chunk_type);
            CREATE INDEX IF NOT EXISTS ix_skill_chunks_parent ON skill_chunks (parent_chunk_id) WHERE parent_chunk_id IS NOT NULL;
            """
        )
    )

    # ── rule_chunks 테이블 (룰 벡터 검색용) ────────────────────────────
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS rule_chunks (
                id SERIAL PRIMARY KEY,
                rule_type VARCHAR(16) NOT NULL,
                rule_entity_id INTEGER NOT NULL,
                app_name VARCHAR(128),
                pattern VARCHAR(256),
                domain VARCHAR(64),
                section_name VARCHAR(128) NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding vector(384),
                metadata JSONB NOT NULL DEFAULT '{}',
                chunk_type VARCHAR(16) NOT NULL DEFAULT 'child',
                parent_chunk_id INTEGER REFERENCES rule_chunks(id) ON DELETE SET NULL,
                CONSTRAINT uq_rule_chunks_type_entity_idx UNIQUE (rule_type, rule_entity_id, chunk_index)
            );
            CREATE INDEX IF NOT EXISTS ix_rule_chunks_rule_type ON rule_chunks (rule_type);
            CREATE INDEX IF NOT EXISTS ix_rule_chunks_entity_id ON rule_chunks (rule_entity_id);
            CREATE INDEX IF NOT EXISTS ix_rule_chunks_app_name ON rule_chunks (app_name);
            CREATE INDEX IF NOT EXISTS ix_rule_chunks_pattern ON rule_chunks (pattern);
            CREATE INDEX IF NOT EXISTS ix_rule_chunks_domain ON rule_chunks (domain);
            CREATE INDEX IF NOT EXISTS ix_rule_chunks_chunk_type ON rule_chunks (chunk_type);
            CREATE INDEX IF NOT EXISTS ix_rule_chunks_parent ON rule_chunks (parent_chunk_id) WHERE parent_chunk_id IS NOT NULL;
            """
        )
    )


    # ── Workflows 테이블 생성 (Rules/Skills와 별개) ──────────────────────
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS global_workflow_versions (
                id SERIAL PRIMARY KEY,
                section_name VARCHAR(128) NOT NULL DEFAULT 'main',
                version INTEGER NOT NULL,
                body TEXT NOT NULL,
                domain VARCHAR(64) NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_global_workflow_versions_section_version UNIQUE (section_name, version)
            );
            CREATE INDEX IF NOT EXISTS ix_global_workflow_versions_section_name ON global_workflow_versions (section_name);
            CREATE INDEX IF NOT EXISTS ix_global_workflow_versions_domain ON global_workflow_versions (domain);

            CREATE TABLE IF NOT EXISTS app_workflow_versions (
                id SERIAL PRIMARY KEY,
                app_name VARCHAR(128) NOT NULL,
                section_name VARCHAR(128) NOT NULL DEFAULT 'main',
                version INTEGER NOT NULL,
                body TEXT NOT NULL,
                domain VARCHAR(64) NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_app_workflow_versions_app_section_version UNIQUE (app_name, section_name, version)
            );
            CREATE INDEX IF NOT EXISTS ix_app_workflow_versions_app_name ON app_workflow_versions (app_name);
            CREATE INDEX IF NOT EXISTS ix_app_workflow_versions_section_name ON app_workflow_versions (section_name);
            CREATE INDEX IF NOT EXISTS ix_app_workflow_versions_domain ON app_workflow_versions (domain);

            CREATE TABLE IF NOT EXISTS repo_workflow_versions (
                id SERIAL PRIMARY KEY,
                pattern VARCHAR(256) NOT NULL DEFAULT '',
                section_name VARCHAR(128) NOT NULL DEFAULT 'main',
                sort_order INTEGER NOT NULL DEFAULT 100,
                version INTEGER NOT NULL,
                body TEXT NOT NULL,
                domain VARCHAR(64) NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_repo_workflow_versions_pattern_section_version UNIQUE (pattern, section_name, version)
            );
            CREATE INDEX IF NOT EXISTS ix_repo_workflow_versions_pattern ON repo_workflow_versions (pattern);
            CREATE INDEX IF NOT EXISTS ix_repo_workflow_versions_section_name ON repo_workflow_versions (section_name);
            CREATE INDEX IF NOT EXISTS ix_repo_workflow_versions_domain ON repo_workflow_versions (domain);
            """
        )
    )

    # ── 데이터 마이그레이션: skill → workflow 이동 (idempotent) ─────────
    connection.execute(
        text(
            """
            -- global: 워크플로우 스킬을 워크플로우 테이블로 이동
            INSERT INTO global_workflow_versions (section_name, version, body, domain, created_at)
            SELECT 'spec-implementation', 1, body, domain, created_at
            FROM global_skill_versions WHERE section_name='spec-implementation-workflow' AND version=1
            ON CONFLICT DO NOTHING;

            INSERT INTO global_workflow_versions (section_name, version, body, domain, created_at)
            SELECT 'spec-scan', 1, body, domain, created_at
            FROM global_skill_versions WHERE section_name='spec-scan-workflow' AND version=2
            ON CONFLICT DO NOTHING;

            INSERT INTO global_workflow_versions (section_name, version, body, domain, created_at)
            SELECT 'error-hunt', 1, body, domain, created_at
            FROM global_skill_versions WHERE section_name='error-hunt-workflow' AND version=3
            ON CONFLICT DO NOTHING;

            -- app: orchestrator → spec-implementation 워크플로우
            INSERT INTO app_workflow_versions (app_name, section_name, version, body, domain, created_at)
            SELECT app_name, 'spec-implementation', 1, body, domain, created_at
            FROM app_skill_versions
            WHERE app_name='adventure' AND section_name='orchestrator'
              AND version=(SELECT MAX(version) FROM app_skill_versions WHERE app_name='adventure' AND section_name='orchestrator')
            ON CONFLICT DO NOTHING;

            -- repo: workflow-* → 워크플로우 테이블
            INSERT INTO repo_workflow_versions (pattern, section_name, version, sort_order, body, domain, created_at)
            SELECT pattern, REPLACE(section_name, 'workflow-', ''), 1, sort_order, body, domain, created_at
            FROM repo_skill_versions
            WHERE section_name LIKE 'workflow-%'
            ON CONFLICT DO NOTHING;
            """
        )
    )

    # ── 이동 완료 후 스킬 테이블 정리 (안전 체크 포함) ────────────────
    connection.execute(
        text(
            """
            DELETE FROM global_skill_versions WHERE section_name='spec-implementation-workflow'
              AND EXISTS (SELECT 1 FROM global_workflow_versions WHERE section_name='spec-implementation');
            DELETE FROM global_skill_versions WHERE section_name='spec-scan-workflow'
              AND EXISTS (SELECT 1 FROM global_workflow_versions WHERE section_name='spec-scan');
            DELETE FROM global_skill_versions WHERE section_name='error-hunt-workflow'
              AND EXISTS (SELECT 1 FROM global_workflow_versions WHERE section_name='error-hunt');
            DELETE FROM app_skill_versions WHERE app_name='adventure' AND section_name='orchestrator'
              AND EXISTS (SELECT 1 FROM app_workflow_versions WHERE app_name='adventure' AND section_name='spec-implementation');
            DELETE FROM repo_skill_versions WHERE section_name LIKE 'workflow-%'
              AND EXISTS (SELECT 1 FROM repo_workflow_versions LIMIT 1);

            -- 중복/불필요 데이터 정리
            DELETE FROM global_skill_versions WHERE section_name='compound-workflow';
            DELETE FROM global_skill_versions WHERE section_name='mcp-usage' AND version=1
              AND EXISTS (SELECT 1 FROM global_skill_versions WHERE section_name='mcp-usage' AND version=2);
            DELETE FROM global_skill_versions WHERE section_name='harness-construction' AND version=1
              AND EXISTS (SELECT 1 FROM global_skill_versions WHERE section_name='harness-construction' AND version=2);
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
    # ── skill_chunks: FTS generated column + GIN + HNSW ──────────────────
    connection.execute(
        text(
            """
            DO $$
            BEGIN
              IF to_regclass('public.skill_chunks') IS NOT NULL THEN
                IF NOT EXISTS (
                  SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'public' AND table_name = 'skill_chunks'
                    AND column_name = 'content_tsv'
                ) THEN
                  ALTER TABLE skill_chunks ADD COLUMN content_tsv tsvector
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
              IF to_regclass('public.skill_chunks') IS NOT NULL THEN
                EXECUTE $idx$
                  CREATE INDEX IF NOT EXISTS skill_chunks_content_tsv_idx
                  ON skill_chunks USING GIN (content_tsv);
                $idx$;
                EXECUTE $idx$
                  CREATE INDEX IF NOT EXISTS skill_chunks_embedding_hnsw_idx
                  ON skill_chunks USING hnsw (embedding vector_cosine_ops)
                  WITH (m = 16, ef_construction = 64);
                $idx$;
              END IF;
            END $$;
            """
        )
    )
    # ── rule_chunks: FTS generated column + GIN + HNSW ───────────────────
    connection.execute(
        text(
            """
            DO $$
            BEGIN
              IF to_regclass('public.rule_chunks') IS NOT NULL THEN
                IF NOT EXISTS (
                  SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'public' AND table_name = 'rule_chunks'
                    AND column_name = 'content_tsv'
                ) THEN
                  ALTER TABLE rule_chunks ADD COLUMN content_tsv tsvector
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
              IF to_regclass('public.rule_chunks') IS NOT NULL THEN
                EXECUTE $idx$
                  CREATE INDEX IF NOT EXISTS rule_chunks_content_tsv_idx
                  ON rule_chunks USING GIN (content_tsv);
                $idx$;
                EXECUTE $idx$
                  CREATE INDEX IF NOT EXISTS rule_chunks_embedding_hnsw_idx
                  ON rule_chunks USING hnsw (embedding vector_cosine_ops)
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
