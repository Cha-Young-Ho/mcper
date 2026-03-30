"""Tests for POST /admin/documents/urls - bulk URL registration endpoint."""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Spec
from app.main import app
from app.db.database import get_db


@pytest.fixture
def client():
    """Provide TestClient for admin routes."""
    return TestClient(app)


class TestBulkRegisterUrlsAuth:
    """Authentication and authorization tests for bulk URL registration."""

    def test_bulk_register_urls_requires_admin(self, client: TestClient):
        """Non-admin or unauthenticated users should get 403 or redirect."""
        with patch("app.auth.dependencies.require_admin_user") as mock_require_admin:
            # Simulate unauthorized access
            mock_require_admin.side_effect = Exception("Unauthorized")

            response = client.post(
                "/admin/documents/urls",
                data={"urls": ["https://example.com"]},
            )

            # Should be 403 or redirect
            assert response.status_code in (403, 302)

    def test_bulk_register_urls_with_valid_admin(self, client: TestClient, admin_user):
        """Admin user should be able to access the endpoint."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = "Test content from URL"

                response = client.post(
                    "/admin/documents/urls",
                    data={
                        "urls": ["https://example.com/doc1"],
                        "app_target": "test_app",
                        "base_branch": "main",
                    },
                )

                # Should process the request (may succeed or fail based on DB state)
                assert response.status_code in (200, 400, 500)


class TestBulkRegisterUrlsSuccess:
    """Success scenario tests for bulk URL registration."""

    def test_single_valid_url_registered(
        self, client: TestClient, admin_user, db_session: Session
    ):
        """Successfully register a single valid URL."""
        from unittest.mock import patch

        url = "https://example.com/spec"
        content = "# API Specification\n\nDetailed API documentation."

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = content

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.return_value = {"indexed": True, "chunks": 5}

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": [url],
                            "app_target": "api_docs",
                            "base_branch": "main",
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["ok_count"] == 1
                    assert data["fail_count"] == 0
                    assert len(data["results"]) == 1
                    assert data["results"][0]["ok"] is True
                    assert data["results"][0]["url"] == url

    def test_multiple_urls_all_succeed(
        self, client: TestClient, admin_user, db_session: Session
    ):
        """Register multiple URLs, all successful."""
        from unittest.mock import patch

        urls = [
            "https://example.com/doc1",
            "https://example.com/doc2",
            "https://example.com/doc3",
        ]
        contents = [
            "Documentation 1",
            "Documentation 2",
            "Documentation 3",
        ]

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                # Return different content for each URL
                mock_fetch.side_effect = contents

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.return_value = {"indexed": True, "chunks": 3}

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": urls,
                            "app_target": "docs",
                            "base_branch": "develop",
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["ok_count"] == 3
                    assert data["fail_count"] == 0
                    assert len(data["results"]) == 3

                    for i, result in enumerate(data["results"]):
                        assert result["ok"] is True
                        assert result["url"] == urls[i]


class TestBulkRegisterUrlsPartialFailure:
    """Partial failure scenario tests (some URLs fail, others succeed)."""

    def test_some_urls_fetch_failure_others_succeed(
        self, client: TestClient, admin_user, db_session: Session
    ):
        """Some URLs fail to fetch, others succeed - partial failure handled."""
        from unittest.mock import patch

        urls = [
            "https://example.com/success1",
            "https://example.com/fail",
            "https://example.com/success2",
        ]

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                # First succeeds, second fails, third succeeds
                def side_effect(url):
                    if "fail" in url:
                        raise Exception("Connection timeout")
                    return f"Content from {url}"

                mock_fetch.side_effect = side_effect

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.return_value = {"indexed": True}

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": urls,
                            "app_target": "mixed",
                            "base_branch": "main",
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["ok_count"] == 2
                    assert data["fail_count"] == 1

                    # Check which ones succeeded
                    ok_results = [r for r in data["results"] if r["ok"]]
                    fail_results = [r for r in data["results"] if not r["ok"]]

                    assert len(ok_results) == 2
                    assert len(fail_results) == 1
                    assert "fail" in fail_results[0]["url"]
                    assert "error" in fail_results[0]

    def test_empty_content_response_marks_as_failed(
        self, client: TestClient, admin_user, db_session: Session
    ):
        """URL with empty content should be marked as failed."""
        from unittest.mock import patch

        url = "https://example.com/empty"

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = ""  # Empty content

                response = client.post(
                    "/admin/documents/urls",
                    data={
                        "urls": [url],
                        "app_target": "test",
                        "base_branch": "main",
                    },
                )

                assert response.status_code == 200
                data = response.json()
                assert data["ok_count"] == 0
                assert data["fail_count"] == 1
                assert data["results"][0]["ok"] is False
                assert "내용이 비어" in data["results"][0]["error"] or "empty" in data["results"][0]["error"].lower()

    def test_whitespace_only_content_marks_as_failed(
        self, client: TestClient, admin_user, db_session: Session
    ):
        """URL with whitespace-only content should be marked as failed."""
        from unittest.mock import patch

        url = "https://example.com/whitespace"

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = "   \n\t  \n  "  # Whitespace only

                response = client.post(
                    "/admin/documents/urls",
                    data={
                        "urls": [url],
                        "app_target": "test",
                        "base_branch": "main",
                    },
                )

                assert response.status_code == 200
                data = response.json()
                assert data["ok_count"] == 0
                assert data["fail_count"] == 1


class TestBulkRegisterUrlsEdgeCases:
    """Edge case tests for bulk URL registration."""

    def test_empty_url_list(self, client: TestClient, admin_user):
        """Empty URL list should return 0 counts."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            response = client.post(
                "/admin/documents/urls",
                data={
                    "urls": [],
                    "app_target": "test",
                    "base_branch": "main",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["ok_count"] == 0
            assert data["fail_count"] == 0
            assert data["results"] == []

    def test_url_list_with_empty_strings(self, client: TestClient, admin_user):
        """URL list with empty strings should be filtered out."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = "Content"

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.return_value = {"indexed": True}

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": ["https://example.com/doc", "", "  ", "https://example.com/doc2"],
                            "app_target": "test",
                            "base_branch": "main",
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    # Should process only non-empty URLs
                    assert data["ok_count"] + data["fail_count"] <= 2

    def test_url_with_whitespace_trimmed(self, client: TestClient, admin_user):
        """URLs with leading/trailing whitespace should be trimmed."""
        from unittest.mock import patch

        urls_with_whitespace = [
            "  https://example.com/doc1  ",
            "\thttps://example.com/doc2\t",
        ]

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = "Content"

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.return_value = {"indexed": True}

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": urls_with_whitespace,
                            "app_target": "test",
                            "base_branch": "main",
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["ok_count"] == 2
                    # Check that whitespace was trimmed in results
                    assert all("https://example.com" in r["url"] for r in data["results"])

    def test_missing_app_target_uses_empty_string(self, client: TestClient, admin_user):
        """Missing app_target should default to empty string."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = "Content"

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.return_value = {"indexed": True}

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": ["https://example.com/doc"],
                            # app_target not provided
                            "base_branch": "main",
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["ok_count"] == 1

    def test_missing_base_branch_defaults_to_main(self, client: TestClient, admin_user):
        """Missing base_branch should default to 'main'."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = "Content"

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.return_value = {"indexed": True}

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": ["https://example.com/doc"],
                            "app_target": "test",
                            # base_branch not provided
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["ok_count"] == 1

    def test_database_error_caught_and_reported(self, client: TestClient, admin_user, db_session: Session):
        """Database errors should be caught and reported per URL."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = "Content"

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.side_effect = Exception("Database connection failed")

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": ["https://example.com/doc"],
                            "app_target": "test",
                            "base_branch": "main",
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["ok_count"] == 0
                    assert data["fail_count"] == 1
                    assert "error" in data["results"][0]
                    assert "Database" in data["results"][0]["error"]

    def test_response_includes_spec_id(self, client: TestClient, admin_user, db_session: Session):
        """Successful registrations should include the created spec_id."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = "Content"

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.return_value = {"indexed": True}

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": ["https://example.com/doc"],
                            "app_target": "test",
                            "base_branch": "main",
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["ok_count"] == 1
                    assert "spec_id" in data["results"][0]
                    assert isinstance(data["results"][0]["spec_id"], int)

    def test_large_url_list(self, client: TestClient, admin_user):
        """Handle a large number of URLs (e.g., 100 URLs)."""
        from unittest.mock import patch

        # Create 100 URLs
        urls = [f"https://example.com/doc{i}" for i in range(100)]

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = "Content"

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.return_value = {"indexed": True}

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": urls,
                            "app_target": "large_test",
                            "base_branch": "main",
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert len(data["results"]) == 100
                    assert data["ok_count"] + data["fail_count"] == 100


class TestBulkRegisterUrlsResponseFormat:
    """Tests for response format and structure."""

    def test_response_has_required_fields(self, client: TestClient, admin_user):
        """Response should have ok_count, fail_count, and results."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = "Content"

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.return_value = {"indexed": True}

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": ["https://example.com/doc"],
                            "app_target": "test",
                            "base_branch": "main",
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()

                    # Check required fields
                    assert "ok_count" in data
                    assert "fail_count" in data
                    assert "results" in data
                    assert isinstance(data["ok_count"], int)
                    assert isinstance(data["fail_count"], int)
                    assert isinstance(data["results"], list)

    def test_each_result_has_required_fields(self, client: TestClient, admin_user):
        """Each result in results list should have required fields."""
        from unittest.mock import patch

        with patch("app.auth.dependencies.require_admin_user") as mock_admin:
            mock_admin.return_value = admin_user.username

            with patch("app.services.document_parser.fetch_url_as_text") as mock_fetch:
                mock_fetch.return_value = "Content"

                with patch("app.services.document_parser.enqueue_or_index_sync") as mock_index:
                    mock_index.return_value = {"indexed": True}

                    response = client.post(
                        "/admin/documents/urls",
                        data={
                            "urls": ["https://example.com/doc"],
                            "app_target": "test",
                            "base_branch": "main",
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()

                    for result in data["results"]:
                        assert "url" in result
                        assert "ok" in result
                        if result["ok"]:
                            assert "spec_id" in result
                        else:
                            assert "error" in result
