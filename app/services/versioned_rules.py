"""Load and publish versioned global / repository / app rules (Postgres).

섹션 설계 (section_name):
- 기본 섹션은 "main" (모든 기존 API는 section_name="main" 기본값으로 backward-compatible)
- 각 (entity, section_name) 쌍이 독립 버전 스트림을 가짐
- MCP get_global_rule 은 모든 섹션을 합쳐 반환
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.rule_models import (
    AppRuleVersion,
    GlobalRuleVersion,
    McpAppPullOption,
    McpRepoPatternPullOption,
    McpRuleReturnOptions,
    RepoRuleVersion,
)
from app.services.git import GitContext, get_git_context

logger = __import__("logging").getLogger(__name__)

# URL 경로에서 빈 pattern 표현 (DB에는 "" 로 저장)
REPO_PATTERN_URL_DEFAULT = "__default__"

DEFAULT_SECTION = "main"

# `git remote -v` 한 줄·여러 줄·URL 단독 모두에서 fetch URL 추출
_ORIGIN_URL_EXTRACT = re.compile(
    r"git@[^:\s]+:\S+|https?://[^\s)\]]+|ssh://[^\s)\]]+",
)


def normalize_agent_origin_url(raw: str | None) -> str | None:
    """
    에이전트가 넘긴 값에서 origin fetch URL 한 덩어리만 추출.
    `origin  git@github.com:org/repo.git (fetch)` 통째로 와도 된다.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    for line in s.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _ORIGIN_URL_EXTRACT.search(line)
        if m:
            out = m.group(0).rstrip(".,;)")
            if out.strip().lower() != "unknown":
                return out
    m = _ORIGIN_URL_EXTRACT.search(s)
    if m:
        out = m.group(0).rstrip(".,;)")
        return None if out.strip().lower() == "unknown" else out
    out = s
    return None if out.strip().lower() == "unknown" else out


_FALLBACK_GLOBAL = (
    "# Global rule\n\n"
    "(DB에 global_rule_versions 행이 없습니다. 어드민 또는 publish_global_rule 로 등록하세요.)\n"
)
_FALLBACK_APP = (
    "(이 앱에 대한 app_rule_versions 가 없습니다. 어드민 또는 publish_app_rule 로 등록하세요.)\n"
)
_FALLBACK_REPO = (
    "(이 origin URL에 맞는 repository_rule_versions 가 없습니다. 어드민 또는 publish_repo_rule 로 등록하세요.)\n"
)

_GLOBAL_REPO_PREAMBLE = """## Repository 룰에 대해 (알림)

**Repository rule** 은 DB에 등록된 **부분문자열 패턴**이 **origin URL** 에 포함되는지로 고른다.

- **권장:** 에이전트가 워크스페이스에서 **`git remote -v`** 를 실행해 **origin 의 fetch URL** 을 얻고, `get_global_rule` 의 **`origin_url`** 인자로 그 문자열을 넘긴다. (Docker MCP 등에서 서버가 `git` 을 못 읽어도 매칭된다.)
- 서버가 직접 읽은 URL과 병행할 때는 **`origin_url` 이 우선**한다.

로컬 확인: **`git remote -v`**, **`git status`**. MCP가 URL·브랜치를 확정하지 못하면 **사용자에게** 저장소 루트·원격 URL·브랜치를 질문한다.

---
"""

_APP_UNCLEAR_FOOTER = (
    "\n\n---\n\n"
    "## 작업 전 확인 (Git / 룰)\n\n"
    "`git remote -v`, **`git status`** 로 메타를 확인하거나, **Repository·앱 룰이 바로 확정되지 않으면 사용자에게** 물어본다.\n"
)

# app_name 이 있는 2차 응답 끝에 붙임 — MCP는 마크다운만 주고, 저장 포맷·경로는 실행 중 에이전트가 IDE에 맞게 처리
_AGENT_LOCAL_RULE_SAVE_BLOCK = """# [CRITICAL — 사용 중인 에이전트/IDE에 맞게 로컬에 규칙 반영]

**이 MCP 서버가 하는 일:** `get_global_rule` 은 **규칙 본문(마크다운)만** 내려준다. **클라이언트별 전용 경로·파일 포맷으로의 변환·디스크 저장은, 지금 대화를 수행하는 에이전트가 담당**한다. (읽기만 하고 끝내지 말 것.)

## 0) [필수] 사용자가 룰을 "받아와 / 조회 / 동기화" 하라고 한 경우 — **로컬 파일 저장까지**

아래 **또는 이와 같은 의도**의 한국어·영어 요청이면, `get_global_rule` 로 받은 뒤 **채팅에만 보여 주고 끝내지 말고**, **반드시** 이 문서 아래 **2)~6)절**에 따라 **디스크에 저장**한다.

- 예: 「이 프로젝트 룰 받아와줘」「프로젝트 룰 받아와」「룰 조회해와」「룰 가져와」「워크스페이스 룰 불러와」「MCP 룰 동기화」「팀 규칙 받아와」「get_global_rule 해줘」「전역 룰 적용해줘」 등
- **예외:** 사용자가 **명시적으로** 「저장하지 마」「채팅만 보여줘」「파일 쓰지 마」라고 한 경우만 저장 생략 가능.

`app_name` 이 아직 없으면 부트스트랩 절차로 확보한 뒤 **2차 응답**을 받고, 그 **전체**를 저장한다.

## 1) 어떤 환경인지 먼저 판단

- 워크스페이스 단서·도구 이름·사용자 발화로 **실제 사용 제품**을 추정한다.  
  예: **Cursor**, **Claude Code / Claude**(터미널·IDE 플러그인), **Google Antigravity**, **Gemini** 기반 IDE/CLI, **GitHub Copilot Chat**, 기타.
- **확실하지 않으면** 한 문장만 묻는다:  
  *「Cursor / Claude Code / Antigravity / Gemini / 기타 중 무엇으로 이 저장소를 작업 중인가요?」*

## 2) 환경별 저장 위치·포맷 (제품 문서가 바뀌면 문서를 우선)

아래는 **흔한 패턴**이다. 각 제품의 **최신 공식 안내**와 다르면 공식을 따른다.

| 환경 (예) | 저장 위치·포맷 (요지) |
|-----------|----------------------|
| **Cursor** | Git 루트 `.cursor/rules/mcp-rules.mdc` (**팀 기본 파일명**). 항시 적용은 YAML `alwaysApply: true`. 필요 시 `mcp-rules-global.mdc` / `mcp-rules-repository.mdc` / `mcp-rules-app.mdc` 로 섹션 분리. |
| **Claude Code / 프로젝트 Claude** | 저장소 루트 **`CLAUDE.md`** 등, 해당 제품이 읽는 **프로젝트 규칙 마크다운**. frontmatter 없이 본문만인 경우가 많음. 섹션으로 Global / Repository / App 을 나눠도 됨. |
| **Google Antigravity** | 제품이 정한 **워크스페이스 규칙 디렉터리**(예: `.agent/rules/` 등 — **최신 문서 확인**). 마크다운으로 저장. |
| **Gemini / 기타** | 해당 제품의 **프로젝트 instructions / rules** 경로. 없으면 팀 합의로 `docs/MCP_AGENT_RULES.md` 같은 UTF-8 마크다운. |

**공통**

- **Git 저장소 루트**를 기준으로 둔다. 서브폴더만 열었으면 `git rev-parse --show-toplevel` 로 루트를 쓴다. 멀티 루트면 `app_name` 이 나온 **그 저장소** 루트.
- **MCP가 Docker 등으로만 돌 때:** 파일은 **호스트에서 사용자가 연 클론**에 쓴다. 컨테이너 안에만 쓰지 않는다.

## 3) 무엇을 파일에 넣을지

- **이번 `get_global_rule` 2차 응답**의 실질 본문(Global / Repository / App, 맨 위 `<!-- rule_meta: -->` 는 팀 정책에 따라 유지·삭제)과 **이 `[CRITICAL — …]` 절**을, **선택한 환경이 요구하는 포맷**으로 넣는다.  
  - 예: Cursor `.mdc` → YAML frontmatter 필요. `CLAUDE.md` → 순수 마크다운 위주.
- **`app_name` 없이 받은 1차 부트스트랩만** 있는 응답은 **저장하지 않는다.**

## 4) Cursor 전용 참고 — 파일 분할 전략

**섹션이 여러 개인 경우 (권장: 섹션별 분리 파일)**:
- `mcp-rules-global-main.mdc` — Global rule main 섹션
- `mcp-rules-global-{section_name}.mdc` — Global 추가 섹션마다
- `mcp-rules-repo-{pattern}-{section_name}.mdc` — Repository 패턴 × 섹션
- `mcp-rules-app-{app_name}-main.mdc` — App rule main 섹션
- `mcp-rules-app-{app_name}-{section_name}.mdc` — App 추가 섹션마다 (예: `mcp-rules-app-myapp-admin_rules.mdc`)
- 모두 `alwaysApply: true` 설정.

**섹션이 main 하나뿐인 경우 (기존 단순 방식)**:
- `mcp-rules.mdc` 한 파일에 전체 + `alwaysApply: true`.
- 또는 `mcp-rules-global.mdc` / `mcp-rules-repository.mdc` / `mcp-rules-app.mdc` 3파일 분할.

## 5) Repository 룰이 (default) 폴백만 올 때 / `git_origin_url=Unknown`

- **먼저** 워크스페이스에서 **`git remote -v`** 로 origin fetch URL 을 얻어, **같은 `app_name`으로** `get_global_rule(..., origin_url="그_URL")` 를 **재호출**한다. (`git@...` / `https://...` 한 줄이면 됨. `git remote -v` 통째 붙여 넣어도 서버가 URL 을 뽑는다.)
- 그다음에도 서버 Git 이 필요하면 `repo_root` 또는 `GIT_REPO_ROOT` 를 쓴다.

## 6) 저장 후

- Cursor 사용자에게 **「`.cursor/rules/mcp-rules.mdc` (또는 팀이 쓰는 경로)에 반영했다」** 고 짧게 알리고 본 작업을 진행한다.
"""


def normalize_read_version(version: int | str | None) -> int | None:
    """
    MCP 조회용: None / 빈값 / 'latest' 등 → 최신(None).
    정수 또는 정수 문자열 → 해당 버전 고정.
    """
    if version is None:
        return None
    if isinstance(version, int):
        return version if version > 0 else None
    if isinstance(version, str):
        s = version.strip().lower()
        if s in ("", "latest", "max", "newest", "last"):
            return None
        try:
            n = int(s)
            return n if n > 0 else None
        except ValueError:
            return None
    return None


def repo_pattern_from_url_segment(segment: str) -> str:
    """어드민 URL 세그먼트 → DB pattern (빈 값은 __default__)."""
    s = segment.strip()
    if s == REPO_PATTERN_URL_DEFAULT:
        return ""
    return s


def repo_pat_href_segment(pattern: str) -> str:
    """DB pattern → 어드민 경로 한 세그먼트 (인코딩 없이 안전한 경우 그대로)."""
    p = (pattern or "").strip()
    if not p:
        return REPO_PATTERN_URL_DEFAULT
    return quote(p, safe="")


def app_rule_card_display_name(app_name: str) -> str:
    """카드/헤더 표기: DB `__default__` 는 화면에만 `default` 로 표시."""
    s = (app_name or "").strip().lower()
    if s in ("", "__default__"):
        return "default"
    return (app_name or "").strip()


def repo_pattern_card_display(pattern: str) -> str:
    """빈 패턴(폴백) 스트림은 카드에 `default` 로만 표시."""
    if not (pattern or "").strip():
        return "default"
    return (pattern or "").strip()


def get_mcp_include_repo_default(session: Session) -> bool:
    """레거시 전역 플래그(행 없는 패턴 폴백에만 사용)."""
    row = session.get(McpRuleReturnOptions, 1)
    if row is None:
        return False
    return bool(row.include_repo_default)


def get_mcp_include_repo_default_for_pattern(session: Session, pattern: str | None) -> bool:
    """패턴별로 repository `default`(빈 패턴) 스트림 병합 여부. 행 없으면 전역 플래그 폴백."""
    key = pattern if pattern is not None else ""
    row = session.get(McpRepoPatternPullOption, key)
    if row is not None:
        return bool(row.include_repo_default)
    return get_mcp_include_repo_default(session)


def set_mcp_include_repo_default_for_pattern(
    session: Session, pattern: str, value: bool
) -> None:
    key = pattern if pattern is not None else ""
    row = session.get(McpRepoPatternPullOption, key)
    if row is None:
        session.add(McpRepoPatternPullOption(pattern=key, include_repo_default=value))
    else:
        row.include_repo_default = value
    session.commit()


def ensure_mcp_repo_pattern_pull_option(session: Session, pattern: str) -> None:
    """새 repo 패턴 첫 버전 후 옵션 행이 없으면 전역 기본값으로 생성."""
    key = pattern if pattern is not None else ""
    if session.get(McpRepoPatternPullOption, key) is not None:
        return
    session.add(
        McpRepoPatternPullOption(
            pattern=key,
            include_repo_default=get_mcp_include_repo_default(session),
        )
    )
    session.commit()


def get_mcp_include_app_default_global(session: Session) -> bool:
    """앱별 행이 없을 때 쓰는 전역 기본(어드민 Global 보드에서 토글)."""
    row = session.get(McpRuleReturnOptions, 1)
    if row is None:
        return False
    return bool(row.include_app_default)


def set_mcp_include_app_default_global(session: Session, value: bool) -> None:
    row = session.get(McpRuleReturnOptions, 1)
    if row is None:
        session.add(
            McpRuleReturnOptions(
                id=1,
                include_app_default=value,
                include_repo_default=False,
            )
        )
    else:
        row.include_app_default = value
    session.commit()


def get_mcp_include_app_default_for_app(session: Session, app_name: str) -> bool:
    """
    MCP 응답에 `__default__` 앱 스트림을 **이 app_name** 요청에 한해 추가로 붙일지.
    `__default__` 를 직접 조회할 때는 항상 False (중복 섹션 방지).
    """
    key = (app_name or "").strip().lower()
    if not key or key == "__default__":
        return False
    row = session.get(McpAppPullOption, key)
    if row is not None:
        return bool(row.include_app_default)
    return get_mcp_include_app_default_global(session)


def set_mcp_include_app_default_for_app(session: Session, app_name: str, value: bool) -> None:
    key = (app_name or "").strip().lower()
    if not key or key == "__default__":
        raise ValueError("invalid app_name for pull option")
    row = session.get(McpAppPullOption, key)
    if row is None:
        session.add(McpAppPullOption(app_name=key, include_app_default=value))
    else:
        row.include_app_default = value
    session.commit()


def set_mcp_include_repo_default(session: Session, value: bool) -> None:
    row = session.get(McpRuleReturnOptions, 1)
    if row is None:
        session.add(
            McpRuleReturnOptions(
                id=1,
                include_app_default=False,
                include_repo_default=value,
            )
        )
    else:
        row.include_repo_default = value
    session.commit()


def list_sections_for_global(session: Session) -> list[str]:
    """글로벌 룰의 모든 섹션 이름 (알파벳 순, 'main' 우선)."""
    rows = session.scalars(
        select(GlobalRuleVersion.section_name).distinct()
    ).all()
    sections = sorted({r for r in rows if r}, key=lambda s: ("" if s == DEFAULT_SECTION else s))
    return sections or [DEFAULT_SECTION]


def list_sections_for_app(session: Session, app_name: str) -> list[str]:
    """앱의 모든 섹션 이름 (알파벳 순, 'main' 우선)."""
    key = (app_name or "").lower().strip()
    rows = session.scalars(
        select(AppRuleVersion.section_name)
        .where(AppRuleVersion.app_name == key)
        .distinct()
    ).all()
    sections = sorted({r for r in rows if r}, key=lambda s: ("" if s == DEFAULT_SECTION else s))
    return sections or [DEFAULT_SECTION]


def list_sections_for_repo(session: Session, pattern: str) -> list[str]:
    """레포지토리 패턴의 모든 섹션 이름 (알파벳 순, 'main' 우선)."""
    key = (pattern or "").strip()
    rows = session.scalars(
        select(RepoRuleVersion.section_name)
        .where(RepoRuleVersion.pattern == key)
        .distinct()
    ).all()
    sections = sorted({r for r in rows if r}, key=lambda s: ("" if s == DEFAULT_SECTION else s))
    return sections or [DEFAULT_SECTION]


def _global_latest(
    session: Session, section_name: str = DEFAULT_SECTION
) -> GlobalRuleVersion | None:
    """지정 섹션의 최신 global 룰 행."""
    max_v = (
        select(func.max(GlobalRuleVersion.version))
        .where(GlobalRuleVersion.section_name == section_name)
        .scalar_subquery()
    )
    return session.scalars(
        select(GlobalRuleVersion).where(
            GlobalRuleVersion.section_name == section_name,
            GlobalRuleVersion.version == max_v,
        )
    ).first()


def _domain_filter(col, domain: str | None):
    """domain 필터 조건 생성. development는 NULL도 포함."""
    if domain is None:
        return None
    if domain == "development":
        return (col == "development") | (col.is_(None))
    return col == domain


def _global_all_sections_latest(
    session: Session, *, domain: str | None = None
) -> list[GlobalRuleVersion]:
    """모든 섹션의 최신 global 룰 행 (섹션별 max version)."""
    base = select(
        GlobalRuleVersion.section_name.label("sn"),
        func.max(GlobalRuleVersion.version).label("mv"),
    )
    df = _domain_filter(GlobalRuleVersion.domain, domain)
    if df is not None:
        base = base.where(df)
    subq = base.group_by(GlobalRuleVersion.section_name).subquery()
    q = select(GlobalRuleVersion).join(
        subq,
        (GlobalRuleVersion.section_name == subq.c.sn)
        & (GlobalRuleVersion.version == subq.c.mv),
    )
    if df is not None:
        q = q.where(_domain_filter(GlobalRuleVersion.domain, domain))
    rows = session.scalars(q).all()
    return sorted(rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _global_exact(
    session: Session, version: int, section_name: str = DEFAULT_SECTION
) -> GlobalRuleVersion | None:
    return session.scalars(
        select(GlobalRuleVersion).where(
            GlobalRuleVersion.section_name == section_name,
            GlobalRuleVersion.version == version,
        )
    ).first()


def resolve_global_row(
    session: Session,
    version: int | None,
    section_name: str = DEFAULT_SECTION,
) -> tuple[GlobalRuleVersion | None, int | None, bool]:
    """
    version None → 최신.
    version N → N번 행, 없으면 최신으로 폴백 (fallback=True).
    """
    if version is None:
        return _global_latest(session, section_name), None, False
    row = _global_exact(session, version, section_name)
    if row is not None:
        return row, version, False
    return _global_latest(session, section_name), version, True


def _app_latest(
    session: Session, app_name: str, section_name: str = DEFAULT_SECTION
) -> AppRuleVersion | None:
    """`WHERE app_name=:key AND section_name=:sn AND version=MAX` — __default__ 폴백 포함."""
    key = app_name.lower().strip()
    max_v = (
        select(func.max(AppRuleVersion.version))
        .where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.section_name == section_name,
        )
        .scalar_subquery()
    )
    row = session.scalars(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.section_name == section_name,
            AppRuleVersion.version == max_v,
        )
    ).first()
    if row is None and key != "__default__":
        max_d = (
            select(func.max(AppRuleVersion.version))
            .where(
                AppRuleVersion.app_name == "__default__",
                AppRuleVersion.section_name == section_name,
            )
            .scalar_subquery()
        )
        return session.scalars(
            select(AppRuleVersion).where(
                AppRuleVersion.app_name == "__default__",
                AppRuleVersion.section_name == section_name,
                AppRuleVersion.version == max_d,
            )
        ).first()
    return row


def _app_all_sections_latest(
    session: Session, app_name: str
) -> list[AppRuleVersion]:
    """앱의 모든 섹션 × 최신 버전 행 목록 (섹션 이름 알파벳순, main 우선)."""
    key = app_name.lower().strip()
    subq = (
        select(
            AppRuleVersion.section_name.label("sn"),
            func.max(AppRuleVersion.version).label("mv"),
        )
        .where(AppRuleVersion.app_name == key)
        .group_by(AppRuleVersion.section_name)
        .subquery()
    )
    rows = session.scalars(
        select(AppRuleVersion).join(
            subq,
            (AppRuleVersion.app_name == key)
            & (AppRuleVersion.section_name == subq.c.sn)
            & (AppRuleVersion.version == subq.c.mv),
        )
    ).all()
    return sorted(rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _app_exact(
    session: Session, app_name: str, version: int, section_name: str = DEFAULT_SECTION
) -> AppRuleVersion | None:
    key = app_name.lower().strip()
    row = session.scalars(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.section_name == section_name,
            AppRuleVersion.version == version,
        )
    ).first()
    if row is None and key != "__default__":
        return session.scalars(
            select(AppRuleVersion).where(
                AppRuleVersion.app_name == "__default__",
                AppRuleVersion.section_name == section_name,
                AppRuleVersion.version == version,
            )
        ).first()
    return row


def resolve_app_row(
    session: Session,
    app_name: str,
    version: int | None,
    section_name: str = DEFAULT_SECTION,
) -> tuple[AppRuleVersion | None, int | None, bool]:
    """version None → 최신(+ __default__ 폴백). version N → N번 행, 없으면 최신으로 폴백."""
    if version is None:
        return _app_latest(session, app_name, section_name), None, False
    row = _app_exact(session, app_name, version, section_name)
    if row is not None:
        return row, version, False
    return _app_latest(session, app_name, section_name), version, True


def _app_latest_strict(
    session: Session, app_name: str, section_name: str = DEFAULT_SECTION
) -> AppRuleVersion | None:
    """해당 app_name + section_name 스트림만 (__default__ 폴백 없음)."""
    key = app_name.lower().strip()
    max_v = (
        select(func.max(AppRuleVersion.version))
        .where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.section_name == section_name,
        )
        .scalar_subquery()
    )
    return session.scalars(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.section_name == section_name,
            AppRuleVersion.version == max_v,
        )
    ).first()


def _app_exact_named_only(
    session: Session, app_name: str, version: int, section_name: str = DEFAULT_SECTION
) -> AppRuleVersion | None:
    key = app_name.lower().strip()
    return session.scalars(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.section_name == section_name,
            AppRuleVersion.version == version,
        )
    ).first()


def resolve_app_row_named_only(
    session: Session,
    app_name: str,
    version: int | None,
    section_name: str = DEFAULT_SECTION,
) -> tuple[AppRuleVersion | None, int | None, bool]:
    """MCP `include_app_default` 용: 요청 app 스트림만, __default__ 폴백 없음."""
    key = app_name.lower().strip()
    if version is None:
        return _app_latest_strict(session, key, section_name), None, False
    row = _app_exact_named_only(session, app_name, version, section_name)
    if row is not None:
        return row, version, False
    latest = _app_latest_strict(session, key, section_name)
    return latest, version, True


def _repo_latest_for_pattern(
    session: Session, pattern: str, section_name: str = DEFAULT_SECTION
) -> RepoRuleVersion | None:
    key = pattern.strip()
    max_v = (
        select(func.max(RepoRuleVersion.version))
        .where(
            RepoRuleVersion.pattern == key,
            RepoRuleVersion.section_name == section_name,
        )
        .scalar_subquery()
    )
    return session.scalars(
        select(RepoRuleVersion).where(
            RepoRuleVersion.pattern == key,
            RepoRuleVersion.section_name == section_name,
            RepoRuleVersion.version == max_v,
        )
    ).first()


def _repo_all_sections_latest_for_pattern(
    session: Session, pattern: str
) -> list[RepoRuleVersion]:
    """레포 패턴의 모든 섹션 × 최신 버전 행 (섹션 이름 알파벳순, main 우선)."""
    key = pattern.strip()
    subq = (
        select(
            RepoRuleVersion.section_name.label("sn"),
            func.max(RepoRuleVersion.version).label("mv"),
        )
        .where(RepoRuleVersion.pattern == key)
        .group_by(RepoRuleVersion.section_name)
        .subquery()
    )
    rows = session.scalars(
        select(RepoRuleVersion).join(
            subq,
            (RepoRuleVersion.pattern == key)
            & (RepoRuleVersion.section_name == subq.c.sn)
            & (RepoRuleVersion.version == subq.c.mv),
        )
    ).all()

    # 중복 제거 (같은 section_name은 1개만)
    seen = set()
    unique_rows = []
    for row in rows:
        if row.section_name not in seen:
            seen.add(row.section_name)
            unique_rows.append(row)

    return sorted(unique_rows, key=lambda r: ("" if r.section_name == DEFAULT_SECTION else r.section_name))


def _repo_latest_rows_ordered(
    session: Session, section_name: str = DEFAULT_SECTION
) -> list[RepoRuleVersion]:
    """패턴별 `version = MAX(version)` 행만 조인해 가져온 뒤 sort_order → pattern 정렬."""
    subq = (
        select(
            RepoRuleVersion.pattern.label("p"),
            func.max(RepoRuleVersion.version).label("mv"),
        )
        .where(RepoRuleVersion.section_name == section_name)
        .group_by(RepoRuleVersion.pattern)
        .subquery()
    )
    rows = session.scalars(
        select(RepoRuleVersion).join(
            subq,
            (RepoRuleVersion.pattern == subq.c.p)
            & (RepoRuleVersion.section_name == section_name)
            & (RepoRuleVersion.version == subq.c.mv),
        )
    ).all()
    latest = list(rows)
    latest.sort(key=lambda r: (r.sort_order, r.pattern or ""))
    return latest


def resolve_repo_row(
    session: Session, repo_url: str, section_name: str = DEFAULT_SECTION
) -> RepoRuleVersion | None:
    """origin URL 소문자에 패턴 부분문자열이 들어가는 첫 행(정렬 우선). 없으면 빈 패턴 최신."""
    url_l = (repo_url or "").strip().lower()
    rows = _repo_latest_rows_ordered(session, section_name)
    for r in rows:
        pat = (r.pattern or "").strip()
        if pat and pat.lower() in url_l:
            return r
    for r in rows:
        if not (r.pattern or "").strip():
            return r
    return None


def git_context_uncertain(ctx: GitContext) -> bool:
    return (
        not (ctx.repo_url or "").strip()
        or ctx.repo_url == "Unknown"
        or not (ctx.current_branch or "").strip()
        or ctx.current_branch == "Unknown"
    )


def build_markdown_response(
    *,
    global_rows: list[GlobalRuleVersion],
    repo_rows: list[RepoRuleVersion],
    repo_default_rows: list[RepoRuleVersion] | None = None,
    app_rows: list[AppRuleVersion],
    app_default_rows: list[AppRuleVersion] | None = None,
    app_name: str | None,
    notices: list[str],
    meta_extra: list[str],
    three_layer: bool,
    uncertain_git: bool,
    # backward-compat single-row aliases (None → ignored)
    global_row: GlobalRuleVersion | None = None,
    repo_row: RepoRuleVersion | None = None,
    repo_default_row: RepoRuleVersion | None = None,
    app_row: AppRuleVersion | None = None,
    app_default_row: AppRuleVersion | None = None,
) -> str:
    """Assemble markdown for MCP clients (멀티섹션 지원).

    섹션이 여러 개일 때 각 섹션을 별도 헤딩으로 분리 출력.
    backward-compat: 구 single-row 파라미터도 허용 (list 파라미터가 비었을 때 사용).
    """
    # backward-compat 처리
    if not global_rows and global_row is not None:
        global_rows = [global_row]
    if not repo_rows and repo_row is not None:
        repo_rows = [repo_row]
    if repo_default_rows is None and repo_default_row is not None:
        repo_default_rows = [repo_default_row]
    if not app_rows and app_row is not None:
        app_rows = [app_row]
    if app_default_rows is None and app_default_row is not None:
        app_default_rows = [app_default_row]
    if repo_default_rows is None:
        repo_default_rows = []
    if app_default_rows is None:
        app_default_rows = []

    meta_parts: list[str] = []

    # global 메타
    if global_rows:
        sections_meta = ",".join(
            f"{r.section_name}:{r.version}" for r in global_rows
        )
        meta_parts.append(f"global_served={sections_meta}")
    else:
        meta_parts.append("global_served=(none)")

    meta_parts.extend(meta_extra)

    if three_layer:
        if repo_rows:
            repo_meta = ",".join(
                f"{repo_pattern_card_display(r.pattern)}/{r.section_name}:{r.version}"
                for r in repo_rows
            )
            meta_parts.append(f"repo_served={repo_meta}")
        else:
            meta_parts.append("repo_served=(none)")

    if app_name:
        req_l = app_name.strip().lower()
        meta_parts.append(f"app_name={app_name}")
        if app_rows:
            named = [r for r in app_rows if r.app_name == req_l]
            if named:
                app_meta = ",".join(f"{r.section_name}:{r.version}" for r in named)
                meta_parts.append(f"app_served={app_meta}")
            else:
                meta_parts.append("app_named_served=(none)")
                default_meta = ",".join(f"{r.section_name}:{r.version}" for r in app_rows)
                meta_parts.append(f"app_default_served={default_meta}")
                meta_parts.append("app_stream_resolved=__default__")
        else:
            meta_parts.append("app_served=(none)")

    meta_line = "<!-- rule_meta: " + ", ".join(meta_parts) + " -->"
    chunks: list[str] = [meta_line]

    if notices:
        chunks.append("\n".join(f"> {n}" for n in notices))

    # ── Global 섹션들 ──────────────────────────────────────────────────────
    if global_rows:
        for gr in global_rows:
            sec_label = "" if gr.section_name == DEFAULT_SECTION else f" — 섹션: {gr.section_name}"
            body = gr.body
            if three_layer and gr == global_rows[0]:
                body = _GLOBAL_REPO_PREAMBLE.strip() + "\n\n" + body
            chunks.append(f"# Global rule{sec_label} (version {gr.version})\n\n{body}")
    else:
        body = _FALLBACK_GLOBAL
        if three_layer:
            body = _GLOBAL_REPO_PREAMBLE.strip() + "\n\n" + body
        chunks.append(f"# Global rule\n\n{body}")

    # ── Repository 섹션들 ──────────────────────────────────────────────────
    if three_layer:
        if repo_rows:
            for rr in repo_rows:
                disp = repo_pattern_card_display(rr.pattern)
                sec_label = "" if rr.section_name == DEFAULT_SECTION else f" — 섹션: {rr.section_name}"
                chunks.append(
                    f"# Repository rule — pattern `{disp}`{sec_label} (version {rr.version})\n\n{rr.body}"
                )
        else:
            chunks.append(f"# Repository rule\n\n{_FALLBACK_REPO}")

        for rdr in repo_default_rows:
            if not any(rdr.id == r.id for r in repo_rows):
                sec_label = "" if rdr.section_name == DEFAULT_SECTION else f" — 섹션: {rdr.section_name}"
                chunks.append(
                    f"# Repository rule — pattern `default`{sec_label} (version {rdr.version})\n\n"
                    f"{rdr.body}"
                )

    # ── App 섹션들 ─────────────────────────────────────────────────────────
    if app_name:
        req_l = app_name.strip().lower()
        if app_rows:
            named = [r for r in app_rows if r.app_name == req_l]
            if not named:
                # __default__ 폴백
                chunks.append(
                    f"# App rule: {app_name}\n\n"
                    f"*DB에 `{app_name}` 전용 행이 없습니다. "
                    f"**default** (`__default__`) 스트림 본문이 적용됩니다.*\n"
                )
                for dr in app_rows:
                    sec_label = "" if dr.section_name == DEFAULT_SECTION else f" — 섹션: {dr.section_name}"
                    body = dr.body
                    if uncertain_git:
                        body = body + _APP_UNCLEAR_FOOTER
                    chunks.append(
                        f"# App rule: default{sec_label} (version {dr.version})\n\n{body}"
                    )
            else:
                for ar in named:
                    sec_label = "" if ar.section_name == DEFAULT_SECTION else f" — 섹션: {ar.section_name}"
                    body = ar.body
                    if uncertain_git:
                        body = body + _APP_UNCLEAR_FOOTER
                    chunks.append(
                        f"# App rule: {app_name}{sec_label} (version {ar.version})\n\n{body}"
                    )
        else:
            fb = _FALLBACK_APP
            if uncertain_git:
                fb = fb + _APP_UNCLEAR_FOOTER
            chunks.append(f"# App rule: {app_name}\n\n{fb}")

        for adr in app_default_rows:
            if req_l != "__default__" and not any(adr.id == r.id for r in app_rows):
                sec_label = "" if adr.section_name == DEFAULT_SECTION else f" — 섹션: {adr.section_name}"
                chunks.append(
                    f"# App rule: default{sec_label} (version {adr.version})\n\n{adr.body}"
                )

    if three_layer:
        chunks.append(_AGENT_LOCAL_RULE_SAVE_BLOCK.strip())

    return "\n\n---\n\n".join(chunks)


def get_rules_markdown(
    session: Session,
    *,
    app_name: str | None,
    version: int | None,
    repo_root: str | None = None,
    origin_url: str | None = None,
) -> str:
    """
    조회 전용 (멀티섹션 지원):
    - app_name 없음: global 모든 섹션 (repo_root / origin_url 무시).
    - app_name 있음: global 모든 섹션 + repository 모든 섹션 + 앱 모든 섹션.
    """
    trimmed = (app_name or "").strip()
    notices: list[str] = []
    meta_extra: list[str] = []

    if not trimmed:
        global_rows = _global_all_sections_latest(session)
        return build_markdown_response(
            global_rows=global_rows,
            repo_rows=[],
            app_rows=[],
            app_name=None,
            notices=notices,
            meta_extra=meta_extra,
            three_layer=False,
            uncertain_git=False,
        )

    git_ctx = get_git_context(repo_root)
    agent_origin = normalize_agent_origin_url(origin_url)
    server_uncertain = git_context_uncertain(git_ctx)

    if agent_origin:
        repo_match_url = agent_origin
        meta_extra.append("git_origin_source=agent_git_remote_v")
        meta_extra.append(f"git_origin_url={repo_match_url}")
        meta_extra.append(f"git_branch={git_ctx.current_branch}")
        if server_uncertain:
            notices.append(
                "MCP 서버는 Git 메타를 완전히 읽지 못했지만, **에이전트가 넘긴 `origin_url`** 로 Repository 룰을 매칭했다. "
                "브랜치 등 추가 확인은 로컬에서 `git status` 를 쓰거나 사용자에게 질문하라."
            )
    else:
        repo_match_url = (git_ctx.repo_url or "").strip() or "Unknown"
        meta_extra.append("git_origin_source=server")
        meta_extra.append(f"git_origin_url={git_ctx.repo_url}")
        meta_extra.append(f"git_branch={git_ctx.current_branch}")
        if server_uncertain:
            notices.append(
                "Git `origin` URL 또는 현재 브랜치를 **MCP 서버**가 읽지 못했다. "
                "**에이전트는 워크스페이스에서 `git remote -v` 를 실행한 뒤**, "
                "`get_global_rule(..., origin_url=\"origin의_fetch_URL\")` 로 **재호출**하여 Repository 룰을 맞춘다."
            )

    uncertain = server_uncertain and not agent_origin

    # 모든 섹션의 global 최신
    global_rows = _global_all_sections_latest(session)

    # Repository 매칭: main 섹션으로 패턴 판별 후, 해당 패턴의 모든 섹션 조회
    repo_r_main = resolve_repo_row(session, repo_match_url, DEFAULT_SECTION)
    matched_pattern = repo_r_main.pattern if repo_r_main is not None else None

    repo_rows: list[RepoRuleVersion] = []
    if matched_pattern is not None:
        repo_rows = _repo_all_sections_latest_for_pattern(session, matched_pattern)

    inc_repo = get_mcp_include_repo_default_for_pattern(session, matched_pattern or "")
    meta_extra.append(f"mcp_include_app_default={get_mcp_include_app_default_for_app(session, trimmed)}")
    meta_extra.append(f"mcp_include_repo_default={'true' if inc_repo else 'false'}")

    # 레포 default (빈 패턴) 섹션들
    repo_default_rows: list[RepoRuleVersion] = []
    if inc_repo:
        default_rows = _repo_all_sections_latest_for_pattern(session, "")
        repo_default_rows = [r for r in default_rows if not any(r.id == x.id for x in repo_rows)]

    # 앱 모든 섹션 최신
    inc_app = get_mcp_include_app_default_for_app(session, trimmed)
    meta_extra.append("global_mode=latest_for_app_context")

    if inc_app and trimmed.lower() != "__default__":
        app_rows = _app_all_sections_latest(session, trimmed)
        app_default_rows_raw = _app_all_sections_latest(session, "__default__")
        app_default_rows = [r for r in app_default_rows_raw if not any(r.id == x.id for x in app_rows)]
    else:
        app_rows = _app_all_sections_latest(session, trimmed)
        # __default__ 폴백: 앱 전용 행이 없으면 __default__ 사용
        if not app_rows and trimmed.lower() != "__default__":
            app_rows = _app_all_sections_latest(session, "__default__")
        app_default_rows = []

    return build_markdown_response(
        global_rows=global_rows,
        repo_rows=repo_rows,
        repo_default_rows=repo_default_rows,
        app_rows=app_rows,
        app_default_rows=app_default_rows,
        app_name=trimmed,
        notices=notices,
        meta_extra=meta_extra,
        three_layer=True,
        uncertain_git=uncertain,
    )


def get_rule_version_snapshot(
    session: Session,
    *,
    app_name: str | None,
    origin_url: str | None,
    repo_root: str | None,
) -> dict[str, Any]:
    """
    DB에 저장된 최신 룰의 버전 정보를 섹션별로 JSON 반환.
    - `global_sections`: {section_name: version} 딕셔너리
    - `app_sections`: {section_name: version} 딕셔너리 (app_name 없으면 null)
    - `repo_sections`: {section_name: version} 딕셔너리
    - backward-compat: `global_version`, `app_version`, `repo_version` 도 유지 (main 섹션)
    """
    global_rows = _global_all_sections_latest(session)
    global_sections = {r.section_name: r.version for r in global_rows}
    g_main = next((r for r in global_rows if r.section_name == DEFAULT_SECTION), None)

    out: dict[str, Any] = {
        "global_version": g_main.version if g_main else None,
        "global_sections": global_sections,
    }

    trimmed = (app_name or "").strip()
    if not trimmed:
        inc_repo = get_mcp_include_repo_default_for_pattern(session, "")
        out["app_name"] = None
        out["app_version"] = None
        out["app_sections"] = None
        out["repo_pattern"] = None
        out["repo_version"] = None
        out["repo_sections"] = None
        out["mcp_include_app_default"] = None
        out["mcp_include_repo_default"] = inc_repo
        out["app_default_version"] = None
        if inc_repo:
            dr_rows = _repo_all_sections_latest_for_pattern(session, "")
            out["repo_default_version"] = dr_rows[0].version if dr_rows else None
        else:
            out["repo_default_version"] = None
        return out

    key = trimmed.lower()
    git_ctx = get_git_context(repo_root)
    agent_origin = normalize_agent_origin_url(origin_url)
    repo_match_url = agent_origin or (git_ctx.repo_url or "").strip() or "Unknown"

    repo_r_main = resolve_repo_row(session, repo_match_url, DEFAULT_SECTION)
    matched_pattern = repo_r_main.pattern if repo_r_main is not None else None
    inc_app = get_mcp_include_app_default_for_app(session, trimmed)
    inc_repo = get_mcp_include_repo_default_for_pattern(session, matched_pattern or "")
    out["mcp_include_app_default"] = inc_app
    out["mcp_include_repo_default"] = inc_repo

    # 앱 섹션별 버전
    app_section_rows = _app_all_sections_latest(session, key)
    if app_section_rows:
        app_sections = {r.section_name: r.version for r in app_section_rows}
        an_main = next((r for r in app_section_rows if r.section_name == DEFAULT_SECTION), None)
        out["app_version"] = an_main.version if an_main else app_section_rows[0].version
        out["app_default_version"] = None
    else:
        dr_rows = _app_all_sections_latest(session, "__default__")
        app_sections = {r.section_name: r.version for r in dr_rows} if dr_rows else {}
        out["app_version"] = None
        out["app_default_version"] = dr_rows[0].version if dr_rows else None

    out["app_name"] = key
    out["app_sections"] = app_sections or None

    if matched_pattern is not None:
        repo_section_rows = _repo_all_sections_latest_for_pattern(session, matched_pattern)
        repo_sections = {r.section_name: r.version for r in repo_section_rows}
        r_main = next((r for r in repo_section_rows if r.section_name == DEFAULT_SECTION), None)
        out["repo_pattern"] = repo_pattern_card_display(matched_pattern)
        out["repo_version"] = r_main.version if r_main else (repo_section_rows[0].version if repo_section_rows else None)
        out["repo_sections"] = repo_sections or None
    else:
        out["repo_pattern"] = None
        out["repo_version"] = None
        out["repo_sections"] = None

    if inc_repo:
        dr_rows = _repo_all_sections_latest_for_pattern(session, "")
        out["repo_default_version"] = dr_rows[0].version if dr_rows else None
    else:
        out["repo_default_version"] = None

    return out


def next_global_version(session: Session, section_name: str = DEFAULT_SECTION) -> int:
    m = session.scalar(
        select(func.coalesce(func.max(GlobalRuleVersion.version), 0)).where(
            GlobalRuleVersion.section_name == section_name
        )
    )
    return int(m or 0) + 1


def next_app_version(session: Session, app_name: str, section_name: str = DEFAULT_SECTION) -> int:
    key = app_name.lower().strip()
    m = session.scalar(
        select(func.max(AppRuleVersion.version)).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.section_name == section_name,
        )
    )
    return int(m or 0) + 1


def next_repo_version(session: Session, pattern: str, section_name: str = DEFAULT_SECTION) -> int:
    key = pattern.strip()
    m = session.scalar(
        select(func.coalesce(func.max(RepoRuleVersion.version), 0)).where(
            RepoRuleVersion.pattern == key,
            RepoRuleVersion.section_name == section_name,
        )
    )
    return int(m or 0) + 1


def _try_index_rule(
    session: Session,
    rule_type: str,
    rule_entity_id: int,
    body: str,
    *,
    app_name: str | None = None,
    pattern: str | None = None,
    domain: str | None = None,
    section_name: str = DEFAULT_SECTION,
) -> None:
    try:
        from app.rule.service import make_default_rule_service
        svc = make_default_rule_service(session)
        svc.index_rule(
            rule_type=rule_type,
            rule_entity_id=rule_entity_id,
            body=body,
            app_name=app_name,
            pattern=pattern,
            domain=domain,
            section_name=section_name,
        )
    except Exception:
        logger.warning("rule indexing failed type=%s id=%s", rule_type, rule_entity_id, exc_info=True)


def publish_global(
    session: Session, body: str, section_name: str = DEFAULT_SECTION, *, domain: str | None = None
) -> int:
    """섹션별 다음 버전 번호를 자동 할당해 글로벌 룰 추가."""
    nv = next_global_version(session, section_name)
    row = GlobalRuleVersion(section_name=section_name, version=nv, body=body, domain=domain)
    session.add(row)
    session.commit()
    _try_index_rule(session, "global", row.id, body, domain=domain, section_name=section_name)
    return nv


def publish_app(
    session: Session, app_name: str, body: str, section_name: str = DEFAULT_SECTION, *, domain: str | None = None
) -> tuple[str, str, int]:
    """(app_name, section_name) 스트림의 다음 버전 자동 할당. 반환: (app_name, section_name, version)."""
    key = app_name.lower().strip()
    if not key:
        raise ValueError("app_name is required")
    sn = (section_name or DEFAULT_SECTION).strip()
    nv = next_app_version(session, key, sn)
    row = AppRuleVersion(app_name=key, section_name=sn, version=nv, body=body, domain=domain)
    session.add(row)
    session.commit()
    _try_index_rule(session, "app", row.id, body, app_name=key, domain=domain, section_name=sn)
    return key, sn, nv


def append_to_app_rule(
    session: Session,
    app_name: str,
    append_markdown: str,
    section_name: str = DEFAULT_SECTION,
) -> tuple[str, str, int]:
    """섹션 최신 본문 뒤에 append_markdown 이어 붙여 새 버전 저장. 반환: (app_name, section_name, version)."""
    key = app_name.lower().strip()
    if not key:
        raise ValueError("app_name is required")
    addition = (append_markdown or "").strip()
    if not addition:
        raise ValueError("append_markdown is required")
    sn = (section_name or DEFAULT_SECTION).strip()
    latest = _app_latest(session, key, sn)
    if latest is None:
        new_body = addition
    else:
        new_body = latest.body.rstrip() + "\n\n" + addition
    return publish_app(session, key, new_body, sn)


def publish_repo(
    session: Session,
    pattern: str,
    body: str,
    *,
    sort_order: int | None = None,
    section_name: str = DEFAULT_SECTION,
    domain: str | None = None,
) -> tuple[str, str, int]:
    """(pattern, section_name) 스트림의 다음 버전. 반환: (pattern, section_name, version)."""
    key = pattern.strip()
    sn = (section_name or DEFAULT_SECTION).strip()
    nv = next_repo_version(session, key, sn)
    max_v = (
        select(func.max(RepoRuleVersion.version))
        .where(
            RepoRuleVersion.pattern == key,
            RepoRuleVersion.section_name == sn,
        )
        .scalar_subquery()
    )
    prev = session.scalars(
        select(RepoRuleVersion).where(
            RepoRuleVersion.pattern == key,
            RepoRuleVersion.section_name == sn,
            RepoRuleVersion.version == max_v,
        )
    ).first()
    if nv == 1 and sort_order is not None:
        so = sort_order
    elif prev is not None:
        so = prev.sort_order
    else:
        any_prev = session.scalars(
            select(RepoRuleVersion).where(RepoRuleVersion.pattern == key).limit(1)
        ).first()
        so = any_prev.sort_order if any_prev else 100
    row = RepoRuleVersion(pattern=key, section_name=sn, version=nv, body=body.strip(), sort_order=so, domain=domain)
    session.add(row)
    session.commit()
    ensure_mcp_repo_pattern_pull_option(session, key)
    _try_index_rule(session, "repo", row.id, body, pattern=key, domain=domain, section_name=sn)
    return key, sn, nv


def patch_global_rule(
    session: Session, patch_markdown: str, section_name: str = DEFAULT_SECTION
) -> tuple[str, int]:
    """global 룰 섹션 최신 버전에 patch_markdown 덧붙여 새 버전 생성."""
    latest = _global_latest(session, section_name)
    base = latest.body if latest else ""
    new_body = base.rstrip() + "\n\n" + patch_markdown.strip() if base else patch_markdown.strip()
    return "global", publish_global(session, new_body, section_name)


def patch_app_rule(
    session: Session, app_name: str, patch_markdown: str, section_name: str = DEFAULT_SECTION
) -> tuple[str, str, int]:
    """app 룰 섹션 최신 버전에 patch_markdown 병합 후 새 버전 생성."""
    key = (app_name or "").strip().lower()
    if not key:
        raise ValueError("app_name is required")
    latest = _app_latest(session, key, section_name)
    base = latest.body if latest else ""
    new_body = base.rstrip() + "\n\n" + patch_markdown.strip() if base else patch_markdown.strip()
    return publish_app(session, key, new_body, section_name)


def patch_repo_rule(
    session: Session, pattern: str, patch_markdown: str, section_name: str = DEFAULT_SECTION
) -> tuple[str, str, int]:
    """repo 룰 섹션 최신 버전에 patch_markdown 병합 후 새 버전 생성."""
    key = (pattern or "").strip()
    latest = _repo_latest_for_pattern(session, key, section_name)
    base = latest.body if latest else ""
    new_body = base.rstrip() + "\n\n" + patch_markdown.strip() if base else patch_markdown.strip()
    return publish_repo(session, key, new_body, section_name=section_name)


def rollback_global_rule(
    session: Session, target_version: int, section_name: str = DEFAULT_SECTION
) -> int:
    """global 룰 섹션을 target_version 본문으로 새 버전 생성 (히스토리 보존)."""
    row = session.scalar(
        select(GlobalRuleVersion).where(
            GlobalRuleVersion.section_name == section_name,
            GlobalRuleVersion.version == target_version,
        )
    )
    if row is None:
        raise ValueError(f"global rule section={section_name} version {target_version} not found")
    return publish_global(session, row.body, section_name)


def rollback_app_rule(
    session: Session, app_name: str, target_version: int, section_name: str = DEFAULT_SECTION
) -> tuple[str, str, int]:
    """app 룰 섹션 특정 버전으로 롤백."""
    key = (app_name or "").strip().lower()
    row = session.scalar(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.section_name == section_name,
            AppRuleVersion.version == target_version,
        )
    )
    if row is None:
        raise ValueError(f"app rule '{key}' section={section_name} version {target_version} not found")
    return publish_app(session, key, row.body, section_name)


def rollback_repo_rule(
    session: Session, pattern: str, target_version: int, section_name: str = DEFAULT_SECTION
) -> tuple[str, str, int]:
    """repo 룰 섹션 특정 버전으로 롤백."""
    key = (pattern or "").strip()
    row = session.scalar(
        select(RepoRuleVersion).where(
            RepoRuleVersion.pattern == key,
            RepoRuleVersion.section_name == section_name,
            RepoRuleVersion.version == target_version,
        )
    )
    if row is None:
        raise ValueError(f"repo rule pattern '{key}' section={section_name} version {target_version} not found")
    return publish_repo(session, key, row.body, section_name=section_name)


def export_rules_markdown(session: Session) -> str:
    """모든 룰 (global/app/repo × 모든 섹션 최신)을 단일 마크다운 문자열로 export."""
    lines: list[str] = ["# MCPER Rules Export\n"]

    global_rows = _global_all_sections_latest(session)
    if global_rows:
        lines.append("## Global Rules\n")
        for gr in global_rows:
            lines.append(f"### Section: {gr.section_name} (v{gr.version})\n")
            lines.append(gr.body)
            lines.append("\n")

    apps = list_distinct_apps(session)
    if apps:
        lines.append("## App Rules\n")
        for app in apps:
            app_rows = _app_all_sections_latest(session, app)
            if app_rows:
                lines.append(f"### App: {app}\n")
                for ar in app_rows:
                    lines.append(f"#### Section: {ar.section_name} (v{ar.version})\n")
                    lines.append(ar.body)
                    lines.append("\n")

    patterns = list_distinct_repo_patterns(session)
    if patterns:
        lines.append("## Repository Rules\n")
        for p in patterns:
            repo_rows = _repo_all_sections_latest_for_pattern(session, p)
            if repo_rows:
                label = p if p else "(default)"
                lines.append(f"### Pattern: {label}\n")
                for rr in repo_rows:
                    lines.append(f"#### Section: {rr.section_name} (v{rr.version})\n")
                    lines.append(rr.body)
                    lines.append("\n")

    return "\n".join(lines)


def export_rules_json(session: Session) -> dict:
    """모든 룰 최신 버전 (섹션 포함)을 JSON 직렬화 가능한 dict로 export."""
    global_rows = _global_all_sections_latest(session)
    apps = list_distinct_apps(session)
    patterns = list_distinct_repo_patterns(session)

    app_rules: dict[str, dict] = {}
    for app in apps:
        app_rows = _app_all_sections_latest(session, app)
        if app_rows:
            app_rules[app] = {
                r.section_name: {"version": r.version, "body": r.body}
                for r in app_rows
            }

    repo_rules: dict[str, dict] = {}
    for p in patterns:
        repo_rows = _repo_all_sections_latest_for_pattern(session, p)
        if repo_rows:
            repo_rules[p or "__default__"] = {
                r.section_name: {"version": r.version, "body": r.body}
                for r in repo_rows
            }

    return {
        "global": {
            r.section_name: {"version": r.version, "body": r.body}
            for r in global_rows
        },
        "apps": app_rules,
        "repos": repo_rules,
    }


def list_distinct_apps(session: Session, *, domain: str | None = None) -> list[str]:
    q = select(AppRuleVersion.app_name).distinct()
    df = _domain_filter(AppRuleVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    rows = session.scalars(q).all()
    return sorted({r for r in rows if r})


def list_distinct_repo_patterns(session: Session, *, domain: str | None = None) -> list[str]:
    q = select(RepoRuleVersion.pattern).distinct()
    df = _domain_filter(RepoRuleVersion.domain, domain)
    if df is not None:
        q = q.where(df)
    rows = session.scalars(q).all()
    return sorted(
        {r for r in rows if r is not None},
        key=lambda p: (0 if (p or "").strip() else 1, (p or "").lower()),
    )
