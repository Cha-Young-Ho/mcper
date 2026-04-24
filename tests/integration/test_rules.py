"""Integration tests for rule versioning.

기존 DB에 'main' section 의 version=1,2 등이 이미 있을 수 있으므로
테스트마다 고유 section_name 을 사용해 충돌을 회피한다.
"""

import uuid

import pytest
from app.db.rule_models import GlobalRuleVersion


def _unique_section() -> str:
    return f"test_{uuid.uuid4().hex[:8]}"


@pytest.mark.integration
class TestRuleVersioning:
    def test_create_and_fetch_rule(self, db_session):
        """Create a rule version and verify it can be retrieved."""
        section = _unique_section()
        db_session.add(GlobalRuleVersion(section_name=section, version=1, body="# Test rule"))
        db_session.commit()
        row = (
            db_session.query(GlobalRuleVersion)
            .filter_by(section_name=section, version=1)
            .first()
        )
        assert row is not None
        assert row.body == "# Test rule"

    def test_rollback_creates_new_version(self, db_session):
        """Verify rollback creates new version with old content."""
        section = _unique_section()
        db_session.add(GlobalRuleVersion(section_name=section, version=1, body="Original"))
        db_session.add(GlobalRuleVersion(section_name=section, version=2, body="Updated"))
        db_session.commit()

        # Simulate rollback: create v3 with v1 content
        v1 = (
            db_session.query(GlobalRuleVersion)
            .filter_by(section_name=section, version=1)
            .first()
        )
        db_session.add(GlobalRuleVersion(section_name=section, version=3, body=v1.body))
        db_session.commit()

        v3 = (
            db_session.query(GlobalRuleVersion)
            .filter_by(section_name=section, version=3)
            .first()
        )
        assert v3.body == "Original"
        assert (
            db_session.query(GlobalRuleVersion).filter_by(section_name=section).count() == 3
        )
