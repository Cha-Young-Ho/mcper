"""Integration tests for document upload → indexing pipeline."""
import pytest

@pytest.mark.integration
class TestUploadIndex:
    def test_upload_and_search(self, test_client, db_session):
        """E2E: upload document → index → search finds it."""
        pytest.skip("TODO: implement with real DB")

    def test_upload_triggers_indexing(self, test_client, db_session):
        """Verify upload endpoint triggers enqueue_or_index_sync."""
        pytest.skip("TODO: implement")
