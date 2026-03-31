"""Integration tests for rule versioning."""

import pytest
from app.db.rule_models import GlobalRuleVersion


@pytest.mark.integration
class TestRuleVersioning:
    def test_create_and_fetch_rule(self, db_session):
        """Create a rule version and verify it can be retrieved."""
        db_session.add(GlobalRuleVersion(version=1, body="# Test rule"))
        db_session.commit()
        row = db_session.query(GlobalRuleVersion).filter_by(version=1).first()
        assert row is not None
        assert row.body == "# Test rule"

    def test_rollback_creates_new_version(self, db_session):
        """Verify rollback creates new version with old content."""
        db_session.add(GlobalRuleVersion(version=1, body="Original"))
        db_session.add(GlobalRuleVersion(version=2, body="Updated"))
        db_session.commit()

        # Simulate rollback: create v3 with v1 content
        v1 = db_session.query(GlobalRuleVersion).filter_by(version=1).first()
        db_session.add(GlobalRuleVersion(version=3, body=v1.body))
        db_session.commit()

        v3 = db_session.query(GlobalRuleVersion).filter_by(version=3).first()
        assert v3.body == "Original"
        assert db_session.query(GlobalRuleVersion).count() == 3
