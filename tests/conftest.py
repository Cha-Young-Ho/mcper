"""Shared pytest fixtures for authentication and security tests."""

import os
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

# Import auth utilities
from app.auth.service import (
    hash_password,
    create_access_token,
    hash_api_key,
)
from app.db.auth_models import User, ApiKey
from app.db.database import Base, SessionLocal, engine
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create test database tables."""
    Base.metadata.create_all(bind=engine)
    yield
    # Optionally cleanup after all tests
    # Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    """Provide a clean database session for each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def test_client():
    """Provide FastAPI test client with auto CSRF token injection for unsafe methods.

    Uses https://testserver so that Secure-flagged CSRF cookies set by CSRFMiddleware
    are correctly sent back on subsequent requests."""
    return _CSRFClient(app)


class _CSRFClient:
    """Thin wrapper around TestClient that auto-attaches X-CSRF-Token header for
    unsafe methods. Backed by a live TestClient so cookies persist across requests.

    Uses https://testserver so that Secure-flagged cookies set by CSRFMiddleware
    are actually sent back on subsequent requests (TestClient defaults to http)."""

    def __init__(self, app_):
        self._client = TestClient(app_, base_url="https://testserver")
        # Prime the csrf_token cookie (GET / triggers CSRFMiddleware's safe-path branch)
        self._client.get("/")
        self._token = self._client.cookies.get("csrf_token", "")

    def _with_csrf_headers(self, method, kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        # Do NOT inject automatic CSRF header when the caller is manually setting
        # its own cookies (likely testing CSRF behavior directly).
        caller_sets_cookies = "cookies" in kwargs
        already_has_header = any(k.lower() == "x-csrf-token" for k in headers)
        if (
            self._token
            and method.upper() not in {"GET", "HEAD", "OPTIONS"}
            and not caller_sets_cookies
            and not already_has_header
        ):
            headers["X-CSRF-Token"] = self._token
        kwargs["headers"] = headers
        return kwargs

    def get(self, url, **kwargs):
        return self._client.get(url, **self._with_csrf_headers("GET", kwargs))

    def post(self, url, **kwargs):
        return self._client.post(url, **self._with_csrf_headers("POST", kwargs))

    def put(self, url, **kwargs):
        return self._client.put(url, **self._with_csrf_headers("PUT", kwargs))

    def delete(self, url, **kwargs):
        return self._client.delete(url, **self._with_csrf_headers("DELETE", kwargs))

    def patch(self, url, **kwargs):
        return self._client.patch(url, **self._with_csrf_headers("PATCH", kwargs))

    def options(self, url, **kwargs):
        return self._client.options(url, **self._with_csrf_headers("OPTIONS", kwargs))

    def head(self, url, **kwargs):
        return self._client.head(url, **self._with_csrf_headers("HEAD", kwargs))

    @property
    def cookies(self):
        return self._client.cookies


@pytest.fixture
def csrf_client():
    """TestClient wrapper that automatically attaches X-CSRF-Token for unsafe requests."""
    return _CSRFClient(app)


def _auth_routes_registered() -> bool:
    """True if /auth/* routes are mounted (MCPER_AUTH_ENABLED=true at import time)."""
    return any(getattr(r, "path", "").startswith("/auth/login") for r in app.routes)


# Exposed for pytest.mark.skipif in test modules
auth_disabled_skip = pytest.mark.skipif(
    not _auth_routes_registered(),
    reason="Auth routes only registered when MCPER_AUTH_ENABLED=true at import time",
)


@pytest.fixture
def admin_user(db_session: Session) -> User:
    """Create a test admin user with password already changed."""
    user = User(
        username="admin_test",
        email="admin@test.local",
        hashed_password=hash_password("Admin@12345"),
        is_admin=True,
        is_active=True,
        password_changed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin_user_default_password(db_session: Session) -> User:
    """Create a test admin user with default password (NOT changed)."""
    user = User(
        username="admin_default",
        email="admin_default@test.local",
        hashed_password=hash_password("changeme"),
        is_admin=True,
        is_active=True,
        password_changed_at=None,  # Not changed
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def regular_user(db_session: Session) -> User:
    """Create a test regular (non-admin) user."""
    user = User(
        username="user_test",
        email="user@test.local",
        hashed_password=hash_password("User@12345"),
        is_admin=False,
        is_active=True,
        password_changed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def valid_jwt_token(admin_user: User) -> str:
    """Create a valid JWT token for admin user."""
    return create_access_token(
        data={"sub": str(admin_user.id), "type": "access"},
        expires_delta=timedelta(minutes=15)
    )


@pytest.fixture
def expired_jwt_token(admin_user: User) -> str:
    """Create an expired JWT token."""
    return create_access_token(
        data={"sub": str(admin_user.id), "type": "access"},
        expires_delta=timedelta(hours=-1)  # Expired 1 hour ago
    )


@pytest.fixture
def refresh_token_valid(admin_user: User) -> str:
    """Create a valid refresh token."""
    return create_access_token(
        data={"sub": str(admin_user.id), "type": "refresh"},
        expires_delta=timedelta(days=7)
    )


@pytest.fixture
def refresh_token_expired(admin_user: User) -> str:
    """Create an expired refresh token."""
    return create_access_token(
        data={"sub": str(admin_user.id), "type": "refresh"},
        expires_delta=timedelta(days=-1)  # Expired 1 day ago
    )


@pytest.fixture
def api_key_valid(db_session: Session, admin_user: User) -> tuple[str, ApiKey]:
    """Create a valid API key and return (raw_key, api_key_obj)."""
    raw_key = "test_api_key_" + os.urandom(16).hex()
    key_hash = hash_api_key(raw_key)

    api_key = ApiKey(
        user_id=admin_user.id,
        key_hash=key_hash,
        name="test_key",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(api_key)
    db_session.commit()
    db_session.refresh(api_key)

    return raw_key, api_key


@pytest.fixture
def api_key_expired(db_session: Session, admin_user: User) -> tuple[str, ApiKey]:
    """Create an expired API key and return (raw_key, api_key_obj)."""
    raw_key = "expired_api_key_" + os.urandom(16).hex()
    key_hash = hash_api_key(raw_key)

    api_key = ApiKey(
        user_id=admin_user.id,
        key_hash=key_hash,
        name="expired_key",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # Expired
    )
    db_session.add(api_key)
    db_session.commit()
    db_session.refresh(api_key)

    return raw_key, api_key


@pytest.fixture
def csrf_token():
    """Create a dummy CSRF token."""
    import secrets
    return secrets.token_hex(16)


@pytest.fixture
def mock_datetime():
    """Mock datetime for testing token expiry scenarios."""
    with patch("app.auth.service.datetime") as mock_dt:
        # Set a fixed "now" time
        fixed_time = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = fixed_time
        mock_dt.fromtimestamp.side_effect = datetime.fromtimestamp
        yield mock_dt
