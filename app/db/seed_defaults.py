"""Seed versioned rules: global from markdown; app/repo rows via ORM (no bundled .sql files)."""

from __future__ import annotations

import logging
import os

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.db.rule_models import (
    AppRuleVersion,
    GlobalRuleVersion,
    McpAppPullOption,
    RepoRuleVersion,
)
from app.prompts.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_auth_enabled = os.environ.get("MCPER_AUTH_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)


def _default_app_body() -> str:
    return (
        "## 앱 공통\n\n"
        "- 프로젝트 기본 Clean Code 컨벤션을 준수하십시오.\n"
        "- REST/웹 구분 없이 공통으로: 에러 핸들링, 기존 컨벤션 존중, 도메인에 맞는 변경.\n"
        "- **레포 URL별 가이드(api/web 등)** 는 MCP 2차 응답의 **Repository rule** 블록을 따르십시오.\n"
        "- **Git 메타나 룰 본문이 불완전하면** `git status`, `git remote -v` 로 확인하거나 **사용자에게** 물어보십시오.\n"
    )


def seed_repo_defaults(session: Session) -> None:
    rows: list[tuple[str, int, str]] = [
        (
            "api",
            10,
            "## API 레포지토리\n\n"
            "- 공통 Response 래핑·에러 코드 규약을 프로젝트 표준에 맞출 것.\n"
            "- 외부 연동 시 로깅·타임아웃·재시도 정책을 명시된 대로.\n",
        ),
        (
            "web",
            20,
            "## Web 레포지토리\n\n"
            "- 컴포넌트/Props 타입·스타일 가이드를 팀 컨벤션에 맞출 것.\n"
            "- 접근성·번들 크기를 고려한 구현.\n",
        ),
        (
            "",
            9999,
            "## 기본 Repository 룰 (폴백)\n\n"
            "- origin URL에 등록된 다른 패턴(api/web 등)이 없을 때 적용.\n"
            "- 팀 공통 브랜치·PR 규약을 따르십시오.\n",
        ),
    ]
    for pattern, sort_order, body in rows:
        session.add(
            RepoRuleVersion(
                pattern=pattern,
                version=1,
                body=body,
                sort_order=sort_order,
            )
        )


def seed_all_rows(session: Session) -> None:
    """
    Insert global version 1 + **앱 룰은 `__default__`만** (version 1) + repo version 1.
    그 외 앱 식별자는 코드에 두지 않고 DB에만 둔다(운영에서 INSERT / MCP publish).
    """
    session.add(
        GlobalRuleVersion(
            version=1,
            body=load_prompt("global_rule_bootstrap"),
        )
    )

    session.add(
        AppRuleVersion(
            app_name="__default__",
            version=1,
            body=_default_app_body(),
        )
    )

    seed_repo_defaults(session)


def seed_if_empty(session: Session) -> bool:
    """Return True if full rule seed ran (global was empty)."""
    session.execute(text("SELECT pg_advisory_xact_lock(1234567890)"))
    n = session.scalar(select(func.count()).select_from(GlobalRuleVersion)) or 0
    if n > 0:
        return False
    seed_all_rows(session)
    session.commit()
    return True


def seed_repo_if_empty(session: Session) -> bool:
    """기존 DB에 global만 있고 repo 테이블이 비어 있을 때 repository 시드만 추가."""
    session.execute(text("SELECT pg_advisory_xact_lock(1234567891)"))
    n = session.scalar(select(func.count()).select_from(RepoRuleVersion)) or 0
    if n > 0:
        return False
    seed_repo_defaults(session)
    session.commit()
    return True


def seed_force(session: Session) -> None:
    """Wipe versioned rule tables and re-seed."""
    session.execute(delete(McpAppPullOption))
    session.execute(delete(RepoRuleVersion))
    session.execute(delete(AppRuleVersion))
    session.execute(delete(GlobalRuleVersion))
    session.commit()
    seed_all_rows(session)
    session.commit()


def seed_admin_user_if_empty(session: Session) -> None:
    """
    MCPER_AUTH_ENABLED=true이고 mcper_users 테이블이 비어 있으면
    ADMIN_USER / ADMIN_PASSWORD 환경변수로 초기 관리자 계정 생성.
    password_changed_at=NULL로 설정하여 초기 로그인 시 강제 변경 유도.
    """
    if not _auth_enabled:
        return
    try:
        from app.db.auth_models import User
        from app.auth.service import hash_password

        count = session.scalar(select(func.count()).select_from(User)) or 0
        if count > 0:
            return
        username = os.environ.get("ADMIN_USER", "admin")
        password = os.environ.get("ADMIN_PASSWORD", "")
        if not password:
            logger.warning(
                "MCPER_AUTH_ENABLED=true but ADMIN_PASSWORD is empty. Skipping admin seed."
            )
            return
        session.add(
            User(
                username=username,
                hashed_password=hash_password(password),
                is_admin=True,
                is_active=True,
                password_changed_at=None,  # 초기 상태: 패스워드 미변경
            )
        )
        session.commit()
        logger.info(
            "Initial admin user '%s' created (password change required on first login).",
            username,
        )
    except Exception as exc:
        logger.exception("seed_admin_user_if_empty failed: %s", exc)
        session.rollback()
