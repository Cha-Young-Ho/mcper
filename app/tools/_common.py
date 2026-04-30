"""MCP 도구 공통 헬퍼."""

from __future__ import annotations

import json
from typing import Any


def _normalize_app_name(raw: str) -> str:
    """INI `app_name` 정규화 — 따옴표 제거, `name/branch` 형태에서 name 부분만 사용."""
    s = raw.strip().strip('"').strip("'")
    if "/" in s:
        s = s.split("/", 1)[0].strip()
    return s


def error_payload(message: str, **extra: Any) -> dict[str, Any]:
    """MCP 도구 공통 에러 스키마 dict 형태. `{ok: false, error: str, ...extra}`."""
    return {"ok": False, "error": message, **extra}


def error_json(message: str, **extra: Any) -> str:
    """MCP 도구 공통 에러 스키마 JSON 문자열 형태. 일부 도구가 JSON 직렬화 결과를 반환."""
    return json.dumps(error_payload(message, **extra), ensure_ascii=False)
