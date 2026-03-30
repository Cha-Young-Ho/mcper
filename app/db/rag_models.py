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
    """Semantic slice of a planning spec with embedding + FTS (content_tsv via migration)."""

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
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim), nullable=False)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)

    spec: Mapped[Spec] = relationship("Spec", back_populates="chunks")


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
