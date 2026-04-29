"""OAuth/MCP 세션 스토어 추상화 (L01/L02/L03 대응).

근거:
    - docs/design-docs/session-store-redis.md
    - docs/audit_2026-04-29.md L01/L02/L03

`McperOAuthProvider` 와 `complete_authorization` 내부에서 사용하던
인메모리 dict 6개(_auth_codes, _clients, _refresh_tokens,
_pending_auth_requests, _code_user_map, _access_tokens)를 이 모듈의
SessionStore Protocol 로 추상화한다.

InMemorySessionStore — 프로세스 메모리 기반 (기본). 단일 인스턴스 운영.

값은 JSON 직렬화 가능한 dict 로 가정한다. pydantic 모델은 provider
레이어에서 `.model_dump(mode='json')` / `.model_validate()` 로 변환한 뒤
이 스토어에 넣는다.

후속 PR 에서 RedisSessionStore 를 추가해 ``MCPER_SESSION_STORE=redis``
로 스위칭 가능하게 한다.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

# 기본 TTL (초). 호출 측에서 override 가능.
DEFAULT_AUTH_CODE_TTL = 600          # OAuth authorization code
DEFAULT_ACCESS_TOKEN_TTL = 3600      # access token (1h)
DEFAULT_REFRESH_TOKEN_TTL = 2592000  # refresh token (30d)
DEFAULT_PENDING_AUTH_TTL = 300       # pending auth request (5m)
DEFAULT_CLIENT_TTL = 2592000         # DCR client (30d, None 이면 무기한)
DEFAULT_CODE_USER_TTL = 600          # code→user 매핑


class SessionStore(Protocol):
    """OAuth/MCP 세션 데이터 저장소 Protocol."""

    # ── OAuth authorization code ──────────────────────────────────────
    def save_auth_code(self, code: str, data: dict, ttl: int) -> None: ...
    def get_auth_code(self, code: str) -> Optional[dict]: ...
    def pop_auth_code(self, code: str) -> Optional[dict]: ...

    # ── Registered OAuth client (DCR) ─────────────────────────────────
    def save_client(self, client_id: str, data: dict, ttl: Optional[int] = None) -> None: ...
    def get_client(self, client_id: str) -> Optional[dict]: ...

    # ── Refresh token ─────────────────────────────────────────────────
    def save_refresh_token(self, token: str, data: dict, ttl: int) -> None: ...
    def pop_refresh_token(self, token: str) -> Optional[dict]: ...
    def get_refresh_token(self, token: str) -> Optional[dict]: ...

    # ── Access token (짧은 TTL, 조회 전용) ────────────────────────────
    def save_access_token(self, token: str, data: dict, ttl: int) -> None: ...
    def get_access_token(self, token: str) -> Optional[dict]: ...
    def delete_access_token(self, token: str) -> None: ...

    # ── Pending authorization request (로그인 폼 → callback) ──────────
    def save_pending_auth(self, request_id: str, data: dict, ttl: int) -> None: ...
    def pop_pending_auth(self, request_id: str) -> Optional[dict]: ...

    # ── Code → user_id mapping ────────────────────────────────────────
    def save_code_user(self, code: str, user_id: str, ttl: int) -> None: ...
    def get_code_user(self, code: str) -> Optional[str]: ...
    def pop_code_user(self, code: str) -> Optional[str]: ...

    # ── 운영 ──────────────────────────────────────────────────────────
    def access_token_count(self) -> int:
        """디버깅/로깅용. 외부 스토어는 추산치(-1) 반환 가능."""
        ...


# ══════════════════════════════════════════════════════════════════════
# InMemory 구현
# ══════════════════════════════════════════════════════════════════════


class _TTLDict:
    """TTL 지원 dict 경량 래퍼. (value, expires_at) 저장."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, Optional[float]]] = {}

    def set(self, key: str, value: Any, ttl: Optional[int]) -> None:
        expires_at = time.time() + ttl if ttl is not None else None
        self._data[key] = (value, expires_at)

    def get(self, key: str) -> Optional[Any]:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and expires_at < time.time():
            self._data.pop(key, None)
            return None
        return value

    def pop(self, key: str) -> Optional[Any]:
        entry = self._data.pop(key, None)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and expires_at < time.time():
            return None
        return value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def __len__(self) -> int:
        # 만료 항목 포함. 모니터링용이라 정확도 요구치 낮음.
        return len(self._data)


class InMemorySessionStore:
    """프로세스 메모리 기반 SessionStore. 기존 dict 6개 동작을 그대로 이관."""

    def __init__(self) -> None:
        self._codes = _TTLDict()
        self._clients = _TTLDict()
        self._refresh = _TTLDict()
        self._access = _TTLDict()
        self._pending = _TTLDict()
        self._code_user = _TTLDict()

    # auth code
    def save_auth_code(self, code: str, data: dict, ttl: int) -> None:
        self._codes.set(code, data, ttl)

    def get_auth_code(self, code: str) -> Optional[dict]:
        return self._codes.get(code)

    def pop_auth_code(self, code: str) -> Optional[dict]:
        return self._codes.pop(code)

    # client
    def save_client(self, client_id: str, data: dict, ttl: Optional[int] = None) -> None:
        self._clients.set(client_id, data, ttl)

    def get_client(self, client_id: str) -> Optional[dict]:
        return self._clients.get(client_id)

    # refresh
    def save_refresh_token(self, token: str, data: dict, ttl: int) -> None:
        self._refresh.set(token, data, ttl)

    def pop_refresh_token(self, token: str) -> Optional[dict]:
        return self._refresh.pop(token)

    def get_refresh_token(self, token: str) -> Optional[dict]:
        return self._refresh.get(token)

    # access
    def save_access_token(self, token: str, data: dict, ttl: int) -> None:
        self._access.set(token, data, ttl)

    def get_access_token(self, token: str) -> Optional[dict]:
        return self._access.get(token)

    def delete_access_token(self, token: str) -> None:
        self._access.delete(token)

    # pending
    def save_pending_auth(self, request_id: str, data: dict, ttl: int) -> None:
        self._pending.set(request_id, data, ttl)

    def pop_pending_auth(self, request_id: str) -> Optional[dict]:
        return self._pending.pop(request_id)

    # code → user
    def save_code_user(self, code: str, user_id: str, ttl: int) -> None:
        self._code_user.set(code, user_id, ttl)

    def get_code_user(self, code: str) -> Optional[str]:
        return self._code_user.get(code)

    def pop_code_user(self, code: str) -> Optional[str]:
        return self._code_user.pop(code)

    def access_token_count(self) -> int:
        return len(self._access)


# ══════════════════════════════════════════════════════════════════════
# 팩토리
# ══════════════════════════════════════════════════════════════════════

_instance: Optional[SessionStore] = None
_factory_lock = threading.Lock()


def get_session_store() -> SessionStore:
    """프로세스 수명 동안 단일 SessionStore 를 반환.

    현재는 InMemorySessionStore 만 지원. 후속 PR 에서
    ``MCPER_SESSION_STORE=redis`` 스위치로 RedisSessionStore 선택 가능.
    """
    global _instance
    if _instance is not None:
        return _instance
    with _factory_lock:
        if _instance is not None:
            return _instance
        logger.info("SessionStore: using InMemorySessionStore")
        _instance = InMemorySessionStore()
    return _instance


def reset_session_store() -> None:
    """테스트 전용. 싱글톤을 리셋한다."""
    global _instance
    with _factory_lock:
        _instance = None


__all__ = [
    "SessionStore",
    "InMemorySessionStore",
    "get_session_store",
    "reset_session_store",
    "DEFAULT_AUTH_CODE_TTL",
    "DEFAULT_ACCESS_TOKEN_TTL",
    "DEFAULT_REFRESH_TOKEN_TTL",
    "DEFAULT_PENDING_AUTH_TTL",
    "DEFAULT_CLIENT_TTL",
    "DEFAULT_CODE_USER_TTL",
]
