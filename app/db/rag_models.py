"""RAG tables: spec chunks, code graph nodes/edges (pgvector)."""

from __future__ import annotations

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db.models import Base, Spec


class SpecChunk(Base):
    """Semantic slice of a planning spec with embedding + FTS (content_tsv via migration).

    chunk_type:
        'child'  — 임베딩 대상 작은 조각 (검색 히트). chunk_index >= 0.
        'parent' — 섹션 원문 전체 (컨텍스트 반환용). chunk_index < 0. embedding = NULL.
    레거시 행(마이그레이션 이전)은 chunk_type='child', parent_chunk_id=NULL 로 간주.
    """

    __tablename__ = "spec_chunks"
    __table_args__ = (
        UniqueConstraint("spec_id", "chunk_index", name="uq_spec_chunks_spec_chunk_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spec_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("specs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # parent 청크는 embedding 없음 → nullable
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)

    # Parent-Child 관계 컬럼 (마이그레이션 필요: scripts/migrate_spec_chunks_parent_child.sql)
    chunk_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="child", index=True
    )
    parent_chunk_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("spec_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    spec: Mapped[Spec] = relationship("Spec", back_populates="chunks")


class SkillChunk(Base):
    """Semantic slice of a skill body with embedding + FTS (content_tsv via migration).

    skill_type: 'global', 'app', 'repo' — 어떤 스킬 테이블의 행인지.
    skill_entity_id: 해당 *_skill_versions.id.
    chunk_type: 'child' (임베딩 대상) / 'parent' (섹션 원문 컨텍스트).
    """

    __tablename__ = "skill_chunks"
    __table_args__ = (
        UniqueConstraint(
            "skill_type", "skill_entity_id", "chunk_index",
            name="uq_skill_chunks_type_entity_idx",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    skill_entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    app_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    section_name: Mapped[str] = mapped_column(String(128), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)
    chunk_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="child", index=True
    )
    parent_chunk_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("skill_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class RuleChunk(Base):
    """Semantic slice of a rule body with embedding + FTS (content_tsv via migration).

    rule_type: 'global', 'app', 'repo' — 어떤 룰 테이블의 행인지.
    rule_entity_id: 해당 *_rule_versions.id.
    chunk_type: 'child' (임베딩 대상) / 'parent' (섹션 원문 컨텍스트).
    """

    __tablename__ = "rule_chunks"
    __table_args__ = (
        UniqueConstraint(
            "rule_type", "rule_entity_id", "chunk_index",
            name="uq_rule_chunks_type_entity_idx",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    rule_entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    app_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    pattern: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    section_name: Mapped[str] = mapped_column(String(128), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)
    chunk_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="child", index=True
    )
    parent_chunk_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("rule_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class WorkflowChunk(Base):
    """Semantic slice of a workflow body with embedding + FTS (content_tsv via migration).

    workflow_type: 'global', 'app', 'repo' — 어떤 워크플로우 테이블의 행인지.
    workflow_entity_id: 해당 *_workflow_versions.id.
    chunk_type: 'child' (임베딩 대상) / 'parent' (섹션 원문 컨텍스트).
    """

    __tablename__ = "workflow_chunks"
    __table_args__ = (
        UniqueConstraint(
            "workflow_type", "workflow_entity_id", "chunk_index",
            name="uq_workflow_chunks_type_entity_idx",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    workflow_entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    app_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    pattern: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    section_name: Mapped[str] = mapped_column(String(128), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)
    chunk_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="child", index=True
    )
    parent_chunk_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("workflow_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class DocChunk(Base):
    """Semantic slice of a doc body with embedding + FTS (content_tsv via migration).

    doc_type: 'global', 'app', 'repo' — 어떤 docs 테이블의 행인지.
    doc_entity_id: 해당 *_doc_versions.id.
    chunk_type: 'child' (임베딩 대상) / 'parent' (섹션 원문 컨텍스트).
    """

    __tablename__ = "doc_chunks"
    __table_args__ = (
        UniqueConstraint(
            "doc_type", "doc_entity_id", "chunk_index",
            name="uq_doc_chunks_type_entity_idx",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    doc_entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    app_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    pattern: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    section_name: Mapped[str] = mapped_column(String(128), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)
    chunk_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="child", index=True
    )
    parent_chunk_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("doc_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class CodeNode(Base):
    """AST-level or symbol-level code unit for GraphRAG search."""

    __tablename__ = "code_nodes"
    __table_args__ = (UniqueConstraint("app_target", "stable_id", name="uq_code_nodes_app_stable"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_target: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    stable_id: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    symbol_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="fragment")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim), nullable=False)
    node_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)


class CodeEdge(Base):
    """Directed relationship between code nodes (CALLS, IMPORTS, etc.)."""

    __tablename__ = "code_edges"
    __table_args__ = (
        UniqueConstraint(
            "app_target", "source_id", "target_id", "relation",
            name="uq_code_edges_app_src_tgt_rel",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_target: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("code_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("code_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation: Mapped[str] = mapped_column(String(64), nullable=False)


# Attach reverse relationship on Spec (same module import order: models first)
Spec.chunks = relationship(  # type: ignore[attr-defined]
    "SpecChunk",
    back_populates="spec",
    cascade="all, delete-orphan",
)
