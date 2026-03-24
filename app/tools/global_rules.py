"""MCP tools: get_global_rule + publish_* for versioned global/repo/app rules."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from app.db.database import SessionLocal
from app.services.mcp_tool_stats import record_mcp_tool_call
from app.services.versioned_rules import (
    append_to_app_rule as append_app_rule_body,
    get_rule_version_snapshot,
    get_rules_markdown,
    normalize_read_version,
    publish_app,
    publish_global,
    publish_repo,
)

# Cursor 전용 참고 경로 (다른 IDE는 각 제품 문서·CLAUDE.md·.agent/rules 등 사용)
CURSOR_RULE_MDC_PATH = ".cursor/rules/mcp-rules.mdc"
CURSOR_RULE_MDC_PATHS_SPLIT = (
    ".cursor/rules/mcp-rules-global.mdc",
    ".cursor/rules/mcp-rules-repository.mdc",
    ".cursor/rules/mcp-rules-app.mdc",
)


def _normalize_app_name(raw: str) -> str:
    """
    INI `app_name` 값만 사용한다. 따옴표 제거, `your_app_name/master` 같은 입력은 `your_app_name`만 사용.
    """
    s = raw.strip().strip('"').strip("'")
    if "/" in s:
        s = s.split("/", 1)[0].strip()
    return s


def get_global_rule_impl(
    app_name: str | None,
    version: int | str | None,
    repo_root: str | None,
    origin_url: str | None,
) -> str:
    record_mcp_tool_call("get_global_rule")
    trimmed = _normalize_app_name(app_name or "")
    v = normalize_read_version(version)
    rr = (repo_root or "").strip() or None
    ou = (origin_url or "").strip() or None
    db = SessionLocal()
    try:
        return get_rules_markdown(
            db,
            app_name=trimmed if trimmed else None,
            version=v,
            repo_root=rr,
            origin_url=ou,
        )
    finally:
        db.close()


def register_global_rule_tool(mcp: FastMCP) -> None:
    """Expose get_global_rule, check_rule_versions, publish_* , append_to_app_rule."""

    @mcp.tool()
    def get_global_rule(
        app_name: str | None = None,
        version: int | str | None = None,
        repo_root: str | None = None,
        origin_url: str | None = None,
    ) -> str:
        """
        DB에 저장된 룰을 마크다운으로 조회합니다. **버전 번호는 조회할 때만** 지정합니다.

        - `app_name` → **앱 룰** 스트림 (INI 식별자만, 예: your_app_name). `/master` 금지.
        - `app_name` 없음: **global 룰만** (`version`은 global 만).
        - `app_name` 있음: **global 최신** + **repository 룰**(URL 패턴) + **앱 룰** (`version`은 앱 룰만).

        - **`origin_url` (권장, app_name 있을 때):** 에이전트가 워크스페이스에서 **`git remote -v`** 로 얻은 **origin fetch URL**
          (`git@github.com:org/repo.git` 또는 `https://...`). Repository 룰 매칭은 **이 값이 최우선**.
          `git remote -v` 출력 통째로 넘겨도 된다.
        - `repo_root` (선택): 서버가 브랜치 등을 읽을 경로. `origin_url` 없을 때 origin 후보로도 쓰임.

        **저장(발행) 시 버전은 에이전트가 넘기지 않습니다.** `publish_*` 툴이 서버에서 버전을 붙입니다.

        **자연어 트리거:** 룰 **받아와/조회/동기화** → 호출 후 **로컬 파일 저장**까지(명시적 거절 시만 생략).

        **2차 응답:** 응답 말미 **[CRITICAL — …]** 로 환경별 저장.
        """
        return get_global_rule_impl(
            app_name=app_name,
            version=version,
            repo_root=repo_root,
            origin_url=origin_url,
        )

    @mcp.tool()
    def check_rule_versions(
        app_name: str | None = None,
        origin_url: str | None = None,
        repo_root: str | None = None,
    ) -> str:
        """
        서버 DB에 올라와 있는 **최신** 룰의 **버전 번호(정수)** 만 JSON으로 돌려준다.
        로컬에 저장한 `<!-- rule_meta: … -->` 의 `global_served`, `repo_served`, `app_served` 등과 비교해,
        하나라도 다르면 **`get_global_rule` 로 다시 받아와 최신 본문으로 로컬 규칙을 갱신**한다.

        - `app_name` 없음: `global_version` 만 채우고 app/repo 필드는 null. `mcp_include_app_default` 는 null.
        - `app_name` 있음: global + (origin_url/repo_root 로 매칭된) repository + 해당 앱 스트림의 최신 버전.
          `mcp_include_app_default` 는 앱 카드·보드에서 켠 값(앱별 행 없으면 Global 보드 전역 기본).
          `mcp_include_repo_default` 는 매칭된 repository 패턴 카드 설정.

        반환 예: `{"global_version":3,"app_name":"your_app_name","app_version":2,"repo_pattern":"api","repo_version":1}`.
        """
        record_mcp_tool_call("check_rule_versions")
        trimmed = _normalize_app_name(app_name or "")
        rr = (repo_root or "").strip() or None
        ou = (origin_url or "").strip() or None
        db = SessionLocal()
        try:
            snap = get_rule_version_snapshot(
                db,
                app_name=trimmed if trimmed else None,
                origin_url=ou,
                repo_root=rr,
            )
            return json.dumps(snap, ensure_ascii=False)
        finally:
            db.close()

    @mcp.tool()
    def publish_global_rule(body: str) -> str:
        """
        **새 global 룰 버전을 1개 추가**합니다. 버전 번호는 **서버가 자동 부여**하며,
        이 툴에는 `version` 인자가 없습니다(클라이언트가 특정 번호로 저장할 수 없음).
        반환: JSON `{ "scope": "global", "version": N }` (방금 생성된 N).
        """
        record_mcp_tool_call("publish_global_rule")
        db = SessionLocal()
        try:
            v = publish_global(db, body)
            return json.dumps({"scope": "global", "version": v}, ensure_ascii=False)
        finally:
            db.close()

    @mcp.tool()
    def publish_app_rule(app_name: str, body: str) -> str:
        """
        **새 app 룰 버전을 1개 추가**합니다. 버전 번호는 **서버가 해당 앱 기준으로 자동 부여**합니다.
        `version` 인자는 없습니다.
        반환: JSON `{ "scope": "app", "app_name": "...", "version": N }`.
        """
        key = _normalize_app_name(app_name)
        if not key:
            return json.dumps(
                {"error": "app_name is required"},
                ensure_ascii=False,
            )
        record_mcp_tool_call("publish_app_rule")
        db = SessionLocal()
        try:
            name, v = publish_app(db, key, body)
            return json.dumps(
                {"scope": "app", "app_name": name, "version": v},
                ensure_ascii=False,
            )
        finally:
            db.close()

    @mcp.tool()
    def append_to_app_rule(app_name: str, append_markdown: str) -> str:
        """
        해당 앱 룰 **최신 본문 뒤에** `append_markdown` 을 덧붙여 **새 버전**을 저장합니다.
        - **해당 앱이 DB에 없으면** → 넘긴 내용만으로 **버전 1** 행 생성.
        - **이미 있으면** → 최신 본문 + append_markdown 을 **다음 정수 버전**(2, 3, …)으로 저장.
        사용자가 「룰 이거 추가해줘」「your_app_name 앱 룰에 ~~ 추가해줘」처럼 말할 때 사용합니다.
        (전체 본문을 갈아엎을 때는 `publish_app_rule` 에 전체 `body` 를 넘기세요.)
        반환: JSON `{ "scope": "app", "app_name": "...", "version": N, "appended": true }`.
        """
        key = _normalize_app_name(app_name)
        if not key:
            return json.dumps(
                {"error": "app_name is required"},
                ensure_ascii=False,
            )
        record_mcp_tool_call("append_to_app_rule")
        db = SessionLocal()
        try:
            name, v = append_app_rule_body(db, key, append_markdown)
            return json.dumps(
                {
                    "scope": "app",
                    "app_name": name,
                    "version": v,
                    "appended": True,
                },
                ensure_ascii=False,
            )
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        finally:
            db.close()

    @mcp.tool()
    def publish_repo_rule(pattern: str, body: str) -> str:
        """
        **새 repository 룰 버전을 1개 추가**합니다. `pattern` 은 `git remote` origin URL에 포함되면
        매칭되는 **부분문자열**(소문자 비교). 빈 패턴은 URL에 다른 패턴이 안 맞을 때 **폴백**으로 쓰입니다.
        버전은 **패턴별**로 서버가 자동 증가합니다.
        반환: JSON `{ "scope": "repo", "pattern": "...", "version": N }`.
        """
        record_mcp_tool_call("publish_repo_rule")
        key = (pattern or "").strip()
        db = SessionLocal()
        try:
            p, v = publish_repo(db, key, body)
            return json.dumps(
                {"scope": "repo", "pattern": p, "version": v},
                ensure_ascii=False,
            )
        finally:
            db.close()
