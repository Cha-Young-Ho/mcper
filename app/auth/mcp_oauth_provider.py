"""MCP SDK OAuth Authorization Server Provider.

기존 User/ApiKey DB 모델과 연동하여 MCP 클라이언트(Cursor 등)가
브라우저 기반 OAuth 로그인 플로우를 사용할 수 있게 한다.

세션 데이터(코드/클라이언트/토큰/pending)는 ``app.auth.session_store.SessionStore``
로 추상화되어 있으며, 기본 InMemory / 옵션 Redis(``MCPER_SESSION_STORE=redis``)
를 지원한다.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone

from pydantic import AnyUrl  # noqa: F401 — 외부 import 경로 하위 호환
from sqlalchemy import select

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from app.auth.session_store import (
    DEFAULT_CLIENT_TTL,
    get_session_store,
)
from app.db.auth_models import ApiKey
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)

# MCP 도구 접속용 단일 스코프
MCP_SCOPES = ["mcp:tools"]

# Token lifetimes
ACCESS_TOKEN_EXPIRY = 3600  # 1시간
REFRESH_TOKEN_EXPIRY = 86400 * 30  # 30일
AUTH_CODE_EXPIRY = 300  # 5분

# DCR 으로 등록된 client 를 유지할 기간 (설계 문서: 30d)
CLIENT_TTL = DEFAULT_CLIENT_TTL

# pending_auth_requests 의 TTL 은 AUTH_CODE_EXPIRY 와 동일
PENDING_AUTH_TTL = AUTH_CODE_EXPIRY


def _generate_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


# ── Pydantic ↔ dict 변환 helpers ─────────────────────────────────────
# SessionStore 는 JSON-serializable dict 만 다룬다. 값으로 들어오는
# pydantic 모델은 여기서 dump/validate 한다.


def _dump_auth_code(ac: AuthorizationCode) -> dict:
    return ac.model_dump(mode="json")


def _load_auth_code(data: dict) -> AuthorizationCode:
    return AuthorizationCode.model_validate(data)


def _dump_client(c: OAuthClientInformationFull) -> dict:
    return c.model_dump(mode="json")


def _load_client(data: dict) -> OAuthClientInformationFull:
    return OAuthClientInformationFull.model_validate(data)


def _dump_auth_params(p: AuthorizationParams) -> dict:
    return p.model_dump(mode="json")


def _load_auth_params(data: dict) -> AuthorizationParams:
    return AuthorizationParams.model_validate(data)


class McperOAuthProvider:
    """MCPER OAuth Authorization Server Provider for MCP SDK."""

    def __init__(self, login_url: str = "/auth/mcp-authorize"):
        self._login_url = login_url

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = get_session_store().get_client(client_id)
        if data is None:
            return None
        try:
            return _load_client(data)
        except Exception:
            logger.exception("get_client: invalid client payload for %s", client_id)
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        get_session_store().save_client(
            client_info.client_id,
            _dump_client(client_info),
            ttl=CLIENT_TTL,
        )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """브라우저 로그인 페이지로 리다이렉트. 로그인 성공 시 콜백으로 auth code 전달."""
        # state에 필요한 정보를 저장하고 로그인 페이지로 보냄
        # pending auth request를 임시 저장 (JSON 직렬화 가능한 형태로)
        request_id = secrets.token_urlsafe(16)
        get_session_store().save_pending_auth(
            request_id,
            {
                "client": _dump_client(client),
                "params": _dump_auth_params(params),
                "created_at": time.time(),
            },
            ttl=PENDING_AUTH_TTL,
        )
        # 로그인 페이지로 리다이렉트 (request_id를 전달)
        return f"{self._login_url}?request_id={request_id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        store = get_session_store()
        data = store.get_auth_code(authorization_code)
        if data is None:
            return None
        try:
            code_data = _load_auth_code(data)
        except Exception:
            logger.exception("load_authorization_code: invalid payload")
            return None
        if code_data.expires_at < time.time():
            store.pop_auth_code(authorization_code)
            return None
        if code_data.client_id != client.client_id:
            return None
        return code_data

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Authorization code를 access/refresh token으로 교환."""
        store = get_session_store()
        # Code 사용 후 삭제 (일회성)
        store.pop_auth_code(authorization_code.code)

        # user_id는 code에 연결되어 있음
        user_id_str = store.pop_code_user(authorization_code.code)
        user_id: int | None = int(user_id_str) if user_id_str is not None else None

        now = int(time.time())
        access_token = _generate_token("mcp_at_")
        refresh_token = _generate_token("mcp_rt_")

        # Access token → DB에 ApiKey로 저장 (기존 MCP 게이트 호환)
        if user_id:
            _store_mcp_access_token(user_id, access_token, client.client_id)

        # Refresh token
        store.save_refresh_token(
            refresh_token,
            {
                "user_id": user_id,
                "client_id": client.client_id,
                "scopes": list(authorization_code.scopes),
                "expires_at": now + REFRESH_TOKEN_EXPIRY,
            },
            ttl=REFRESH_TOKEN_EXPIRY,
        )

        # Access token tracking (for load_access_token)
        store.save_access_token(
            access_token,
            {
                "user_id": user_id,
                "client_id": client.client_id,
                "scopes": list(authorization_code.scopes),
                "expires_at": now + ACCESS_TOKEN_EXPIRY,
            },
            ttl=ACCESS_TOKEN_EXPIRY,
        )

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
        store = get_session_store()
        data = store.get_refresh_token(refresh_token)
        if data is None:
            return None
        if data.get("expires_at", 0) < time.time():
            store.pop_refresh_token(refresh_token)
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
        store = get_session_store()
        old_data = store.pop_refresh_token(refresh_token.token)
        user_id = old_data["user_id"] if old_data else None

        now = int(time.time())
        new_access = _generate_token("mcp_at_")
        new_refresh = _generate_token("mcp_rt_")

        effective_scopes = scopes if scopes else refresh_token.scopes

        if user_id:
            _store_mcp_access_token(user_id, new_access, client.client_id)

        store.save_refresh_token(
            new_refresh,
            {
                "user_id": user_id,
                "client_id": client.client_id,
                "scopes": list(effective_scopes),
                "expires_at": now + REFRESH_TOKEN_EXPIRY,
            },
            ttl=REFRESH_TOKEN_EXPIRY,
        )
        store.save_access_token(
            new_access,
            {
                "user_id": user_id,
                "client_id": client.client_id,
                "scopes": list(effective_scopes),
                "expires_at": now + ACCESS_TOKEN_EXPIRY,
            },
            ttl=ACCESS_TOKEN_EXPIRY,
        )

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
        store = get_session_store()

        # 1) SessionStore (OAuth flow로 발급된 토큰)
        data = store.get_access_token(token)
        if data:
            if data.get("expires_at", 0) < time.time():
                store.delete_access_token(token)
                logger.warning(
                    "load_access_token: store token expired (%s...)", token_hint
                )
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
                    "load_access_token: token not found in store (~%d entries) or DB (%s...)",
                    store.access_token_count(),
                    token_hint,
                )
                return None
            if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
                logger.warning(
                    "load_access_token: DB token expired (%s...)", token_hint
                )
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
        store = get_session_store()
        if isinstance(token, AccessToken):
            store.delete_access_token(token.token)
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
            store.pop_refresh_token(token.token)


def _store_mcp_access_token(user_id: int, token: str, client_id: str) -> None:
    """OAuth로 발급된 access token을 DB ApiKey에도 저장 (기존 게이트 호환)."""
    db = SessionLocal()
    try:
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.fromtimestamp(
            time.time() + ACCESS_TOKEN_EXPIRY, tz=timezone.utc
        )
        db.add(
            ApiKey(
                user_id=user_id,
                key_hash=key_hash,
                name=f"mcp-oauth-{client_id[:16]}",
                expires_at=expires_at,
            )
        )
        db.commit()
    finally:
        db.close()


def complete_authorization(request_id: str, user_id: int) -> str | None:
    """로그인 성공 후 호출. Authorization code를 생성하고 redirect URI를 반환한다."""
    store = get_session_store()
    pending = store.pop_pending_auth(request_id)
    if pending is None:
        return None
    if time.time() - float(pending["created_at"]) > AUTH_CODE_EXPIRY:
        return None

    try:
        params: AuthorizationParams = _load_auth_params(pending["params"])
        client: OAuthClientInformationFull = _load_client(pending["client"])
    except Exception:
        logger.exception("complete_authorization: invalid pending payload")
        return None

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
    store.save_auth_code(code, _dump_auth_code(auth_code), ttl=AUTH_CODE_EXPIRY)
    store.save_code_user(code, str(user_id), ttl=AUTH_CODE_EXPIRY)

    # 클라이언트의 redirect_uri로 code와 state를 전달
    redirect_url = construct_redirect_uri(
        str(params.redirect_uri),
        code=code,
        state=params.state,
    )
    return redirect_url
