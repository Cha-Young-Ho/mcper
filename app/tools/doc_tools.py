"""MCP tools: get_global_doc + publish_*_doc + list_doc_sections.

Docs = 일반 문서 (레퍼런스, 가이드, 메모 등 자유 형식 문서)
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.db.database import SessionLocal
from app.services.mcp_tool_stats import record_mcp_tool_call
from app.tools._auth_check import check_read, check_write
from app.services.versioned_docs import (
    DEFAULT_SECTION,
    get_docs_markdown,
    list_sections_for_app_doc,
    list_sections_for_global_doc,
    list_sections_for_repo_doc,
    list_distinct_repo_patterns_with_docs,
    publish_app_doc,
    publish_global_doc,
    publish_repo_doc,
    search_docs as _search_docs,
    update_app_doc,
)


def _normalize_app_name(raw: str) -> str:
    s = raw.strip().strip('"').strip("'")
    if "/" in s:
        s = s.split("/", 1)[0].strip()
    return s


def register_doc_tools(mcp: FastMCP) -> None:
    """FastMCP 인스턴스에 Docs MCP 툴을 등록한다."""

    @mcp.tool()
    def get_global_doc(
        app_name: str | None = None,
        origin_url: str | None = None,
    ) -> str:
        """
        문서(Docs)를 로드한다.

        문서는 자유 형식의 레퍼런스·가이드·메모를 담는다.
        Workflows(워크플로우), Skills(스킬), Rules(규칙)과는 별개의 카테고리다.

        반환 규칙:
        - 항상 Global Docs 포함
        - origin_url 이 있으면 매칭되는 Repo Docs 포함
        - app_name 이 있으면 해당 App Docs 포함

        Args:
            app_name: INI의 app_name (없으면 Global + Repo만)
            origin_url: git remote -v 의 origin fetch URL (Repo Docs 매칭용)
        """
        record_mcp_tool_call("get_global_doc")
        trimmed = _normalize_app_name(app_name or "")
        with SessionLocal() as db:
            denied = check_read(db, app_name=trimmed or None)
            if denied:
                return denied
            return get_docs_markdown(
                db,
                app_name=trimmed or None,
                origin_url=(origin_url or "").strip() or None,
            )

    @mcp.tool()
    def list_doc_sections(
        scope: str = "global",
        app_name: str | None = None,
        origin_url: str | None = None,
    ) -> str:
        """
        등록된 Docs 카테고리 목록을 반환한다.

        Args:
            scope: "global" | "app" | "repo"
            app_name: scope=="app" 시 필수
            origin_url: scope=="repo" 시 패턴 매칭에 사용
        """
        record_mcp_tool_call("list_doc_sections")
        with SessionLocal() as db:
            denied = check_read(db, app_name=_normalize_app_name(app_name or "") or None)
            if denied:
                return denied
            if scope == "app":
                if not app_name:
                    return "app_name 이 필요합니다."
                key = _normalize_app_name(app_name)
                sections = list_sections_for_app_doc(db, key)
            elif scope == "repo":
                patterns = list_distinct_repo_patterns_with_docs(db)
                if origin_url:
                    patterns = [p for p in patterns if p and p in origin_url]
                    if not patterns:
                        patterns = [""]
                sections_by_pat: dict[str, list[str]] = {}
                for pat in patterns:
                    sections_by_pat[pat or "(default)"] = list_sections_for_repo_doc(db, pat)
                lines = []
                for pat, secs in sections_by_pat.items():
                    lines.append(f"패턴: {pat}")
                    for s in secs:
                        lines.append(f"  - {s}")
                return "\n".join(lines) or "등록된 Repo Docs 없음"
            else:
                sections = list_sections_for_global_doc(db)

            if not sections:
                return f"{scope} Docs 카테고리 없음"
            return f"{scope} Docs 카테고리:\n" + "\n".join(f"  - {s}" for s in sections)

    @mcp.tool()
    def publish_global_doc_tool(body: str, section_name: str = DEFAULT_SECTION) -> str:
        """
        Global Doc 새 버전을 발행한다.

        Args:
            body: Markdown 본문
            section_name: 카테고리 이름 (기본: "main")
        """
        record_mcp_tool_call("publish_global_doc")
        with SessionLocal() as db:
            denied = check_write(db)
            if denied:
                return denied
            nv = publish_global_doc(db, body, section_name)
            return f"Global Doc [{section_name}] v{nv} 발행 완료"

    @mcp.tool()
    def publish_app_doc_tool(
        app_name: str, body: str, section_name: str = DEFAULT_SECTION
    ) -> str:
        """
        App Doc 새 버전을 발행한다.

        Args:
            app_name: 앱 이름 (INI의 app_name)
            body: Markdown 본문
            section_name: 카테고리 이름 (기본: "main")
        """
        record_mcp_tool_call("publish_app_doc")
        key = _normalize_app_name(app_name)
        with SessionLocal() as db:
            denied = check_write(db, app_name=key)
            if denied:
                return denied
            _, sn, nv = publish_app_doc(db, key, body, section_name)
            return f"App Doc [{key}/{sn}] v{nv} 발행 완료"

    @mcp.tool()
    def search_docs(
        query: str,
        app_name: str | None = None,
        scope: str = "all",
        top_n: int = 10,
    ) -> str:
        """
        문서를 검색한다 (키워드 기반).

        section_name과 body 내용에서 키워드 매칭으로 검색.

        Args:
            query: 검색 키워드 (예: "에러", "기획서", "spec")
            app_name: 앱 이름 (scope="app" 시 필수)
            scope: "all" | "global" | "app" | "repo"
            top_n: 최대 결과 수 (기본: 10)
        """
        record_mcp_tool_call("search_docs")
        trimmed = _normalize_app_name(app_name or "")
        with SessionLocal() as db:
            denied = check_read(db, app_name=trimmed or None)
            if denied:
                return denied
            results = _search_docs(db, query, app_name=trimmed or None, scope=scope, top_n=top_n)
            if not results:
                return f"'{query}' 검색 결과 없음"
            lines = [f"문서 검색 결과: {len(results)}건\n"]
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
    def update_doc(
        app_name: str,
        section_name: str,
        body: str,
    ) -> str:
        """
        기존 앱 문서를 수정한다 (새 버전으로 발행).

        기존 문서의 내용을 수정하려면 이 도구를 사용.
        수정된 본문이 새 버전으로 저장되며, 이전 버전은 보존된다.

        Args:
            app_name: 앱 이름 (INI의 app_name)
            section_name: 수정할 문서 카테고리 이름 (예: "spec-implementation", "error-hunt")
            body: 수정된 전체 Markdown 본문
        """
        record_mcp_tool_call("update_doc")
        key = _normalize_app_name(app_name)
        with SessionLocal() as db:
            denied = check_write(db, app_name=key)
            if denied:
                return denied
            _, sn, nv = update_app_doc(db, key, section_name, body)
            return f"App Doc [{key}/{sn}] v{nv} 업데이트 완료 (이전 버전 보존됨)"

    @mcp.tool()
    def publish_repo_doc_tool(
        pattern: str, body: str, section_name: str = DEFAULT_SECTION
    ) -> str:
        """
        Repository Doc 새 버전을 발행한다.

        Args:
            pattern: Repository URL 부분 문자열 (비어있으면 default)
            body: Markdown 본문
            section_name: 카테고리 이름 (기본: "main")
        """
        record_mcp_tool_call("publish_repo_doc")
        with SessionLocal() as db:
            denied = check_write(db)
            if denied:
                return denied
            _, sn, nv = publish_repo_doc(db, pattern.strip(), body, section_name)
            pat_display = pattern.strip() or "(default)"
            return f"Repo Doc [{pat_display}/{sn}] v{nv} 발행 완료"
