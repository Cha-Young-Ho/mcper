"""청킹 전략 구현체.

HeadingAwareParentChildChunker — H1/H2 헤딩 경계로 섹션 분리 후 Parent-Child 구조 생성.
FixedSizeChunker               — 기존 고정 크기 분할 (레거시 호환 / 단순 문서용).

교체 방법:
    make_default_service(db, strategy=FixedSizeChunker()) 로 전달.
"""

from __future__ import annotations

import re
from typing import Any

from app.spec.interfaces import IChunkingStrategy  # noqa: F401 (re-export)
from app.spec.models import ChunkRecord

# ── 크기 상수 ──────────────────────────────────────────────────────────────────
PARENT_CHARS = 1500  # 섹션 원문 최대 길이 (반환용 컨텍스트)
CHILD_CHARS = 400  # 임베딩 대상 청크 최대 길이
LEGACY_CHUNK_CHARS = 1800
LEGACY_OVERLAP_CHARS = 180


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────


def _split_text(text: str, chunk_size: int) -> list[str]:
    """단락/줄/문장 경계를 우선해서 chunk_size 로 분할. 오버랩 없음."""
    if len(text) <= chunk_size:
        return [text.strip()] if text.strip() else []

    chunks: list[str] = []
    seps = ["\n\n", "\n", ". ", " "]
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            for sep in seps:
                idx = text.rfind(sep, start + chunk_size // 3, end)
                if idx > start:
                    end = idx + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end
    return chunks


def _split_recursive(text: str, chunk_size: int, overlap: int) -> list[str]:
    """오버랩 있는 재귀 분할 (FixedSizeChunker 에서 사용)."""
    separators = ["\n\n", "\n", ". ", " ", ""]
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        piece = text[start:end]
        if end < len(text):
            best = -1
            for sep in separators:
                if not sep:
                    continue
                idx = piece.rfind(sep)
                if idx > best:
                    best = idx
            if best > chunk_size // 3:
                end = start + best + (len(separators[0]) if separators[0] else 0)
                piece = text[start:end]
        piece = piece.strip()
        if piece:
            chunks.append(piece)
        start = end - overlap if end - overlap > start else end
        if start >= len(text):
            break
        if start <= 0:
            start = end
    return chunks


def _enrich(text: str, meta: dict[str, Any]) -> str:
    """임베딩 품질 향상을 위해 기획서명·섹션 헤딩을 앞에 주입."""
    parts: list[str] = []
    if meta.get("spec_title"):
        parts.append(f"[기획서: {meta['spec_title']}]")
    if meta.get("section_heading"):
        parts.append(f"[섹션: {meta['section_heading']}]")
    return (" ".join(parts) + "\n" + text) if parts else text


# ── 전략 1: HeadingAwareParentChildChunker ─────────────────────────────────────


class HeadingAwareParentChildChunker:
    """H1/H2 헤딩 경계 분리 + Parent-Child 구조.

    섹션마다:
      - Parent(chunk_index 음수): 섹션 원문 전체, 임베딩 없음, 검색 결과 컨텍스트 반환용.
      - Child(chunk_index 0…): CHILD_CHARS 단위, 임베딩 대상.
        섹션이 CHILD_CHARS 이하면 parent 없이 독립 child 로만 생성.

    헤딩이 없는 문서도 전체를 단일 섹션으로 처리하므로 항상 동작.
    """

    def chunk(self, text: str, base_metadata: dict[str, Any]) -> list[ChunkRecord]:
        sections = self._split_by_headings(text)
        records: list[ChunkRecord] = []
        parent_seq = -1  # -1, -2, -3 … (음수)
        child_seq = 0  # 0, 1, 2 … (양수)

        for heading, section_text in sections:
            section_text = section_text.strip()
            if not section_text:
                continue

            meta = {**base_metadata}
            if heading:
                meta["section_heading"] = heading

            raw_children = _split_text(section_text, CHILD_CHARS)
            if not raw_children:
                continue

            needs_parent = len(section_text) > CHILD_CHARS

            if needs_parent:
                # Parent record — 섹션 원문 전체 (임베딩 없음)
                parent_record = ChunkRecord(
                    content=section_text,
                    embed_text=section_text,  # 미사용
                    chunk_type="parent",
                    chunk_index=parent_seq,
                    section_heading=heading,
                    parent_chunk_index=None,
                    metadata=dict(meta),
                )
                records.append(parent_record)

            for child_text in raw_children:
                records.append(
                    ChunkRecord(
                        content=child_text,
                        embed_text=_enrich(child_text, meta),
                        chunk_type="child",
                        chunk_index=child_seq,
                        section_heading=heading,
                        parent_chunk_index=parent_seq if needs_parent else None,
                        metadata=dict(meta),
                    )
                )
                child_seq += 1

            if needs_parent:
                parent_seq -= 1

        return records

    def _split_by_headings(self, text: str) -> list[tuple[str | None, str]]:
        """H1/H2(# 또는 ##)를 경계로 섹션 분리."""
        pattern = re.compile(r"^#{1,2}\s+(.+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))

        if not matches:
            return [(None, text)]

        sections: list[tuple[str | None, str]] = []
        pre = text[: matches[0].start()].strip()
        if pre:
            sections.append((None, pre))

        for i, m in enumerate(matches):
            heading = m.group(1).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections.append((heading, text[start:end]))

        return sections


# ── 전략 2: FixedSizeChunker ──────────────────────────────────────────────────


class FixedSizeChunker:
    """기존 고정 크기 재귀 분할. Parent-Child 없이 모든 청크를 child 로 생성.

    기존 동작과 동일하므로 레거시 호환 또는 단순 문서에 적합.
    """

    def __init__(
        self,
        chunk_size: int = LEGACY_CHUNK_CHARS,
        overlap: int = LEGACY_OVERLAP_CHARS,
    ):
        self._chunk_size = chunk_size
        self._overlap = overlap

    def chunk(self, text: str, base_metadata: dict[str, Any]) -> list[ChunkRecord]:
        raw = _split_recursive(text, self._chunk_size, self._overlap)
        records: list[ChunkRecord] = []
        for i, piece in enumerate(raw):
            records.append(
                ChunkRecord(
                    content=piece,
                    embed_text=_enrich(piece, base_metadata),
                    chunk_type="child",
                    chunk_index=i,
                    section_heading=None,
                    parent_chunk_index=None,
                    metadata={**base_metadata},
                )
            )
        return records
