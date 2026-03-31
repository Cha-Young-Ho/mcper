"""Unit tests for CSRFMiddleware internals and constants."""

from __future__ import annotations

from app.asgi.csrf_middleware import (
    CSRF_FORM_NAME,
    CSRF_HEADER_NAME,
    CSRF_TOKEN_LENGTH,
    SAFE_METHODS,
)


class TestCSRFConstants:
    def test_safe_methods(self):
        assert "GET" in SAFE_METHODS
        assert "HEAD" in SAFE_METHODS
        assert "OPTIONS" in SAFE_METHODS
        assert "POST" not in SAFE_METHODS

    def test_token_length(self):
        assert CSRF_TOKEN_LENGTH == 32

    def test_header_name(self):
        assert CSRF_HEADER_NAME == "x-csrf-token"

    def test_form_name(self):
        assert CSRF_FORM_NAME == "csrf_token"
