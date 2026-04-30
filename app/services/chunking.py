"""Recursive character splitting for spec text (token-approx via character budget)."""

from __future__ import annotations

import re
from typing import Any

# ~512 tokens rough budget (English-heavy); Korean needs smaller char budget — conservative
DEFAULT_CHUNK_CHARS = 1800
DEFAULT_OVERLAP_CHARS = 180


def _split_recursive(
    text: str, separators: list[str], chunk_size: int, overlap: int
) -> list[str]:
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


def extract_markdown_headers(text: str) -> list[tuple[int, str]]:
    """Return (line_index, header_text) for # headers."""
    headers: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines()):
        m = re.match(r"^#{1,6}\s+(.+)$", line.strip())
        if m:
            headers.append((i, m.group(1).strip()))
    return headers


def nearest_header(line_no: int, headers: list[tuple[int, str]]) -> str | None:
    cur: str | None = None
    for ln, title in headers:
        if ln <= line_no:
            cur = title
        else:
            break
    return cur


def chunk_spec_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_OVERLAP_CHARS,
    base_metadata: dict[str, Any] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """
    Split spec body into (chunk_text, metadata) with heading hints.
    """
    base = dict(base_metadata or {})
    headers = extract_markdown_headers(text)
    separators = ["\n\n", "\n", ". ", " ", ""]
    raw_chunks = _split_recursive(text, separators, chunk_size, overlap)
    out: list[tuple[str, dict[str, Any]]] = []
    cursor = 0
    for idx, chunk in enumerate(raw_chunks):
        meta = {**base, "chunk_index": idx}
        pos = text.find(chunk, cursor)
        if pos >= 0:
            line_no = text.count("\n", 0, pos)
            h = nearest_header(line_no, headers)
            if h:
                meta["section_heading"] = h
            cursor = pos + max(1, len(chunk) // 2)
        out.append((chunk, meta))
    return out
