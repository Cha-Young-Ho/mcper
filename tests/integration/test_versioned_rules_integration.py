"""Integration tests for versioned rules service with DB."""

import pytest
from sqlalchemy.orm import Session

from app.db.rule_models import GlobalRuleVersion, AppRuleVersion, RepoRuleVersion
from app.services.versioned_rules import (
    normalize_read_version,
    normalize_agent_origin_url,
    repo_pattern_from_url_segment,
    repo_pat_href_segment,
    app_rule_card_display_name,
    repo_pattern_card_display,
    REPO_PATTERN_URL_DEFAULT,
)


@pytest.mark.integration
class TestNormalizeReadVersion:
    """Version normalization for MCP queries."""

    def test_none_returns_none(self):
        assert normalize_read_version(None) is None

    def test_positive_int(self):
        assert normalize_read_version(5) == 5

    def test_zero_returns_none(self):
        assert normalize_read_version(0) is None

    def test_negative_returns_none(self):
        assert normalize_read_version(-1) is None

    def test_string_latest(self):
        assert normalize_read_version("latest") is None

    def test_string_max(self):
        assert normalize_read_version("max") is None

    def test_string_number(self):
        assert normalize_read_version("3") == 3

    def test_empty_string(self):
        assert normalize_read_version("") is None

    def test_string_zero(self):
        assert normalize_read_version("0") is None


@pytest.mark.integration
class TestNormalizeAgentOriginUrl:
    """Agent origin URL extraction from various formats."""

    def test_none_returns_none(self):
        assert normalize_agent_origin_url(None) is None

    def test_empty_returns_none(self):
        assert normalize_agent_origin_url("") is None

    def test_https_url(self):
        result = normalize_agent_origin_url("https://github.com/org/repo.git")
        assert result == "https://github.com/org/repo.git"

    def test_ssh_url(self):
        result = normalize_agent_origin_url("git@github.com:org/repo.git")
        assert result == "git@github.com:org/repo.git"

    def test_git_remote_v_output(self):
        raw = "origin\tgit@github.com:org/repo.git (fetch)\norigin\tgit@github.com:org/repo.git (push)"
        result = normalize_agent_origin_url(raw)
        assert "github.com" in result

    def test_unknown_returns_none(self):
        assert normalize_agent_origin_url("unknown") is None

    def test_whitespace_handling(self):
        result = normalize_agent_origin_url("  https://github.com/test/repo.git  ")
        assert result is not None


@pytest.mark.integration
class TestRepoPatternHelpers:
    """Repo pattern URL segment conversion."""

    def test_default_pattern_to_url(self):
        assert repo_pat_href_segment("") == REPO_PATTERN_URL_DEFAULT

    def test_pattern_to_url(self):
        assert repo_pat_href_segment("github.com/org") is not None

    def test_url_segment_to_default(self):
        assert repo_pattern_from_url_segment(REPO_PATTERN_URL_DEFAULT) == ""

    def test_url_segment_to_pattern(self):
        assert repo_pattern_from_url_segment("github.com/org") == "github.com/org"


@pytest.mark.integration
class TestDisplayNameHelpers:
    """Display name formatting."""

    def test_app_default_display(self):
        assert app_rule_card_display_name("__default__") == "default"

    def test_app_empty_display(self):
        assert app_rule_card_display_name("") == "default"

    def test_app_normal_display(self):
        assert app_rule_card_display_name("myapp") == "myapp"

    def test_repo_empty_pattern_display(self):
        assert repo_pattern_card_display("") == "default"

    def test_repo_pattern_display(self):
        assert repo_pattern_card_display("github.com/org") == "github.com/org"


@pytest.mark.integration
class TestRuleVersionsDB:
    """Rule version CRUD through DB session."""

    def test_create_global_rule_version(self, db_session):
        """Create and retrieve a global rule version."""
        db_session.add(GlobalRuleVersion(version=1, body="# Global Rule v1"))
        db_session.commit()
        row = db_session.query(GlobalRuleVersion).filter_by(version=1).first()
        assert row is not None
        assert row.body == "# Global Rule v1"

    def test_create_multiple_global_versions(self, db_session):
        """Multiple versions coexist."""
        db_session.add(GlobalRuleVersion(version=1, body="v1"))
        db_session.add(GlobalRuleVersion(version=2, body="v2"))
        db_session.commit()
        count = db_session.query(GlobalRuleVersion).count()
        assert count == 2

    def test_create_app_rule_version(self, db_session):
        """Create an app-specific rule version."""
        db_session.add(AppRuleVersion(app_name="myapp", version=1, body="# App Rule"))
        db_session.commit()
        row = db_session.query(AppRuleVersion).filter_by(app_name="myapp").first()
        assert row is not None

    def test_create_repo_rule_version(self, db_session):
        """Create a repo rule version."""
        db_session.add(RepoRuleVersion(
            pattern="github.com/org",
            version=1,
            body="# Repo Rule",
        ))
        db_session.commit()
        row = db_session.query(RepoRuleVersion).filter_by(pattern="github.com/org").first()
        assert row is not None

    def test_global_rule_version_ordering(self, db_session):
        """Versions can be queried in order."""
        for v in range(1, 6):
            db_session.add(GlobalRuleVersion(version=v, body=f"v{v}"))
        db_session.commit()
        rows = (
            db_session.query(GlobalRuleVersion)
            .order_by(GlobalRuleVersion.version.desc())
            .all()
        )
        versions = [r.version for r in rows]
        assert versions == [5, 4, 3, 2, 1]
