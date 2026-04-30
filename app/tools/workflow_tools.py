"""MCP tools: get_global_workflow + publish_*_workflow + list_workflow_sections.

Workflows = 오케스트레이터 (작업별 에이전트 팀, 실행 순서, 기본 스킬)
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.db.database import SessionLocal
from app.services.mcp_tool_stats import record_mcp_tool_call
from app.tools._auth_check import check_read, check_write
from app.services.versioned_workflows import (
    DEFAULT_SECTION,
    get_workflow_mermaid,
    get_workflows_markdown,
    list_sections_for_app_workflow,
    list_sections_for_global_workflow,
    list_sections_for_repo_workflow,
    list_distinct_repo_patterns_with_workflows,
    publish_app_workflow,
    publish_global_workflow,
    publish_repo_workflow,
    search_workflows as _search_workflows,
    set_workflow_mermaid,
    update_app_workflow,
)
from app.tools._common import _normalize_app_name


def register_workflow_tools(mcp: FastMCP) -> None:
    """FastMCP 인스턴스에 Workflows MCP 툴을 등록한다."""

    @mcp.tool()
    def get_global_workflow(
        app_name: str | None = None,
        origin_url: str | None = None,
    ) -> str:
        """
        워크플로우(Workflows)를 로드한다.

        워크플로우는 작업별 오케스트레이터로, 에이전트 팀 구성·실행 순서·기본 스킬 등을 정의한다.
        Skills(스킬)과 Rules(규칙)은 별도 도구로 관리된다.

        반환 규칙:
        - 항상 Global Workflows 포함
        - origin_url 이 있으면 매칭되는 Repo Workflows 포함
        - app_name 이 있으면 해당 App Workflows 포함

        워크플로우 실행 중 필요한 스킬은 search_skills 로 on-demand 검색하여 사용.

        Args:
            app_name: INI의 app_name (없으면 Global + Repo만)
            origin_url: git remote -v 의 origin fetch URL (Repo Workflows 매칭용)
        """
        record_mcp_tool_call("get_global_workflow")
        trimmed = _normalize_app_name(app_name or "")
        with SessionLocal() as db:
            denied = check_read(db, app_name=trimmed or None)
            if denied:
                return denied
            return get_workflows_markdown(
                db,
                app_name=trimmed or None,
                origin_url=(origin_url or "").strip() or None,
            )

    @mcp.tool()
    def list_workflow_sections(
        scope: str = "global",
        app_name: str | None = None,
        origin_url: str | None = None,
    ) -> str:
        """
        등록된 Workflows 카테고리 목록을 반환한다.

        Args:
            scope: "global" | "app" | "repo"
            app_name: scope=="app" 시 필수
            origin_url: scope=="repo" 시 패턴 매칭에 사용
        """
        record_mcp_tool_call("list_workflow_sections")
        with SessionLocal() as db:
            denied = check_read(
                db, app_name=_normalize_app_name(app_name or "") or None
            )
            if denied:
                return denied
            if scope == "app":
                if not app_name:
                    return "app_name 이 필요합니다."
                key = _normalize_app_name(app_name)
                sections = list_sections_for_app_workflow(db, key)
            elif scope == "repo":
                patterns = list_distinct_repo_patterns_with_workflows(db)
                if origin_url:
                    patterns = [p for p in patterns if p and p in origin_url]
                    if not patterns:
                        patterns = [""]
                sections_by_pat: dict[str, list[str]] = {}
                for pat in patterns:
                    sections_by_pat[pat or "(default)"] = (
                        list_sections_for_repo_workflow(db, pat)
                    )
                lines = []
                for pat, secs in sections_by_pat.items():
                    lines.append(f"패턴: {pat}")
                    for s in secs:
                        lines.append(f"  - {s}")
                return "\n".join(lines) or "등록된 Repo Workflows 없음"
            else:
                sections = list_sections_for_global_workflow(db)

            if not sections:
                return f"{scope} Workflows 카테고리 없음"
            return f"{scope} Workflows 카테고리:\n" + "\n".join(
                f"  - {s}" for s in sections
            )

    @mcp.tool()
    def publish_global_workflow_tool(
        body: str, section_name: str = DEFAULT_SECTION
    ) -> str:
        """
        Global Workflow 새 버전을 발행한다.

        Args:
            body: Markdown 본문
            section_name: 카테고리 이름 (기본: "main")
        """
        record_mcp_tool_call("publish_global_workflow")
        with SessionLocal() as db:
            denied = check_write(db)
            if denied:
                return denied
            nv = publish_global_workflow(db, body, section_name)
            return f"Global Workflow [{section_name}] v{nv} 발행 완료"

    @mcp.tool()
    def publish_app_workflow_tool(
        app_name: str, body: str, section_name: str = DEFAULT_SECTION
    ) -> str:
        """
        App Workflow 새 버전을 발행한다.

        Args:
            app_name: 앱 이름 (INI의 app_name)
            body: Markdown 본문
            section_name: 카테고리 이름 (기본: "main")
        """
        record_mcp_tool_call("publish_app_workflow")
        key = _normalize_app_name(app_name)
        with SessionLocal() as db:
            denied = check_write(db, app_name=key)
            if denied:
                return denied
            _, sn, nv = publish_app_workflow(db, key, body, section_name)
            return f"App Workflow [{key}/{sn}] v{nv} 발행 완료"

    @mcp.tool()
    def search_workflows(
        query: str,
        app_name: str | None = None,
        scope: str = "all",
        top_n: int = 10,
    ) -> str:
        """
        워크플로우를 검색한다 (키워드 기반).

        section_name과 body 내용에서 키워드 매칭으로 검색.

        Args:
            query: 검색 키워드 (예: "에러", "기획서", "spec")
            app_name: 앱 이름 (scope="app" 시 필수)
            scope: "all" | "global" | "app" | "repo"
            top_n: 최대 결과 수 (기본: 10)
        """
        record_mcp_tool_call("search_workflows")
        trimmed = _normalize_app_name(app_name or "")
        with SessionLocal() as db:
            denied = check_read(db, app_name=trimmed or None)
            if denied:
                return denied
            results = _search_workflows(
                db, query, app_name=trimmed or None, scope=scope, top_n=top_n
            )
            if not results:
                return f"'{query}' 검색 결과 없음"
            lines = [f"워크플로우 검색 결과: {len(results)}건\n"]
            for r in results:
                scope_label = r["scope"]
                sn = r["section_name"]
                ver = r["version"]
                prefix = f"[{scope_label}] {sn} v{ver}"
                if r.get("app_name"):
                    prefix = f"[{scope_label}/{r['app_name']}] {sn} v{ver}"
                elif r.get("pattern"):
                    prefix = f"[{scope_label}/{r['pattern']}] {sn} v{ver}"
                body_preview = r["body"][:300].replace("\n", " ")
                lines.append(f"- {prefix}: {body_preview}...")
            return "\n".join(lines)

    @mcp.tool()
    def update_workflow(
        app_name: str,
        section_name: str,
        body: str,
    ) -> str:
        """
        기존 앱 워크플로우를 수정한다 (새 버전으로 발행).

        기존 워크플로우의 내용을 수정하려면 이 도구를 사용.
        수정된 본문이 새 버전으로 저장되며, 이전 버전은 보존된다.

        Args:
            app_name: 앱 이름 (INI의 app_name)
            section_name: 수정할 워크플로우 카테고리 이름 (예: "spec-implementation", "error-hunt")
            body: 수정된 전체 Markdown 본문
        """
        record_mcp_tool_call("update_workflow")
        key = _normalize_app_name(app_name)
        with SessionLocal() as db:
            denied = check_write(db, app_name=key)
            if denied:
                return denied
            _, sn, nv = update_app_workflow(db, key, section_name, body)
            return f"App Workflow [{key}/{sn}] v{nv} 업데이트 완료 (이전 버전 보존됨)"

    @mcp.tool()
    def publish_repo_workflow_tool(
        pattern: str, body: str, section_name: str = DEFAULT_SECTION
    ) -> str:
        """
        Repository Workflow 새 버전을 발행한다.

        Args:
            pattern: Repository URL 부분 문자열 (비어있으면 default)
            body: Markdown 본문
            section_name: 카테고리 이름 (기본: "main")
        """
        record_mcp_tool_call("publish_repo_workflow")
        with SessionLocal() as db:
            denied = check_write(db)
            if denied:
                return denied
            _, sn, nv = publish_repo_workflow(db, pattern.strip(), body, section_name)
            pat_display = pattern.strip() or "(default)"
            return f"Repo Workflow [{pat_display}/{sn}] v{nv} 발행 완료"

    @mcp.tool()
    def set_workflow_mermaid_tool(
        scope: str,
        section_name: str,
        version: int,
        mermaid: str,
        app_name: str | None = None,
        pattern: str | None = None,
    ) -> str:
        """
        워크플로우 특정 버전에 Mermaid 다이어그램을 첨부/갱신한다.

        이 도구는 새 워크플로우 버전을 만들지 않고, 기존 버전의 mermaid 필드만
        업데이트한다. 어드민의 "한눈에 보기" 버튼은 이 필드가 채워진 버전에서만
        활성화된다.

        Mermaid 문법 권장:
          flowchart TD
            A[시작] --> B{조건}
            B -->|Yes| C[작업]
            B -->|No| D[종료]

        Args:
            scope: "global" | "app" | "repo"
            section_name: 대상 섹션 이름 (예: "spec-implementation")
            version: 대상 버전 번호
            mermaid: Mermaid 다이어그램 텍스트 전체 (``` 울타리 없이 순수 문법만)
            app_name: scope="app" 시 필수 (INI의 app_name)
            pattern: scope="repo" 시 Repository URL 부분 문자열 (빈 문자열 = default)
        """
        record_mcp_tool_call("set_workflow_mermaid")
        key = _normalize_app_name(app_name or "") or None
        with SessionLocal() as db:
            denied = check_write(db, app_name=key)
            if denied:
                return denied
            ok = set_workflow_mermaid(
                db,
                scope=scope,
                section_name=section_name,
                version=version,
                mermaid=mermaid,
                app_name=key,
                pattern=pattern,
            )
            if not ok:
                return f"대상 워크플로우 버전을 찾지 못했습니다: scope={scope} section={section_name} v{version}"
            target = f"[{scope}]"
            if scope == "app" and key:
                target = f"[{scope}/{key}]"
            elif scope == "repo":
                target = f"[{scope}/{(pattern or '').strip() or '(default)'}]"
            return f"Mermaid 저장 완료: {target} {section_name} v{version}"

    @mcp.tool()
    def get_workflow_mermaid_tool(
        scope: str,
        section_name: str,
        version: int,
        app_name: str | None = None,
        pattern: str | None = None,
    ) -> str:
        """
        워크플로우 특정 버전에 저장된 Mermaid 다이어그램을 조회한다.

        어드민의 "한눈에 보기" 모달이 렌더하는 것과 동일한 텍스트.
        없으면 안내 문자열 반환.

        활용:
        - Claude Code 에서 워크플로우 구조를 텍스트로 빠르게 확인
        - 기존 다이어그램을 참고해 수정본 작성 후 set_workflow_mermaid_tool 로 재업로드
        - 다이어그램 미존재 확인 후 workflow-to-mermaid 스킬로 생성

        Args:
            scope: "global" | "app" | "repo"
            section_name: 대상 섹션 이름 (예: "spec-implementation")
            version: 대상 버전 번호
            app_name: scope="app" 시 필수 (INI의 app_name)
            pattern: scope="repo" 시 Repository URL 부분 문자열 (빈 문자열 = default)

        Returns:
            Mermaid 문법 텍스트 (코드펜스 없음). 미존재 시 안내 메시지.
        """
        record_mcp_tool_call("get_workflow_mermaid")
        key = _normalize_app_name(app_name or "") or None
        with SessionLocal() as db:
            denied = check_read(db, app_name=key)
            if denied:
                return denied
            mmd = get_workflow_mermaid(
                db,
                scope=scope,
                section_name=section_name,
                version=version,
                app_name=key,
                pattern=pattern,
            )
            if not mmd:
                target = scope
                if scope == "app" and key:
                    target = f"{scope}/{key}"
                elif scope == "repo":
                    target = f"{scope}/{(pattern or '').strip() or '(default)'}"
                return (
                    f"[{target}] {section_name} v{version} 에 Mermaid 다이어그램이 없습니다.\n"
                    f"생성하려면 'workflow-to-mermaid' 스킬을 사용해 "
                    f"set_workflow_mermaid_tool 로 업로드하세요."
                )
            return mmd
