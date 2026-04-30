"""Admin 라우터 공통 헬퍼 — 정렬/표시 유틸."""

from __future__ import annotations


def _sort_app_names(names: list[str]) -> list[str]:
    """`__default__` 카드가 그리드 왼쪽 상단에 오도록 우선 정렬."""

    def key(n: str) -> tuple[int, str]:
        """정렬용 키 추출 함수 (로컬 클로저)."""
        if n.lower() == "__default__":
            return (0, "")
        return (1, n.lower())

    return sorted(names, key=key)


def _sort_repo_patterns(patterns: list[str]) -> list[str]:
    """빈 패턴(default) 카드가 먼저 오도록 정렬."""

    def key(p: str) -> tuple[int, str]:
        """정렬용 키 추출 함수 (로컬 클로저)."""
        if not (p or "").strip():
            return (0, "")
        return (1, (p or "").lower())

    return sorted(patterns, key=key)


def _section_display(sn: str, default_section: str) -> str:
    """섹션 표시명 — 기본 섹션이면 '기본', 아니면 원본 그대로."""
    return "기본" if sn == default_section else sn
