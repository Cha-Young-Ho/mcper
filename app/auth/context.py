"""Thread-safe user context for MCP tools via contextvars.

설정 경로 (L11 감사 결과):
  - MCP HTTP 요청: ``app/asgi/mcp_host_gate.py`` 의 ``McpHostGateASGI`` 가
    Bearer 토큰 검증 후 ``current_user_var.set(user)`` 를 호출하며,
    요청 종료 시 ``finally`` 블록에서 ``reset`` 하여 누수를 방지한다.
    (user 는 인증 비활성/익명 시 None 일 수 있음)
  - FastAPI 일반 라우터: ``app.auth.dependencies.get_current_user_optional``
    등 Depends 의존성을 통해 주입하며, MCP contextvar 와 별개.

사용 규칙:
  - MCP 도구는 ``get_current_user()`` 를 호출해 None-이면 익명으로 처리하거나
    ``require_current_user()`` 로 명시적 실패를 유도한다.
  - 신규 코드에서 "설정되지 않은 것처럼 보이는" 상황을 디버깅할 때는
    ``debug_current_user_state()`` 를 호출해 DEBUG 로그로 추적한다.
"""

from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CurrentUser:
    """Immutable snapshot of the authenticated user."""

    user_id: int
    username: str
    is_admin: bool


current_user_var: contextvars.ContextVar[CurrentUser | None] = contextvars.ContextVar(
    "current_user", default=None
)


def get_current_user() -> CurrentUser | None:
    """Return the current user, or None if auth is disabled / unauthenticated."""
    return current_user_var.get()


def require_current_user() -> CurrentUser:
    """Return the current user, or raise PermissionError."""
    user = current_user_var.get()
    if user is None:
        raise PermissionError("Authentication required")
    return user


def debug_current_user_state() -> CurrentUser | None:
    """디버그용: current_user_var 의 상태를 DEBUG 로그로 남기고 값을 반환.

    기존 ``None`` 기반 분기를 그대로 유지하면서, MCP 게이트를 거치지 않은
    호출 경로(예: 내부 스크립트/워커 컨텍스트)에서 contextvar 누락을
    식별하기 위한 보조 함수. 비즈니스 로직에서 사용하지 말 것.
    """
    user = current_user_var.get()
    if user is None:
        logger.debug(
            "current_user_var accessed but not set; "
            "check MCP gate (mcp_host_gate.py) or auth dependency wiring."
        )
    return user
