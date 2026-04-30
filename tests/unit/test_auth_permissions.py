"""Unit tests for `app.auth.permissions` — 앱별/도메인별 권한 검증.

마스터(`is_admin=True`) 는 모든 요청 통과. 일반 유저는 `UserPermission` 행이
있는 (domain, app) 조합만 허용.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.auth.context import CurrentUser
from app.auth.permissions import (
    Role,
    check_permission,
    filter_restricted_sections,
    get_effective_role,
)


def _make_user(user_id: int = 1, is_admin: bool = False) -> CurrentUser:
    return CurrentUser(user_id=user_id, username="u", is_admin=is_admin)


def _db_with_perms(perms: list[SimpleNamespace]) -> MagicMock:
    """db.scalars(select(UserPermission).where(...)).all() 가 perms 를 돌려주도록."""
    scalars = MagicMock()
    scalars.all.return_value = perms
    db = MagicMock()
    db.scalars.return_value = scalars
    return db


class TestAdminBypass:
    def test_admin_has_admin_role_globally(self):
        db = _db_with_perms([])
        user = _make_user(is_admin=True)
        assert get_effective_role(db, user, None, None) == Role.ADMIN

    def test_admin_has_admin_role_for_any_app(self):
        db = _db_with_perms([])
        user = _make_user(is_admin=True)
        assert get_effective_role(db, user, "dev", "anipang") == Role.ADMIN

    def test_admin_passes_write_on_unknown_app(self):
        db = _db_with_perms([])
        user = _make_user(is_admin=True)
        assert check_permission(db, user, "dev", "random_app", "write") is True

    def test_admin_passes_admin_action(self):
        db = _db_with_perms([])
        user = _make_user(is_admin=True)
        assert check_permission(db, user, None, None, "admin") is True


class TestNonAdminNoPerm:
    def test_no_permission_returns_none(self):
        db = _db_with_perms([])
        user = _make_user()
        assert get_effective_role(db, user, "dev", "anipang") is None

    def test_no_permission_denies_read(self):
        db = _db_with_perms([])
        user = _make_user()
        assert check_permission(db, user, "dev", "anipang", "read") is False


class TestAppScopedPermission:
    def _perm(
        self, role: str, domain: str | None = None, app: str | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(role=role, domain_slug=domain, app_name=app)

    def test_exact_app_match_grants_role(self):
        perms = [self._perm("editor", "dev", "anipang")]
        db = _db_with_perms(perms)
        user = _make_user()
        assert get_effective_role(db, user, "dev", "anipang") == Role.EDITOR

    def test_different_app_denied(self):
        perms = [self._perm("editor", "dev", "anipang")]
        db = _db_with_perms(perms)
        user = _make_user()
        # 다른 앱에 대해선 권한 없음.
        assert get_effective_role(db, user, "dev", "other_app") is None
        assert check_permission(db, user, "dev", "other_app", "read") is False

    def test_domain_wide_permission_applies_to_any_app(self):
        """domain=dev, app=None → dev 도메인의 모든 앱에 적용."""
        perms = [self._perm("viewer", "dev", None)]
        db = _db_with_perms(perms)
        user = _make_user()
        assert get_effective_role(db, user, "dev", "anipang") == Role.VIEWER
        assert get_effective_role(db, user, "dev", "other") == Role.VIEWER

    def test_domain_wide_does_not_apply_to_other_domain(self):
        perms = [self._perm("viewer", "dev", None)]
        db = _db_with_perms(perms)
        user = _make_user()
        assert get_effective_role(db, user, "prod", "anipang") is None

    def test_global_permission_applies_everywhere(self):
        """domain=None, app=None → 모든 곳."""
        perms = [self._perm("viewer", None, None)]
        db = _db_with_perms(perms)
        user = _make_user()
        assert get_effective_role(db, user, "dev", "any") == Role.VIEWER
        assert get_effective_role(db, user, "prod", "other") == Role.VIEWER

    def test_exact_match_wins_over_domain_wide(self):
        """(dev, anipang)=admin + (dev, *)=viewer → exact=admin 채택."""
        perms = [
            self._perm("viewer", "dev", None),
            self._perm("admin", "dev", "anipang"),
        ]
        db = _db_with_perms(perms)
        user = _make_user()
        assert get_effective_role(db, user, "dev", "anipang") == Role.ADMIN


class TestCheckPermissionActions:
    def test_viewer_can_read_but_not_write(self):
        db = _db_with_perms(
            [SimpleNamespace(role="viewer", domain_slug="d", app_name="a")]
        )
        user = _make_user()
        assert check_permission(db, user, "d", "a", "read") is True
        assert check_permission(db, user, "d", "a", "write") is False
        assert check_permission(db, user, "d", "a", "admin") is False

    def test_editor_can_write_but_not_admin(self):
        db = _db_with_perms(
            [SimpleNamespace(role="editor", domain_slug="d", app_name="a")]
        )
        user = _make_user()
        assert check_permission(db, user, "d", "a", "read") is True
        assert check_permission(db, user, "d", "a", "write") is True
        assert check_permission(db, user, "d", "a", "admin") is False

    def test_admin_role_passes_all(self):
        db = _db_with_perms(
            [SimpleNamespace(role="admin", domain_slug="d", app_name="a")]
        )
        user = _make_user()
        assert check_permission(db, user, "d", "a", "admin") is True


class TestFilterRestrictedSections:
    def test_admin_sees_all_sections(self):
        db = MagicMock()
        user = _make_user(is_admin=True)
        out = filter_restricted_sections(db, user, "d", "a", ["main", "secret"])
        assert out == ["main", "secret"]

    def test_no_role_returns_empty(self):
        db = _db_with_perms([])
        user = _make_user()
        out = filter_restricted_sections(db, user, "d", "a", ["main"])
        assert out == []
