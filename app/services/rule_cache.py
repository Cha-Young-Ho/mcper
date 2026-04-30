"""Versioned rule Redis 캐시 (P12).

근거:
    - docs/audit_2026-04-29.md P12
    - `app/services/versioned_rules.py` 의 `get_rules_markdown` 등은
      (app_name, origin_url, version) 조합별로 동일 DB 쿼리를 반복 수행한다.
      Redis 가 이미 배치돼 있으므로 얇은 LRU(TTL) 캐시 레이어를 얹어
      핫패스 지연을 줄인다.

설계:
    - `MCPER_RULE_CACHE` env 가 "redis" 일 때만 활성화. 그 외/미설정이면
      모든 API 가 no-op (기본 동작 변경 없음).
    - Redis 미가용(URL 없음, 연결 실패 등)이면 경고 로그만 남기고 None 반환.
      캐시 장애가 서비스 응답 경로를 깨지 않도록 격리한다.
    - 캐시 값은 **문자열 그대로** 저장 (마크다운). JSON 래핑 생략해 직렬화 비용 없음.
    - invalidate 는 `SCAN + DELETE` 패턴 기반. 키 수가 적어 성능 문제 없음.

키 스킴:
    ``mcper:rule:<app_name>:<origin_url>:<version>``
    - app_name 없음 / origin_url 없음 / 최신 은 각각 ``-`` / ``-`` / ``latest`` 로 대체.
    - pattern invalidate 시 glob: ``mcper:rule:<app_name>:*`` 등.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_REDIS_PREFIX = "mcper:rule:"
_DEFAULT_TTL = 300  # 5분


def _cache_enabled() -> bool:
    """env 토글이 "redis" 일 때만 True. 기본값에서는 항상 False (동작 변경 0)."""
    return os.environ.get("MCPER_RULE_CACHE", "off").lower().strip() == "redis"


def _client():
    """Redis 클라이언트(없으면 None). 예외는 여기서 흡수해 호출 측을 단순화."""
    if not _cache_enabled():
        return None
    try:
        from app.services.redis_pool import get_redis

        return get_redis()
    except Exception:  # noqa: BLE001 — 캐시 장애가 응답을 깨지 않도록 흡수
        logger.warning("rule_cache: redis_pool import failed", exc_info=True)
        return None


def build_rule_cache_key(
    *,
    app_name: str | None,
    origin_url: str | None,
    version: int | str | None,
) -> str:
    """`get_cached_rule` / `set_cached_rule` 에 넘길 공통 키 빌더.

    호출 측이 동일 규칙으로 키를 구성하도록 단일 진입점을 제공한다.
    """
    a = (app_name or "").strip().lower() or "-"
    u = (origin_url or "").strip() or "-"
    if version is None or (isinstance(version, str) and not version.strip()):
        v = "latest"
    else:
        v = str(version).strip().lower() or "latest"
    return f"{a}:{u}:{v}"


def get_cached_rule(key: str) -> Optional[str]:
    """캐시 히트시 본문 문자열, 미스/비활성/장애시 None."""
    cli = _client()
    if cli is None:
        return None
    try:
        v = cli.get(_REDIS_PREFIX + key)
    except Exception:  # noqa: BLE001 — 네트워크/타임아웃 등
        logger.warning("rule_cache.get failed key=%s", key, exc_info=True)
        return None
    if v is None:
        return None
    # redis_pool 은 decode_responses=True 이므로 str 로 돌아온다.
    return v if isinstance(v, str) else str(v)


def set_cached_rule(key: str, body: str, ttl: int = _DEFAULT_TTL) -> None:
    """캐시에 본문 저장 (TTL 기본 5분). 비활성/장애시 silent no-op."""
    cli = _client()
    if cli is None:
        return
    try:
        cli.set(_REDIS_PREFIX + key, body, ex=ttl)
    except Exception:  # noqa: BLE001
        logger.warning("rule_cache.set failed key=%s", key, exc_info=True)


def invalidate_rule(pattern: str) -> int:
    """glob 패턴 매칭 키들을 삭제. 삭제된 키 수 반환 (비활성/장애시 0).

    pattern 예:
        - ``"*"`` : 전체 룰 캐시 flush
        - ``"myapp:*"`` : 특정 app 전체
        - ``"-:*"`` : app_name 없음(= global 조회) 전체
    """
    cli = _client()
    if cli is None:
        return 0
    full_pattern = _REDIS_PREFIX + pattern
    deleted = 0
    try:
        # SCAN 으로 큰 키스페이스에서도 블로킹 없이 안전하게 순회.
        cursor = 0
        while True:
            cursor, keys = cli.scan(cursor=cursor, match=full_pattern, count=200)
            if keys:
                deleted += int(cli.delete(*keys) or 0)
            if cursor == 0:
                break
    except Exception:  # noqa: BLE001
        logger.warning(
            "rule_cache.invalidate failed pattern=%s", pattern, exc_info=True
        )
        return deleted
    return deleted


__all__ = [
    "build_rule_cache_key",
    "get_cached_rule",
    "set_cached_rule",
    "invalidate_rule",
]
