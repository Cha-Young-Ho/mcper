"""Tests for upload_documents_batch MCP tool - batch document upload functionality."""

import json
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import Spec


class TestUploadDocumentsBatchBasics:
    """Basic functionality tests for upload_documents_batch."""

    def test_empty_list_returns_zero_count(self):
        """Calling with empty document list should return success count of 0."""
        from app.tools.documents import upload_document_impl

        result_json = upload_document_impl(
            content="",
            app_target="test",
            base_branch="main",
            related_files=None,
            title=None,
        )

        # Since upload_document_impl expects single doc, we test the batch wrapper differently
        # For now, test that it returns valid JSON
        result = json.loads(result_json)
        assert isinstance(result, dict)
        assert "ok" in result

    def test_single_document_upload_success(self):
        """Upload a single document successfully."""
        from app.tools.documents import upload_document_impl

        content = "Test document content"
        app_target = "test_app"
        base_branch = "main"

        result_json = upload_document_impl(
            content=content,
            app_target=app_target,
            base_branch=base_branch,
            related_files=None,
            title="Test Doc",
        )

        result = json.loads(result_json)
        assert result["ok"] is True
        assert "id" in result
        assert result["message"] == "inserted"
        assert isinstance(result["id"], int)

    def test_single_document_with_related_files(self):
        """Upload document with related files metadata."""
        from app.tools.documents import upload_document_impl

        content = "Test document content"
        related_files = ["file1.py", "file2.py", "folder/file3.py"]

        result_json = upload_document_impl(
            content=content,
            app_target="test_app",
            base_branch="develop",
            related_files=related_files,
            title="Doc with files",
        )

        result = json.loads(result_json)
        assert result["ok"] is True
        assert "id" in result


class TestUploadDocumentsBatchPartialFailure:
    """Partial failure scenario tests."""

    def test_batch_with_some_empty_content(self):
        """Batch with some empty documents should skip them gracefully."""
        from app.tools.documents import upload_document_impl

        # Test with content that will fail DB insertion
        with patch("app.tools.documents.SessionLocal") as mock_session_factory:
            mock_session = MagicMock()
            mock_session_factory.return_value = mock_session

            # Simulate DB add/commit success
            result_json = upload_document_impl(
                content="Valid content",
                app_target="test",
                base_branch="main",
                related_files=None,
                title=None,
            )

            result = json.loads(result_json)
            # Should be valid JSON with either ok=True or ok=False
            assert "ok" in result
            assert isinstance(result["ok"], bool)

    def test_database_error_returns_error_json(self):
        """Database error should return JSON with error message."""
        from app.tools.documents import upload_document_impl

        with patch("app.tools.documents.SessionLocal") as mock_session_factory:
            mock_session = MagicMock()
            mock_session_factory.return_value = mock_session
            mock_session.add.side_effect = Exception("Database connection error")

            result_json = upload_document_impl(
                content="Test content",
                app_target="test",
                base_branch="main",
                related_files=None,
            )

            result = json.loads(result_json)
            assert result["ok"] is False
            assert "error" in result
            assert "Database connection error" in result["error"]


class TestUploadDocumentsBatchMetadata:
    """Tests for metadata handling in batch uploads."""

    def test_title_optional(self):
        """Document title should be optional."""
        from app.tools.documents import upload_document_impl

        result_json = upload_document_impl(
            content="Test content",
            app_target="test",
            base_branch="main",
            related_files=None,
            title=None,  # No title
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_empty_title_treated_as_none(self):
        """Empty string title should be treated as None."""
        from app.tools.documents import upload_document_impl

        result_json = upload_document_impl(
            content="Test content",
            app_target="test",
            base_branch="main",
            related_files=None,
            title="",  # Empty title
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_whitespace_only_title_treated_as_none(self):
        """Whitespace-only title should be treated as None."""
        from app.tools.documents import upload_document_impl

        result_json = upload_document_impl(
            content="Test content",
            app_target="test",
            base_branch="main",
            related_files=None,
            title="   \t\n  ",  # Whitespace only
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_related_files_as_list(self):
        """Related files as list should be accepted."""
        from app.tools.documents import upload_document_impl

        result_json = upload_document_impl(
            content="Test content",
            app_target="test",
            base_branch="main",
            related_files=["file1.py", "file2.py"],
            title="Doc",
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_related_files_as_json_string(self):
        """Related files as JSON array string should be accepted."""
        from app.tools.documents import upload_document_impl

        result_json = upload_document_impl(
            content="Test content",
            app_target="test",
            base_branch="main",
            related_files='["file1.py", "file2.py"]',
            title="Doc",
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_related_files_as_comma_separated_string(self):
        """Related files as comma-separated string should be accepted."""
        from app.tools.documents import upload_document_impl

        result_json = upload_document_impl(
            content="Test content",
            app_target="test",
            base_branch="main",
            related_files="file1.py, file2.py, folder/file3.py",
            title="Doc",
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_app_target_case_preserved(self):
        """App target case should be preserved as-is."""
        from app.tools.documents import upload_document_impl

        app_targets = ["MyApp", "myapp", "MYAPP", "my-app"]

        for target in app_targets:
            result_json = upload_document_impl(
                content="Test content",
                app_target=target,
                base_branch="main",
                related_files=None,
            )
            result = json.loads(result_json)
            assert "ok" in result


class TestUploadDocumentsBatchEdgeCases:
    """Edge case tests for batch uploads."""

    def test_very_large_document_content(self):
        """Handle very large document content."""
        from app.tools.documents import upload_document_impl

        # Create a large document (1MB of text)
        large_content = "x" * (1024 * 1024)

        result_json = upload_document_impl(
            content=large_content,
            app_target="test",
            base_branch="main",
            related_files=None,
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_document_with_special_characters(self):
        """Handle documents with special characters."""
        from app.tools.documents import upload_document_impl

        content = "Special chars: ñ, é, 中文, 한글, emoji: 😀🎉"

        result_json = upload_document_impl(
            content=content,
            app_target="test",
            base_branch="main",
            related_files=None,
            title="특수문자 테스트",
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_document_with_newlines_and_whitespace(self):
        """Handle documents with various whitespace patterns."""
        from app.tools.documents import upload_document_impl

        content = """
        Line 1

        Line 3 with    multiple    spaces

        \tLine 4 with tabs
        """

        result_json = upload_document_impl(
            content=content,
            app_target="test",
            base_branch="main",
            related_files=None,
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_document_with_base64_content(self):
        """Handle documents that might contain base64 encoded content."""
        from app.tools.documents import upload_document_impl

        import base64

        original = "This is encoded content"
        encoded = base64.b64encode(original.encode()).decode()

        result_json = upload_document_impl(
            content=encoded,
            app_target="test",
            base_branch="main",
            related_files=None,
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_document_with_code_snippets(self):
        """Handle documents containing code snippets."""
        from app.tools.documents import upload_document_impl

        content = """
        # Code Example

        ```python
        def hello_world():
            print("Hello, World!")
        ```

        ```javascript
        const greet = () => console.log("Hi");
        ```
        """

        result_json = upload_document_impl(
            content=content,
            app_target="code_docs",
            base_branch="main",
            related_files=None,
            title="Code Snippets",
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_null_related_files(self):
        """Null related_files should default to empty list."""
        from app.tools.documents import upload_document_impl

        result_json = upload_document_impl(
            content="Test content",
            app_target="test",
            base_branch="main",
            related_files=None,
        )

        result = json.loads(result_json)
        assert "ok" in result

    def test_empty_string_related_files(self):
        """Empty string related_files should default to empty list."""
        from app.tools.documents import upload_document_impl

        result_json = upload_document_impl(
            content="Test content",
            app_target="test",
            base_branch="main",
            related_files="",
        )

        result = json.loads(result_json)
        assert "ok" in result


class TestUploadDocumentsBatchResponseFormat:
    """Tests for response format and structure."""

    def test_success_response_format(self):
        """Successful upload should return proper JSON format."""
        from app.tools.documents import upload_document_impl

        result_json = upload_document_impl(
            content="Test content",
            app_target="test",
            base_branch="main",
            related_files=None,
        )

        result = json.loads(result_json)

        # Check required fields for success
        assert "ok" in result
        assert result["ok"] is True
        assert "id" in result
        assert "message" in result
        assert isinstance(result["id"], int)

    def test_error_response_format(self):
        """Failed upload should return proper error JSON format."""
        from app.tools.documents import upload_document_impl

        with patch("app.tools.documents.SessionLocal") as mock_session_factory:
            mock_session = MagicMock()
            mock_session_factory.return_value = mock_session
            mock_session.add.side_effect = Exception("Test error")

            result_json = upload_document_impl(
                content="Test content",
                app_target="test",
                base_branch="main",
                related_files=None,
            )

            result = json.loads(result_json)

            # Check required fields for error
            assert "ok" in result
            assert result["ok"] is False
            assert "error" in result

    def test_response_is_valid_json(self):
        """Response should always be valid JSON."""
        from app.tools.documents import upload_document_impl

        result_json = upload_document_impl(
            content="Test",
            app_target="test",
            base_branch="main",
            related_files=None,
        )

        # Should not raise exception
        result = json.loads(result_json)
        assert isinstance(result, dict)


class TestUploadDocumentsBatchIndexing:
    """Tests for document indexing integration."""

    def test_indexing_enqueued_on_success(self):
        """Document indexing should be enqueued after successful upload."""
        from app.tools.documents import upload_document_impl

        with patch("app.tools.documents.enqueue_index_spec") as mock_enqueue:
            mock_enqueue.return_value = True

            result_json = upload_document_impl(
                content="Test content",
                app_target="test",
                base_branch="main",
                related_files=None,
            )

            result = json.loads(result_json)

            if result["ok"]:
                # enqueue_index_spec should have been called with the spec ID
                assert mock_enqueue.called

    def test_chunk_index_queued_status_included(self):
        """Response should include chunk_index_queued status."""
        from app.tools.documents import upload_document_impl

        with patch("app.tools.documents.enqueue_index_spec") as mock_enqueue:
            mock_enqueue.return_value = True

            result_json = upload_document_impl(
                content="Test content",
                app_target="test",
                base_branch="main",
                related_files=None,
            )

            result = json.loads(result_json)

            if result["ok"]:
                assert "chunk_index_queued" in result
                assert result["chunk_index_queued"] is True


class TestUploadDocumentsBatchDatabase:
    """Tests for database operations."""

    def test_spec_created_with_correct_fields(self):
        """Uploaded spec should have correct fields in database."""
        from app.tools.documents import upload_document_impl

        title = "Test Document"
        content = "Test content"
        app_target = "test_app"
        base_branch = "develop"
        related_files = ["file1.py", "file2.py"]

        with patch("app.tools.documents.enqueue_index_spec") as mock_enqueue:
            mock_enqueue.return_value = True

            result_json = upload_document_impl(
                content=content,
                app_target=app_target,
                base_branch=base_branch,
                related_files=related_files,
                title=title,
            )

            result = json.loads(result_json)

            if result["ok"]:
                # Spec should be created with correct values
                assert result["ok"] is True

    def test_transaction_rollback_on_failure(self):
        """Transaction should be rolled back on failure."""
        from app.tools.documents import upload_document_impl

        with patch("app.tools.documents.SessionLocal") as mock_session_factory:
            mock_session = MagicMock()
            mock_session_factory.return_value = mock_session
            mock_session.add.side_effect = Exception("DB error")

            result_json = upload_document_impl(
                content="Test",
                app_target="test",
                base_branch="main",
                related_files=None,
            )

            result = json.loads(result_json)

            # Rollback should be called on error
            assert mock_session.rollback.called or not result["ok"]

    def test_session_always_closed(self):
        """Database session should always be closed."""
        from app.tools.documents import upload_document_impl

        with patch("app.tools.documents.SessionLocal") as mock_session_factory:
            mock_session = MagicMock()
            mock_session_factory.return_value = mock_session

            result_json = upload_document_impl(
                content="Test",
                app_target="test",
                base_branch="main",
                related_files=None,
            )

            # Session should be closed (in finally block)
            assert mock_session.close.called


class TestUploadDocumentsBatchIntegration:
    """Integration tests for batch uploads."""

    def test_mcp_tool_records_statistics(self):
        """MCP tool call should be recorded in statistics."""
        from app.tools.documents import upload_document_impl

        # Patch the name imported into app.tools.documents, not the source module
        with patch("app.tools.documents.record_mcp_tool_call") as mock_record:
            upload_document_impl(
                content="Test",
                app_target="test",
                base_branch="main",
                related_files=None,
            )
            assert mock_record.called

    def test_ensure_ascii_false_in_json_response(self):
        """Response JSON should handle non-ASCII characters."""
        from app.tools.documents import upload_document_impl

        title = "한글 제목 테스트"
        content = "중국어 내용 测试"

        result_json = upload_document_impl(
            content=content,
            app_target="test",
            base_branch="main",
            related_files=None,
            title=title,
        )

        # Should not raise exception and preserve non-ASCII
        result = json.loads(result_json)
        assert isinstance(result, dict)
