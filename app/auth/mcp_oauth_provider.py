"""MCP SDK OAuth Authorization Server Provider.

기존 User/ApiKey DB 모델과 연동하여 MCP 클라이언트(Cursor 등)가
브라우저 기반 OAuth 로그인 플로우를 사용할 수 있게 한다.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone

from pydantic import AnyUrl
from sqlalchemy import select

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from app.db.auth_models import ApiKey, User
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)

# ── In-memory stores (auth codes, clients, refresh tokens) ───────────
# Authorization codes are short-lived (5분), in-memory로 충분
_auth_codes: dict[str, AuthorizationCode] = {}
_clients: dict[str, OAuthClientInformationFull] = {}
_refresh_tokens: dict[str, dict] = {}  # token -> {user_id, client_id, scopes, expires_at}

# MCP 도구 접속용 단일 스코프
MCP_SCOPES = ["mcp:tools"]

# Token lifetimes
ACCESS_TOKEN_EXPIRY = 3600  # 1시간
REFRESH_TOKEN_EXPIRY = 86400 * 30  # 30일
AUTH_CODE_EXPIRY = 300  # 5분


def _generate_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


class McperOAuthProvider:
    """MCPER OAuth Authorization Server Provider for MCP SDK."""

    def __init__(self, login_url: str = "/auth/mcp-authorize"):
        self._login_url = login_url

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return _clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        _clients[client_info.client_id] = client_info

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """브라우저 로그인 페이지로 리다이렉트. 로그인 성공 시 콜백으로 auth code 전달."""
        # state에 필요한 정보를 저장하고 로그인 페이지로 보냄
        # pending auth request를 임시 저장
        request_id = secrets.token_urlsafe(16)
        _pending_auth_requests[request_id] = {
            "client": client,
            "params": params,
            "created_at": time.time(),
        }
        # 로그인 페이지로 리다이렉트 (request_id를 전달)
        return f"{self._login_url}?request_id={request_id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code_data = _auth_codes.get(authorization_code)
        if code_data is None:
            return None
        if code_data.expires_at < time.time():
            _auth_codes.pop(authorization_code, None)
            return None
        if code_data.client_id != client.client_id:
            return None
        return code_data

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Authorization code를 access/refresh token으로 교환."""
        # Code 사용 후 삭제 (일회성)
        _auth_codes.pop(authorization_code.code, None)

        # user_id는 code에 연결되어 있음
        user_id = _code_user_map.pop(authorization_code.code, None)

        now = int(time.time())
        access_token = _generate_token("mcp_at_")
        refresh_token = _generate_token("mcp_rt_")

        # Access token → DB에 ApiKey로 저장 (기존 MCP 게이트 호환)
        if user_id:
            _store_mcp_access_token(user_id, access_token, client.client_id)

        # Refresh token → in-memory
        _refresh_tokens[refresh_token] = {
            "user_id": user_id,
            "client_id": client.client_id,
            "scopes": authorization_code.scopes,
            "expires_at": now + REFRESH_TOKEN_EXPIRY,
        }

        # In-memory access token tracking (for load_access_token)
        _access_tokens[access_token] = {
            "user_id": user_id,
            "client_id": client.client_id,
            "scopes": authorization_code.scopes,
            "expires_at": now + ACCESS_TOKEN_EXPIRY,
        }

        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRY,
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh_token,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        data = _refresh_tokens.get(refresh_token)
        if data is None:
            return None
        if data.get("expires_at", 0) < time.time():
            _refresh_tokens.pop(refresh_token, None)
            return None
        if data["client_id"] != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=data["client_id"],
            scopes=data["scopes"],
            expires_at=data.get("expires_at"),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Refresh token으로 새 access/refresh token 발급."""
        old_data = _refresh_tokens.pop(refresh_token.token, None)
        user_id = old_data["user_id"] if old_data else None

        now = int(time.time())
        new_access = _generate_token("mcp_at_")
        new_refresh = _generate_token("mcp_rt_")

        effective_scopes = scopes if scopes else refresh_token.scopes

        if user_id:
            _store_mcp_access_token(user_id, new_access, client.client_id)

        _refresh_tokens[new_refresh] = {
            "user_id": user_id,
            "client_id": client.client_id,
            "scopes": effective_scopes,
            "expires_at": now + REFRESH_TOKEN_EXPIRY,
        }
        _access_tokens[new_access] = {
            "user_id": user_id,
            "client_id": client.client_id,
            "scopes": effective_scopes,
            "expires_at": now + ACCESS_TOKEN_EXPIRY,
        }

        return OAuthToken(
            access_token=new_access,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRY,
            scope=" ".join(effective_scopes),
            refresh_token=new_refresh,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Bearer 토큰 검증. in-memory + DB ApiKey 양쪽 지원."""
        token_hint = token[:12] if len(token) > 12 else token

        # 1) in-memory (OAuth flow로 발급된 토큰)
        data = _access_tokens.get(token)
        if data:
            if data.get("expires_at", 0) < time.time():
                _access_tokens.pop(token, None)
                logger.warning("load_access_token: in-memory token expired (%s...)", token_hint)
                return None
            return AccessToken(
                token=token,
                client_id=data["client_id"],
                scopes=data["scopes"],
                expires_at=data.get("expires_at"),
            )

        # 2) DB ApiKey (수동 발급 API 키 + OAuth로 발급 후 DB에 저장된 토큰)
        db = SessionLocal()
        try:
            key_hash = hashlib.sha256(token.encode()).hexdigest()
            api_key = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
            if api_key is None:
                logger.warning(
                    "load_access_token: token not found in memory (%d entries) or DB (%s...)",
                    len(_access_tokens), token_hint,
                )
                return None
            if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
                logger.warning("load_access_token: DB token expired (%s...)", token_hint)
                return None
            api_key.last_used_at = datetime.now(timezone.utc)
            db.commit()
            return AccessToken(
                token=token,
                client_id="api_key",
                scopes=MCP_SCOPES,
                expires_at=None,
            )
        except Exception:
            logger.exception("load_access_token: DB lookup failed (%s...)", token_hint)
            return None
        finally:
            db.close()

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            _access_tokens.pop(token.token, None)
            db = SessionLocal()
            try:
                key_hash = hashlib.sha256(token.token.encode()).hexdigest()
                api_key = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
                if api_key:
                    db.delete(api_key)
                    db.commit()
            except Exception:
                logger.exception("revoke_token: DB cleanup failed")
            finally:
                db.close()
        elif isinstance(token, RefreshToken):
            _refresh_tokens.pop(token.token, None)


# ── Helper stores ────────────────────────────────────────────────────
_pending_auth_requests: dict[str, dict] = {}
_code_user_map: dict[str, int] = {}  # auth_code -> user_id
_access_tokens: dict[str, dict] = {}


def _store_mcp_access_token(user_id: int, token: str, client_id: str) -> None:
    """OAuth로 발급된 access token을 DB ApiKey에도 저장 (기존 게이트 호환)."""
    db = SessionLocal()
    try:
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.fromtimestamp(
            time.time() + ACCESS_TOKEN_EXPIRY, tz=timezone.utc
        )
        db.add(ApiKey(
            user_id=user_id,
            key_hash=key_hash,
            name=f"mcp-oauth-{client_id[:16]}",
            expires_at=expires_at,
        ))
        db.commit()
    finally:
        db.close()


def complete_authorization(request_id: str, user_id: int) -> str | None:
    """로그인 성공 후 호출. Authorization code를 생성하고 redirect URI를 반환한다."""
    pending = _pending_auth_requests.pop(request_id, None)
    if pending is None:
        return None
    if time.time() - pending["created_at"] > AUTH_CODE_EXPIRY:
        return None

    params: AuthorizationParams = pending["params"]
    client: OAuthClientInformationFull = pending["client"]

    code = _generate_token("mcp_code_")
    auth_code = AuthorizationCode(
        code=code,
        scopes=params.scopes or MCP_SCOPES,
        expires_at=time.time() + AUTH_CODE_EXPIRY,
        client_id=client.client_id,
        code_challenge=params.code_challenge,
        redirect_uri=params.redirect_uri,
        redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
        resource=params.resource,
    )
    _auth_codes[code] = auth_code
    _code_user_map[code] = user_id

    # 클라이언트의 redirect_uri로 code와 state를 전달
    redirect_url = construct_redirect_uri(
        str(params.redirect_uri),
        code=code,
        state=params.state,
    )
    return redirect_url
