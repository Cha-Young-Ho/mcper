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
    """Provide FastAPI test client."""
    return TestClient(app)


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
