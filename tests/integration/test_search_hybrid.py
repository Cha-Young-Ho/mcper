"""Integration tests for hybrid search (RRF)."""
import pytest

@pytest.mark.integration
class TestHybridSearch:
    def test_search_returns_results(self, db_session):
        """Verify hybrid search returns results when documents exist."""
        pytest.skip("Requires seeded database — implement after seed fixture")

    def test_search_empty_db(self, db_session):
        """Verify hybrid search returns empty list on empty DB."""
        pytest.skip("TODO: implement")
