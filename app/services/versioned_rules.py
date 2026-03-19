"""Load and publish versioned global / repository / app rules (Postgres)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.rule_models import (
    AppRuleVersion,
    GlobalRuleVersion,
    McpAppPullOption,
    McpRuleReturnOptions,
    RepoRuleVersion,
)
from app.services.git import GitContext, get_git_context

# URL 경로에서 빈 pattern 표현 (DB에는 "" 로 저장)
REPO_PATTERN_URL_DEFAULT = "__default__"

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

## 4) Cursor 전용 참고 — 1파일 vs 3파일

- **기본(권장):** `<저장소_루트>/.cursor/rules/mcp-rules.mdc` 한 파일에 2차 응답 전체 + frontmatter `alwaysApply: true`.
- **분할(선택):** `mcp-rules-global.mdc` / `mcp-rules-repository.mdc` / `mcp-rules-app.mdc` — 각각 `alwaysApply: true`.

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
    """MCP 응답에 repository 빈 패턴(default) 스트림을 추가로 붙일지."""
    row = session.get(McpRuleReturnOptions, 1)
    if row is None:
        return False
    return bool(row.include_repo_default)


def get_mcp_include_app_default_for_app(session: Session, app_name: str) -> bool:
    """
    MCP 응답에 `__default__` 앱 스트림을 **이 app_name** 요청에 한해 추가로 붙일지.
    `__default__` 를 직접 조회할 때는 항상 False (중복 섹션 방지).
    """
    key = (app_name or "").strip().lower()
    if not key or key == "__default__":
        return False
    row = session.get(McpAppPullOption, key)
    if row is None:
        return False
    return bool(row.include_app_default)


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


def _global_latest(session: Session) -> GlobalRuleVersion | None:
    """`version = (SELECT MAX(version) FROM global_rule_versions)` 와 동등."""
    max_v = select(func.max(GlobalRuleVersion.version)).scalar_subquery()
    return session.scalars(
        select(GlobalRuleVersion).where(GlobalRuleVersion.version == max_v)
    ).first()


def _global_exact(session: Session, version: int) -> GlobalRuleVersion | None:
    return session.scalars(
        select(GlobalRuleVersion).where(GlobalRuleVersion.version == version)
    ).first()


def resolve_global_row(
    session: Session,
    version: int | None,
) -> tuple[GlobalRuleVersion | None, int | None, bool]:
    """
    version None → 최신.
    version N → N번 행, 없으면 최신으로 폴백 (fallback=True).
    """
    if version is None:
        return _global_latest(session), None, False
    row = _global_exact(session, version)
    if row is not None:
        return row, version, False
    return _global_latest(session), version, True


def _app_latest(session: Session, app_name: str) -> AppRuleVersion | None:
    """`WHERE app_name = :key AND version = (SELECT MAX(version) …)` 와 동등."""
    key = app_name.lower().strip()
    max_v = (
        select(func.max(AppRuleVersion.version))
        .where(AppRuleVersion.app_name == key)
        .scalar_subquery()
    )
    row = session.scalars(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.version == max_v,
        )
    ).first()
    if row is None and key != "__default__":
        max_d = (
            select(func.max(AppRuleVersion.version))
            .where(AppRuleVersion.app_name == "__default__")
            .scalar_subquery()
        )
        return session.scalars(
            select(AppRuleVersion).where(
                AppRuleVersion.app_name == "__default__",
                AppRuleVersion.version == max_d,
            )
        ).first()
    return row


def _app_exact(session: Session, app_name: str, version: int) -> AppRuleVersion | None:
    key = app_name.lower().strip()
    row = session.scalars(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.version == version,
        )
    ).first()
    if row is None and key != "__default__":
        return session.scalars(
            select(AppRuleVersion).where(
                AppRuleVersion.app_name == "__default__",
                AppRuleVersion.version == version,
            )
        ).first()
    return row


def resolve_app_row(
    session: Session,
    app_name: str,
    version: int | None,
) -> tuple[AppRuleVersion | None, int | None, bool]:
    """
    version None → 최신(+ __default__ 폴백은 _app_latest 안에서).
    version N → N번 행(앱 → __default__ 동일 N), 없으면 최신으로 폴백.
    """
    if version is None:
        return _app_latest(session, app_name), None, False
    row = _app_exact(session, app_name, version)
    if row is not None:
        return row, version, False
    return _app_latest(session, app_name), version, True


def _app_latest_strict(session: Session, app_name: str) -> AppRuleVersion | None:
    """해당 app_name 스트림만 (__default__ 폴백 없음)."""
    key = app_name.lower().strip()
    max_v = (
        select(func.max(AppRuleVersion.version))
        .where(AppRuleVersion.app_name == key)
        .scalar_subquery()
    )
    return session.scalars(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.version == max_v,
        )
    ).first()


def _app_exact_named_only(session: Session, app_name: str, version: int) -> AppRuleVersion | None:
    key = app_name.lower().strip()
    return session.scalars(
        select(AppRuleVersion).where(
            AppRuleVersion.app_name == key,
            AppRuleVersion.version == version,
        )
    ).first()


def resolve_app_row_named_only(
    session: Session,
    app_name: str,
    version: int | None,
) -> tuple[AppRuleVersion | None, int | None, bool]:
    """MCP `include_app_default` 용: 요청 app 스트림만, __default__ 폴백 없음."""
    key = app_name.lower().strip()
    if version is None:
        return _app_latest_strict(session, key), None, False
    row = _app_exact_named_only(session, app_name, version)
    if row is not None:
        return row, version, False
    latest = _app_latest_strict(session, key)
    return latest, version, True


def _repo_latest_for_pattern(session: Session, pattern: str) -> RepoRuleVersion | None:
    key = pattern.strip()
    max_v = (
        select(func.max(RepoRuleVersion.version))
        .where(RepoRuleVersion.pattern == key)
        .scalar_subquery()
    )
    return session.scalars(
        select(RepoRuleVersion).where(
            RepoRuleVersion.pattern == key,
            RepoRuleVersion.version == max_v,
        )
    ).first()


def _repo_latest_rows_ordered(session: Session) -> list[RepoRuleVersion]:
    """패턴별 `version = MAX(version)` 행만 조인해 가져온 뒤 sort_order → pattern 정렬."""
    subq = (
        select(
            RepoRuleVersion.pattern.label("p"),
            func.max(RepoRuleVersion.version).label("mv"),
        )
        .group_by(RepoRuleVersion.pattern)
        .subquery()
    )
    rows = session.scalars(
        select(RepoRuleVersion).join(
            subq,
            (RepoRuleVersion.pattern == subq.c.p)
            & (RepoRuleVersion.version == subq.c.mv),
        )
    ).all()
    latest = list(rows)
    latest.sort(key=lambda r: (r.sort_order, r.pattern or ""))
    return latest


def resolve_repo_row(session: Session, repo_url: str) -> RepoRuleVersion | None:
    """
    origin URL 소문자에 패턴 부분문자열이 들어가는 첫 행(정렬 우선).
    없으면 pattern 빈 문자열 스트림의 최신.
    """
    url_l = (repo_url or "").strip().lower()
    rows = _repo_latest_rows_ordered(session)
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
    global_row: GlobalRuleVersion | None,
    repo_row: RepoRuleVersion | None,
    repo_default_row: RepoRuleVersion | None = None,
    app_row: AppRuleVersion | None,
    app_default_row: AppRuleVersion | None = None,
    app_name: str | None,
    notices: list[str],
    meta_extra: list[str],
    three_layer: bool,
    uncertain_git: bool,
) -> str:
    """Assemble markdown for MCP clients (global · optional repo+app stack + optional default 스트림 추가)."""
    meta_parts: list[str] = []
    if global_row is not None:
        meta_parts.append(f"global_served={global_row.version}")
    else:
        meta_parts.append("global_served=(none)")
    meta_parts.extend(meta_extra)
    if three_layer:
        if repo_row is not None:
            meta_parts.append(f"repo_pattern={repo_pattern_card_display(repo_row.pattern)}")
            meta_parts.append(f"repo_served={repo_row.version}")
        else:
            meta_parts.append("repo_served=(none)")
        if repo_default_row is not None and (
            repo_row is None or repo_default_row.id != repo_row.id
        ):
            meta_parts.append(f"repo_default_served={repo_default_row.version}")
    if app_name:
        req_l = app_name.strip().lower()
        meta_parts.append(f"app_name={app_name}")
        # 요청 app 전용 행 없이 __default__ 본문만 쓰는 경우: app_served 에 default 버전을 붙이지 않음
        implicit_default_fallback = (
            app_row is not None
            and req_l != "__default__"
            and app_row.app_name == "__default__"
            and app_default_row is None
        )
        if implicit_default_fallback:
            meta_parts.append("app_named_served=(none)")
            meta_parts.append(f"app_default_served={app_row.version}")
            meta_parts.append("app_stream_resolved=__default__")
        elif app_row is not None:
            meta_parts.append(f"app_served={app_row.version}")
        else:
            meta_parts.append("app_served=(none)")
        if (
            app_default_row is not None
            and req_l != "__default__"
            and (app_row is None or app_default_row.id != app_row.id)
        ):
            meta_parts.append(f"app_default_served={app_default_row.version}")

    meta_line = "<!-- rule_meta: " + ", ".join(meta_parts) + " -->"
    chunks: list[str] = [meta_line]

    if notices:
        chunks.append("\n".join(f"> {n}" for n in notices))

    if global_row is not None:
        global_body = global_row.body
        if three_layer:
            global_body = _GLOBAL_REPO_PREAMBLE.strip() + "\n\n" + global_body
        chunks.append(f"# Global rule (version {global_row.version})\n\n{global_body}")
    else:
        body = _FALLBACK_GLOBAL
        if three_layer:
            body = _GLOBAL_REPO_PREAMBLE.strip() + "\n\n" + body
        chunks.append(f"# Global rule\n\n{body}")

    if three_layer:
        if repo_row is not None:
            disp = repo_pattern_card_display(repo_row.pattern)
            chunks.append(
                f"# Repository rule — pattern `{disp}` (version {repo_row.version})\n\n{repo_row.body}"
            )
        else:
            chunks.append(f"# Repository rule\n\n{_FALLBACK_REPO}")
        if repo_default_row is not None and (
            repo_row is None or repo_default_row.id != repo_row.id
        ):
            chunks.append(
                f"# Repository rule — pattern `default` (version {repo_default_row.version})\n\n"
                f"{repo_default_row.body}"
            )

    if app_name:
        req_l = app_name.strip().lower()
        implicit_default_fallback = (
            app_row is not None
            and req_l != "__default__"
            and app_row.app_name == "__default__"
            and app_default_row is None
        )
        if implicit_default_fallback:
            chunks.append(
                f"# App rule: {app_name}\n\n"
                f"*DB에 `{app_name}` 전용 `app_rule_versions` 행이 **없습니다**. "
                f"아래 **default** (`__default__`) 스트림 본문이 적용된 것입니다.*\n"
            )
            default_body = app_row.body
            if uncertain_git:
                default_body = default_body + _APP_UNCLEAR_FOOTER
            chunks.append(
                f"# App rule: default (version {app_row.version})\n\n{default_body}"
            )
        elif app_row is not None:
            app_body = app_row.body
            if uncertain_git:
                app_body = app_body + _APP_UNCLEAR_FOOTER
            chunks.append(
                f"# App rule: {app_name} (version {app_row.version})\n\n{app_body}"
            )
        else:
            fb = _FALLBACK_APP
            if uncertain_git:
                fb = fb + _APP_UNCLEAR_FOOTER
            chunks.append(f"# App rule: {app_name}\n\n{fb}")
        if (
            app_default_row is not None
            and req_l != "__default__"
            and (app_row is None or app_default_row.id != app_row.id)
        ):
            chunks.append(
                f"# App rule: default (version {app_default_row.version})\n\n{app_default_row.body}"
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
    조회 전용:
    - app_name 없음: global 만 (repo_root / origin_url 무시).
    - app_name 있음: global 최신 + repository(URL 패턴) + 앱 룰.
      - **origin_url** 이 있으면 repository 매칭에만 이걸 쓴다 (에이전트가 `git remote -v` 결과).
      - 없으면 서버 `get_git_context(repo_root)` 의 origin URL 사용.
    """
    trimmed = (app_name or "").strip()
    notices: list[str] = []
    meta_extra: list[str] = []

    if not trimmed:
        g, pin, fb = resolve_global_row(session, version)
        if pin is not None:
            meta_extra.append(f"global_requested={pin}")
        if fb and pin is not None:
            if g is not None:
                notices.append(
                    f"요청한 global 버전 {pin} 이(가) 없어 **최신** global (version {g.version}) 을 반환했습니다."
                )
            else:
                notices.append(
                    f"요청한 global 버전 {pin} 이(가) 없고, 저장된 global 룰도 없습니다."
                )
            meta_extra.append("global_fallback=true")
        elif pin is not None and not fb:
            meta_extra.append("global_fallback=false")

        return build_markdown_response(
            global_row=g,
            repo_row=None,
            repo_default_row=None,
            app_row=None,
            app_default_row=None,
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
                "**에이전트는 워크스페이스에서 `git remote -v` 를 실행한 뒤**, `get_global_rule(..., origin_url=\"origin의_fetch_URL\")` 로 **재호출**하여 Repository 룰을 맞춘다. "
                "(또는 `repo_root` / `GIT_REPO_ROOT` 로 서버가 클론을 보게 할 수 있다.)"
            )

    uncertain = server_uncertain and not agent_origin

    inc_app = get_mcp_include_app_default_for_app(session, trimmed)
    inc_repo = get_mcp_include_repo_default(session)
    meta_extra.append(f"mcp_include_app_default={'true' if inc_app else 'false'}")
    meta_extra.append(f"mcp_include_repo_default={'true' if inc_repo else 'false'}")

    g, _, _ = resolve_global_row(session, None)
    repo_r = resolve_repo_row(session, repo_match_url)

    repo_default_row: RepoRuleVersion | None = None
    if inc_repo:
        repo_fb = _repo_latest_for_pattern(session, "")
        if repo_fb is not None and (repo_r is None or repo_fb.id != repo_r.id):
            repo_default_row = repo_fb

    app_default_row: AppRuleVersion | None = None
    if inc_app and trimmed.lower() != "__default__":
        a, app_pin, app_fb = resolve_app_row_named_only(session, trimmed, version)
        def_row = _app_latest_strict(session, "__default__")
        if def_row is not None and (a is None or def_row.id != a.id):
            app_default_row = def_row
    else:
        a, app_pin, app_fb = resolve_app_row(session, trimmed, version)

    meta_extra.append("global_mode=latest_for_app_context")
    if app_pin is not None:
        meta_extra.append(f"app_requested={app_pin}")
    if app_fb and app_pin is not None:
        if a is not None:
            notices.append(
                f"요청한 앱 `{trimmed}` 버전 {app_pin} 이(가) 없어 **해당 앱 최신** (version {a.version}) 을 반환했습니다."
            )
        else:
            notices.append(
                f"요청한 앱 `{trimmed}` 버전 {app_pin} 이(가) 없고, 해당 앱·__default__ 최신 룰도 없습니다."
            )
        meta_extra.append("app_fallback=true")
    elif app_pin is not None and not app_fb:
        meta_extra.append("app_fallback=false")

    return build_markdown_response(
        global_row=g,
        repo_row=repo_r,
        repo_default_row=repo_default_row,
        app_row=a,
        app_default_row=app_default_row,
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
    DB에 저장된 **최신** 룰의 버전 번호만 JSON 비교용으로 반환.
    - `app_version`: 요청한 `app_name` **전용** 스트림의 MAX(version) (없으면 null).
    - `app_default_version`: `__default__` 스트림 MAX(version) (해당 앱에 `include_app_default` 켜져 있거나 전용 행이 없을 때 의미 있음).
    - `mcp_include_app_default`: `app_name` 없으면 `null`, 있으면 그 앱의 pull 옵션.
    repository 는 `get_global_rule` 과 동일한 URL 매칭.
    """
    g = _global_latest(session)
    out: dict[str, Any] = {
        "global_version": g.version if g else None,
    }

    trimmed = (app_name or "").strip()
    if not trimmed:
        inc_repo = get_mcp_include_repo_default(session)
        out["app_name"] = None
        out["app_version"] = None
        out["repo_pattern"] = None
        out["repo_version"] = None
        out["mcp_include_app_default"] = None
        out["mcp_include_repo_default"] = inc_repo
        out["app_default_version"] = None
        dr = _repo_latest_for_pattern(session, "") if inc_repo else None
        out["repo_default_version"] = dr.version if dr else None
        return out

    key = trimmed.lower()
    git_ctx = get_git_context(repo_root)
    agent_origin = normalize_agent_origin_url(origin_url)
    if agent_origin:
        repo_match_url = agent_origin
    else:
        repo_match_url = (git_ctx.repo_url or "").strip() or "Unknown"

    repo_r = resolve_repo_row(session, repo_match_url)
    inc_app = get_mcp_include_app_default_for_app(session, trimmed)
    inc_repo = get_mcp_include_repo_default(session)
    out["mcp_include_app_default"] = inc_app
    out["mcp_include_repo_default"] = inc_repo

    if inc_app and key != "__default__":
        an = _app_latest_strict(session, key)
        out["app_version"] = an.version if an else None
        dr_app = _app_latest_strict(session, "__default__")
        out["app_default_version"] = dr_app.version if dr_app else None
    else:
        an = _app_latest_strict(session, key)
        dr_app = _app_latest_strict(session, "__default__")
        if an is not None:
            out["app_version"] = an.version
            out["app_default_version"] = None
        else:
            out["app_version"] = None
            out["app_default_version"] = dr_app.version if dr_app else None

    out["app_name"] = key
    if repo_r is not None:
        out["repo_pattern"] = repo_pattern_card_display(repo_r.pattern)
        out["repo_version"] = repo_r.version
    else:
        out["repo_pattern"] = None
        out["repo_version"] = None

    if inc_repo:
        dr = _repo_latest_for_pattern(session, "")
        out["repo_default_version"] = dr.version if dr else None
    else:
        out["repo_default_version"] = None

    return out


def next_global_version(session: Session) -> int:
    m = session.scalar(select(func.coalesce(func.max(GlobalRuleVersion.version), 0)))
    return int(m or 0) + 1


def next_app_version(session: Session, app_name: str) -> int:
    key = app_name.lower().strip()
    m = session.scalar(
        select(func.max(AppRuleVersion.version)).where(AppRuleVersion.app_name == key)
    )
    return int(m or 0) + 1


def next_repo_version(session: Session, pattern: str) -> int:
    key = pattern.strip()
    m = session.scalar(
        select(func.coalesce(func.max(RepoRuleVersion.version), 0)).where(
            RepoRuleVersion.pattern == key
        )
    )
    return int(m or 0) + 1


def publish_global(session: Session, body: str) -> int:
    """서버가 다음 global 버전 번호를 자동 할당한다 (클라이언트가 지정 불가)."""
    nv = next_global_version(session)
    session.add(GlobalRuleVersion(version=nv, body=body))
    session.commit()
    return nv


def publish_app(session: Session, app_name: str, body: str) -> tuple[str, int]:
    """서버가 해당 앱의 다음 버전 번호를 자동 할당한다 (클라이언트가 지정 불가)."""
    key = app_name.lower().strip()
    if not key:
        raise ValueError("app_name is required")
    nv = next_app_version(session, key)
    session.add(AppRuleVersion(app_name=key, version=nv, body=body))
    session.commit()
    return key, nv


def append_to_app_rule(session: Session, app_name: str, append_markdown: str) -> tuple[str, int]:
    """
    해당 앱 **최신** 룰 본문 뒤에 `append_markdown` 을 이어 붙여 **새 버전**으로 저장.
    기존 행이 없으면 `append_markdown` 만으로 첫 버전이 된다.
    """
    key = app_name.lower().strip()
    if not key:
        raise ValueError("app_name is required")
    addition = (append_markdown or "").strip()
    if not addition:
        raise ValueError("append_markdown is required")
    latest = _app_latest(session, key)
    if latest is None:
        new_body = addition
    else:
        new_body = latest.body.rstrip() + "\n\n" + addition
    return publish_app(session, key, new_body)


def publish_repo(
    session: Session,
    pattern: str,
    body: str,
    *,
    sort_order: int | None = None,
) -> tuple[str, int]:
    """패턴별 다음 버전. 첫 버전이고 sort_order 주면 정렬값 설정, 이후는 직전 MAX 행과 동일 sort_order."""
    key = pattern.strip()
    nv = next_repo_version(session, key)
    max_v = (
        select(func.max(RepoRuleVersion.version))
        .where(RepoRuleVersion.pattern == key)
        .scalar_subquery()
    )
    prev = session.scalars(
        select(RepoRuleVersion).where(
            RepoRuleVersion.pattern == key,
            RepoRuleVersion.version == max_v,
        )
    ).first()
    if nv == 1 and sort_order is not None:
        so = sort_order
    elif prev is not None:
        so = prev.sort_order
    else:
        so = 100
    session.add(
        RepoRuleVersion(pattern=key, version=nv, body=body.strip(), sort_order=so)
    )
    session.commit()
    return key, nv


def list_distinct_apps(session: Session) -> list[str]:
    rows = session.scalars(select(AppRuleVersion.app_name).distinct()).all()
    return sorted({r for r in rows if r})


def list_distinct_repo_patterns(session: Session) -> list[str]:
    rows = session.scalars(select(RepoRuleVersion.pattern).distinct()).all()
    return sorted(
        {r for r in rows if r is not None},
        key=lambda p: (0 if (p or "").strip() else 1, (p or "").lower()),
    )
