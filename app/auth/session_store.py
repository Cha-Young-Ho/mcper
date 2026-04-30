"""OAuth/MCP 세션 스토어 추상화 (L01/L02/L03 대응).

근거:
    - docs/design-docs/session-store-redis.md
    - docs/audit_2026-04-29.md L01/L02/L03

`McperOAuthProvider` 와 `complete_authorization` 내부에서 사용하던
인메모리 dict 6개(_auth_codes, _clients, _refresh_tokens,
_pending_auth_requests, _code_user_map, _access_tokens)를 이 모듈의
SessionStore Protocol 로 추상화한다.

InMemorySessionStore — 프로세스 메모리 기반 (기본). 단일 인스턴스 운영.
RedisSessionStore    — Redis 기반. LB 뒤 다중 인스턴스 운영.

선택: ``MCPER_SESSION_STORE=memory|redis`` (기본 memory, 하위 호환).
Redis 미설정/미접속 시 InMemory 로 폴백.

값은 JSON 직렬화 가능한 dict 로 가정한다. pydantic 모델은 provider
레이어에서 `.model_dump(mode='json')` / `.model_validate()` 로 변환한 뒤
이 스토어에 넣는다.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

# Redis key prefix — 운영 모니터링/격리 용도
_REDIS_PREFIX = "mcper:oauth:"

# 기본 TTL (초). 호출 측에서 override 가능.
DEFAULT_AUTH_CODE_TTL = 600  # OAuth authorization code
DEFAULT_ACCESS_TOKEN_TTL = 3600  # access token (1h)
DEFAULT_REFRESH_TOKEN_TTL = 2592000  # refresh token (30d)
DEFAULT_PENDING_AUTH_TTL = 300  # pending auth request (5m)
DEFAULT_CLIENT_TTL = 2592000  # DCR client (30d, None 이면 무기한)
DEFAULT_CODE_USER_TTL = 600  # code→user 매핑


class SessionStore(Protocol):
    """OAuth/MCP 세션 데이터 저장소 Protocol."""

    # ── OAuth authorization code ──────────────────────────────────────
    def save_auth_code(self, code: str, data: dict, ttl: int) -> None: ...
    def get_auth_code(self, code: str) -> Optional[dict]: ...
    def pop_auth_code(self, code: str) -> Optional[dict]: ...

    # ── Registered OAuth client (DCR) ─────────────────────────────────
    def save_client(
        self, client_id: str, data: dict, ttl: Optional[int] = None
    ) -> None: ...
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
        """디버깅/로깅용. Redis 는 추산치(-1) 반환 가능."""
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
    def save_client(
        self, client_id: str, data: dict, ttl: Optional[int] = None
    ) -> None:
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
# Redis 구현
# ══════════════════════════════════════════════════════════════════════


class RedisSessionStore:
    """Redis 기반 SessionStore. LB 뒤 다중 인스턴스 공유용.

    모든 값은 JSON 직렬화. 키는 ``mcper:oauth:<domain>:<id>`` 형식.
    TTL 은 Redis ``SET EX`` 로 강제. pop 은 ``GETDEL`` (Redis 6.2+).
    """

    _K_CODE = _REDIS_PREFIX + "code:"
    _K_CLIENT = _REDIS_PREFIX + "client:"
    _K_REFRESH = _REDIS_PREFIX + "refresh:"
    _K_ACCESS = _REDIS_PREFIX + "access:"
    _K_PENDING = _REDIS_PREFIX + "pending:"
    _K_CODE_USER = _REDIS_PREFIX + "code_user:"

    def __init__(self, client: Any) -> None:
        self._r = client

    # ── 내부 helpers ──────────────────────────────────────────────────
    def _set_json(self, key: str, data: dict, ttl: Optional[int]) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str)
        if ttl is not None:
            self._r.set(key, payload, ex=ttl)
        else:
            self._r.set(key, payload)

    def _get_json(self, key: str) -> Optional[dict]:
        raw = self._r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("RedisSessionStore: corrupt JSON at %s", key)
            return None

    def _getdel_json(self, key: str) -> Optional[dict]:
        raw = None
        # Redis 6.2+ GETDEL. 구버전 호환: GET + DELETE fallback.
        try:
            raw = self._r.getdel(key)
        except Exception:  # noqa: BLE001 — 구버전 redis-py 또는 서버 미지원
            try:
                raw = self._r.get(key)
                if raw is not None:
                    self._r.delete(key)
            except Exception:
                logger.exception(
                    "RedisSessionStore: getdel fallback failed for %s", key
                )
                return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("RedisSessionStore: corrupt JSON at %s", key)
            return None

    # ── auth code ────────────────────────────────────────────────────
    def save_auth_code(self, code: str, data: dict, ttl: int) -> None:
        self._set_json(self._K_CODE + code, data, ttl)

    def get_auth_code(self, code: str) -> Optional[dict]:
        return self._get_json(self._K_CODE + code)

    def pop_auth_code(self, code: str) -> Optional[dict]:
        return self._getdel_json(self._K_CODE + code)

    # ── client ───────────────────────────────────────────────────────
    def save_client(
        self, client_id: str, data: dict, ttl: Optional[int] = None
    ) -> None:
        self._set_json(self._K_CLIENT + client_id, data, ttl)

    def get_client(self, client_id: str) -> Optional[dict]:
        return self._get_json(self._K_CLIENT + client_id)

    # ── refresh ──────────────────────────────────────────────────────
    def save_refresh_token(self, token: str, data: dict, ttl: int) -> None:
        self._set_json(self._K_REFRESH + token, data, ttl)

    def pop_refresh_token(self, token: str) -> Optional[dict]:
        return self._getdel_json(self._K_REFRESH + token)

    def get_refresh_token(self, token: str) -> Optional[dict]:
        return self._get_json(self._K_REFRESH + token)

    # ── access ───────────────────────────────────────────────────────
    def save_access_token(self, token: str, data: dict, ttl: int) -> None:
        self._set_json(self._K_ACCESS + token, data, ttl)

    def get_access_token(self, token: str) -> Optional[dict]:
        return self._get_json(self._K_ACCESS + token)

    def delete_access_token(self, token: str) -> None:
        try:
            self._r.delete(self._K_ACCESS + token)
        except Exception:
            logger.exception("RedisSessionStore: delete_access_token failed")

    # ── pending auth ─────────────────────────────────────────────────
    def save_pending_auth(self, request_id: str, data: dict, ttl: int) -> None:
        self._set_json(self._K_PENDING + request_id, data, ttl)

    def pop_pending_auth(self, request_id: str) -> Optional[dict]:
        return self._getdel_json(self._K_PENDING + request_id)

    # ── code → user ──────────────────────────────────────────────────
    def save_code_user(self, code: str, user_id: str, ttl: int) -> None:
        # 단일 문자열. JSON 으로 감싸 일관성 유지 (파싱 간편).
        self._r.set(self._K_CODE_USER + code, str(user_id), ex=ttl)

    def get_code_user(self, code: str) -> Optional[str]:
        v = self._r.get(self._K_CODE_USER + code)
        return v if v is None else str(v)

    def pop_code_user(self, code: str) -> Optional[str]:
        try:
            v = self._r.getdel(self._K_CODE_USER + code)
        except Exception:  # noqa: BLE001
            v = self._r.get(self._K_CODE_USER + code)
            if v is not None:
                self._r.delete(self._K_CODE_USER + code)
        return v if v is None else str(v)

    def access_token_count(self) -> int:
        # 전체 스캔은 비싸므로 -1 (미상) 반환. 운영 시 keyspace 로 모니터링.
        return -1


# ══════════════════════════════════════════════════════════════════════
# 팩토리
# ══════════════════════════════════════════════════════════════════════

_instance: Optional[SessionStore] = None
_factory_lock = threading.Lock()


def get_session_store() -> SessionStore:
    """프로세스 수명 동안 단일 SessionStore 를 반환.

    MCPER_SESSION_STORE=redis 이면 RedisSessionStore, 그 외/미설정이면
    InMemorySessionStore. Redis 미설치/미접속 시 경고 후 InMemory 폴백.
    """
    global _instance
    if _instance is not None:
        return _instance
    with _factory_lock:
        if _instance is not None:
            return _instance
        mode = os.environ.get("MCPER_SESSION_STORE", "memory").lower().strip()
        if mode == "redis":
            try:
                from app.services.redis_pool import get_redis

                client = get_redis()
            except Exception:  # noqa: BLE001
                logger.exception("get_session_store: redis_pool import failed")
                client = None
            if client is None:
                logger.warning(
                    "MCPER_SESSION_STORE=redis but no Redis configured "
                    "(REDIS_URL / CELERY_BROKER_URL) — falling back to memory"
                )
                _instance = InMemorySessionStore()
            else:
                logger.info("SessionStore: using RedisSessionStore")
                _instance = RedisSessionStore(client)
        else:
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
    "RedisSessionStore",
    "get_session_store",
    "reset_session_store",
    "DEFAULT_AUTH_CODE_TTL",
    "DEFAULT_ACCESS_TOKEN_TTL",
    "DEFAULT_REFRESH_TOKEN_TTL",
    "DEFAULT_PENDING_AUTH_TTL",
    "DEFAULT_CLIENT_TTL",
    "DEFAULT_CODE_USER_TTL",
]
