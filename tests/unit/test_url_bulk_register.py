"""Tests for POST /admin/documents/urls — current endpoint signature.

엔드포인트는 JSON body (urls: list[str]) 를 받고 require_admin_user 로 보호된다.
CSRFMiddleware 가 적용되므로 csrf_client fixture 를 사용한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.main import app


class TestBulkRegisterUrlsAuth:
    def test_post_without_csrf_is_blocked(self):
        """CSRFMiddleware must block POST without the token (403 JSON)."""
        from fastapi.testclient import TestClient
        client = TestClient(app, base_url="https://testserver")
        response = client.post("/admin/documents/urls", json=["https://example.com"])
        assert response.status_code == 403
        assert "CSRF" in response.json().get("detail", "")

    def test_post_without_auth_but_with_csrf_is_unauthorized(self, csrf_client):
        """With CSRF satisfied but no admin session, auth dependency returns 401/403/redirect."""
        response = csrf_client.post(
            "/admin/documents/urls",
            json=["https://example.com"],
        )
        assert response.status_code in (401, 403, 302, 307)


class TestBulkRegisterUrlsSuccess:
    def test_admin_can_register_urls(self, csrf_client):
        """With admin override + CSRF, endpoint processes URLs."""
        from app.auth.dependencies import require_admin_user
        app.dependency_overrides[require_admin_user] = lambda: "admin"

        try:
            with patch(
                "app.routers.admin_specs.fetch_url_as_text",
                new_callable=AsyncMock,
                return_value="document body",
            ), patch(
                "app.routers.admin_specs.enqueue_or_index_sync",
                return_value={"indexed": True, "chunks": 1},
            ):
                response = csrf_client.post(
                    "/admin/documents/urls",
                    json=["https://example.com/doc1"],
                )
        finally:
            app.dependency_overrides.pop(require_admin_user, None)

        assert response.status_code == 200

    def test_empty_url_skipped(self, csrf_client):
        from app.auth.dependencies import require_admin_user
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        try:
            response = csrf_client.post(
                "/admin/documents/urls",
                json=["", "   "],
            )
        finally:
            app.dependency_overrides.pop(require_admin_user, None)

        assert response.status_code == 200
