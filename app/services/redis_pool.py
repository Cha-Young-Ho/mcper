"""공용 Redis 클라이언트 — 프로세스 수명 동안 단일 풀 재사용.

ad-hoc 으로 redis.from_url() 을 매 호출마다 생성하면 고부하 시 TCP 연결이
고갈될 수 있으므로, 헬스체크/메트릭 등의 단발성 호출은 이 모듈의 싱글톤
클라이언트를 재사용한다.

주의:
    Celery 의 broker/backend 는 Celery 가 자체 커넥션을 관리하므로 여기서
    다루지 않는다. (celery_app.py 의 설정은 그대로 유지)
"""

from __future__ import annotations

import os
import threading
from typing import Optional

try:
    import redis  # type: ignore
except ImportError:  # redis 미설치 환경(테스트 등) 허용
    redis = None  # type: ignore

_lock = threading.Lock()
_client: Optional["redis.Redis"] = None  # type: ignore[name-defined]


def get_redis_url() -> str | None:
    """REDIS_URL 또는 Celery broker URL 에서 해석."""
    return os.environ.get("REDIS_URL") or os.environ.get("CELERY_BROKER_URL") or None


def get_redis() -> "redis.Redis | None":
    """프로세스 수명 동안 단일 Redis 클라이언트 반환. 미설정/미설치면 None."""
    global _client
    if _client is not None:
        return _client
    if redis is None:
        return None
    url = get_redis_url()
    if not url:
        return None
    with _lock:
        if _client is None:
            _client = redis.from_url(
                url,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
                decode_responses=True,
            )
    return _client


def close_redis() -> None:
    """프로세스 종료 시 호출 (옵션). 테스트에서 재생성 원할 때도 사용."""
    global _client
    with _lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:  # noqa: BLE001
                pass
            _client = None
