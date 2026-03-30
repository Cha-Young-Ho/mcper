"""CSRF 토큰 생성 및 검증 미들웨어."""

from __future__ import annotations

import logging
import secrets
from typing import Callable

from fastapi import HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

CSRF_TOKEN_LENGTH = 32
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_FORM_NAME = "csrf_token"


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF 토큰 생성 및 검증.
    - GET: 토큰 생성 후 응답에 포함 (쿠키)
    - POST/PUT/DELETE: 토큰 검증 (header 또는 form)
    """

    def __init__(self, app, secret_key: str):
        super().__init__(app)
        self.secret_key = secret_key

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # CSRF 토큰 생성/검증 (MCP, WebSocket, health, API Bearer 인증 제외)
        if request.url.path.startswith("/mcp") or request.url.path == "/ws":
            return await call_next(request)
        if request.url.path.startswith("/health"):
            return await call_next(request)
        # Bearer 토큰 인증 요청은 CSRF 검증 제외 (API 클라이언트)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return await call_next(request)

        # GET/HEAD/OPTIONS: 토큰 생성
        if request.method in SAFE_METHODS:
            response = await call_next(request)
            # 응답에 CSRF 토큰 쿠키 추가
            token = secrets.token_hex(CSRF_TOKEN_LENGTH // 2)
            response.set_cookie(
                "csrf_token",
                value=token,
                httponly=False,  # JS에서 X-CSRF-Token 헤더로 읽을 수 있게
                secure=True,
                samesite="lax",
                max_age=86400,  # 24시간
            )
            return response

        # POST/PUT/DELETE/PATCH: 토큰 검증
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            # 토큰 추출 (header 우선, 그 다음 form)
            token_from_header = request.headers.get(CSRF_HEADER_NAME, "").strip()

            token_from_form = None
            if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
                try:
                    form = await request.form()
                    token_from_form = form.get(CSRF_FORM_NAME, "").strip()
                except Exception:
                    pass

            token_from_request = token_from_header or token_from_form

            # 쿠키에서 토큰 추출
            token_from_cookie = request.cookies.get("csrf_token", "").strip()

            # 검증
            if not token_from_cookie or not token_from_request:
                logger.warning(f"CSRF token missing: method={request.method}, path={request.url.path}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="CSRF token missing or invalid",
                )

            if not secrets.compare_digest(token_from_cookie, token_from_request):
                logger.warning(f"CSRF token mismatch: method={request.method}, path={request.url.path}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="CSRF token validation failed",
                )

        return await call_next(request)
