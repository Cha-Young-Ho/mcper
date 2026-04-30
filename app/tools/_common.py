"""MCP 도구 공통 헬퍼 + 응답 스키마 규약.

## 에러 응답 스키마 (Q14 통일)

모든 MCP 도구의 에러 응답은 아래 스키마를 따른다:

- dict 반환 도구 →  `{"ok": False, "error": "<message>", ...extra}`
- JSON 문자열 반환 도구 → `json.dumps({...동일...}, ensure_ascii=False)`

성공 응답은 도구별로 고유 스키마를 가지되, 최소한 `ok: True` 가 있으면
호출자가 에러 여부를 일관되게 판단할 수 있다 (`resp.get("ok", True)`).
레거시 성공 응답 중 `ok` 키가 없는 것도 있지만, **에러는 반드시** `ok=False`
플래그가 있어야 한다.

반드시 `error_payload()` / `error_json()` 를 거쳐 반환하고, 에러 문자열을
직접 구성(`{"error": ...}` 등)하지 말 것.
"""

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
