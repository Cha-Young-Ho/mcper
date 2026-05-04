"""JWT 발급/검증 + 패스워드 해싱."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from app.config import settings

# `jose.JWTError` 호환: 기존 코드/테스트에서 `from app.auth.service import JWTError`
# 를 쓸 수 있도록 PyJWT 의 `InvalidTokenError` 를 동일 이름으로 재노출한다.
JWTError = InvalidTokenError


# bcrypt 는 입력을 최대 72 bytes 로 제한한다. bcrypt 5.x 는 초과 시 ValueError.
# 4.x 는 조용히 잘랐음. 동작 일관성을 위해 우리가 명시적으로 잘라서 넘긴다.
# (보안 영향 없음 — 72 bytes 초과분은 bcrypt 가 어차피 사용하지 못함)
_BCRYPT_MAX_BYTES = 72


def _truncate_bcrypt(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate_bcrypt(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate_bcrypt(plain), hashed.encode("utf-8"))
    except Exception:
        return False


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.auth.token_expire_minutes)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.auth.secret_key, algorithm="HS256")


def decode_token(token: str, allow_expired: bool = False) -> dict:
    """
    JWT 검증. 만료 시 기본적으로 InvalidTokenError(=JWTError) 발생.
    allow_expired=True → 만료된 토큰도 payload 반환 (refresh 토큰 갱신용).
    """
    try:
        return jwt.decode(
            token,
            settings.auth.secret_key,
            algorithms=["HS256"],
            options={"verify_exp": not allow_expired},
        )
    except ExpiredSignatureError:
        if allow_expired:
            # 만료된 토큰의 payload 반환 (refresh 토큰에서 유저ID 추출용)
            return jwt.decode(
                token,
                settings.auth.secret_key,
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
        raise
    except InvalidTokenError as e:
        raise InvalidTokenError("Token validation failed") from e


def verify_token_not_expired(token: str) -> bool:
    """토큰 만료 여부만 확인. True = 유효."""
    try:
        jwt.decode(
            token,
            settings.auth.secret_key,
            algorithms=["HS256"],
        )
        return True
    except Exception:
        return False


def validate_password(password: str) -> str | None:
    """
    패스워드 정책 검증.
    - 12자 이상
    - 특수문자 1개 이상 포함
    Returns: 오류 메시지 (None이면 통과).
    """
    if len(password) < 12:
        return "Password must be at least 12 characters"
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>/?`~]', password):
        return "Password must contain at least one special character"
    return None
