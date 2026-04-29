"""MCP 도구 공통 헬퍼."""

from __future__ import annotations


def _normalize_app_name(raw: str) -> str:
    """INI `app_name` 정규화 — 따옴표 제거, `name/branch` 형태에서 name 부분만 사용."""
    s = raw.strip().strip('"').strip("'")
    if "/" in s:
        s = s.split("/", 1)[0].strip()
    return s
