"""spec 도메인 데이터클래스 — ORM에 의존하지 않는 순수 도메인 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ChunkType = Literal["parent", "child"]


@dataclass
class ChunkRecord:
    """청킹 전략이 생산하는 단위 레코드.

    chunk_type:
        "parent" — 섹션 원문 전체. 임베딩 없음. chunk_index 는 음수(-1, -2, …).
        "child"  — 임베딩 대상 작은 조각. chunk_index 는 0 이상.
                   parent_chunk_index 가 None 이면 독립 청크(작은 섹션).
    """

    content: str
    embed_text: str  # 임베딩에 넣을 텍스트 (컨텍스트 주입 포함). parent 는 미사용.
    chunk_type: ChunkType
    chunk_index: int  # parent: -(n+1),  child: 전역 순서 0‥
    section_heading: str | None
    parent_chunk_index: (
        int | None
    )  # child 가 속한 parent 의 chunk_index(음수). 독립 child 는 None.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IndexResult:
    ok: bool
    spec_id: int
    parent_count: int = 0
    child_count: int = 0
    error: str | None = None

    @property
    def total_embedded(self) -> int:
        return self.child_count
