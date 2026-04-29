"""MCP tools: get_global_skill + publish_*_skill.

Skills = 스킬 / 시스템 이해 (Rules = 행동 지침과 완전 구분)

반환 형식:
- 카테고리별 독립 파일 블록
- 에이전트는 각 블록을 지정 경로에 저장
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import json

from app.db.database import SessionLocal
from app.services.mcp_tool_stats import record_mcp_tool_call
from app.tools._auth_check import check_read, check_write
from app.services.versioned_skills import (
    DEFAULT_SECTION,
    get_skills_markdown,
    list_sections_for_app_skill,
    list_sections_for_global_skill,
    list_sections_for_repo_skill,
    publish_app_skill,
    publish_global_skill,
    publish_repo_skill,
)
from app.tools._common import _normalize_app_name


def register_skill_tools(mcp: FastMCP) -> None:
    """FastMCP 인스턴스에 Skills MCP 툴을 등록한다."""

    @mcp.tool()
    def get_global_skill(
        app_name: str | None = None,
        origin_url: str | None = None,
    ) -> str:
        """
        스킬(Skills)을 로드한다.

        get_global_rule 과 별개로 동작하며 카테고리별 독립 파일 블록을 반환한다.

        반환 규칙:
        - 항상 Global Skills 포함
        - origin_url 이 있으면 매칭되는 Repo Skills 포함
        - app_name 이 있으면 해당 App Skills 포함

        [CRITICAL] 반환된 SKILL FILE 블록을 각각 지정된 경로에 저장할 것.
        저장 후 .cursor/skills/ 폴더가 에이전트 컨텍스트로 자동 로드된다.

        Args:
            app_name: INI의 app_name (없으면 Global + Repo만)
            origin_url: git remote -v 의 origin fetch URL (Repo Skills 매칭용)
        """
        record_mcp_tool_call("get_global_skill")
        trimmed = _normalize_app_name(app_name or "")
        with SessionLocal() as db:
            denied = check_read(db, app_name=trimmed or None)
            if denied:
                return denied
            return get_skills_markdown(
                db,
                app_name=trimmed or None,
                origin_url=(origin_url or "").strip() or None,
            )

    @mcp.tool()
    def list_skill_sections(
        scope: str = "global",
        app_name: str | None = None,
        origin_url: str | None = None,
    ) -> str:
        """
        등록된 Skills 카테고리 목록을 반환한다.

        Args:
            scope: "global" | "app" | "repo"
            app_name: scope=="app" 시 필수
            origin_url: scope=="repo" 시 패턴 매칭에 사용
        """
        record_mcp_tool_call("list_skill_sections")
        with SessionLocal() as db:
            denied = check_read(db, app_name=_normalize_app_name(app_name or "") or None)
            if denied:
                return denied
            if scope == "app":
                if not app_name:
                    return "app_name 이 필요합니다."
                key = _normalize_app_name(app_name)
                sections = list_sections_for_app_skill(db, key)
            elif scope == "repo":
                from app.services.versioned_skills import list_distinct_repo_patterns_with_skills
                patterns = list_distinct_repo_patterns_with_skills(db)
                if origin_url:
                    patterns = [p for p in patterns if p and p in origin_url]
                    if not patterns:
                        patterns = [""]
                sections_by_pat: dict[str, list[str]] = {}
                for pat in patterns:
                    sections_by_pat[pat or "(default)"] = list_sections_for_repo_skill(db, pat)
                lines = []
                for pat, secs in sections_by_pat.items():
                    lines.append(f"패턴: {pat}")
                    for s in secs:
                        lines.append(f"  - {s}")
                return "\n".join(lines) or "등록된 Repo Skills 없음"
            else:
                sections = list_sections_for_global_skill(db)

            if not sections:
                return f"{scope} Skills 카테고리 없음"
            return f"{scope} Skills 카테고리:\n" + "\n".join(f"  - {s}" for s in sections)

    @mcp.tool()
    def publish_global_skill_tool(body: str, section_name: str = DEFAULT_SECTION) -> str:
        """
        Global Skills 새 버전을 발행한다.

        Args:
            body: Markdown 본문
            section_name: 카테고리 이름 (기본: "main")
        """
        record_mcp_tool_call("publish_global_skill")
        with SessionLocal() as db:
            denied = check_write(db)
            if denied:
                return denied
            nv = publish_global_skill(db, body, section_name)
            return f"Global Skill [{section_name}] v{nv} 발행 완료"

    @mcp.tool()
    def publish_app_skill_tool(
        app_name: str, body: str, section_name: str = DEFAULT_SECTION
    ) -> str:
        """
        App Skills 새 버전을 발행한다.

        Args:
            app_name: 앱 이름 (INI의 app_name)
            body: Markdown 본문
            section_name: 카테고리 이름 (기본: "main")
        """
        record_mcp_tool_call("publish_app_skill")
        key = _normalize_app_name(app_name)
        with SessionLocal() as db:
            denied = check_write(db, app_name=key)
            if denied:
                return denied
            _, sn, nv = publish_app_skill(db, key, body, section_name)
            return f"App Skill [{key}/{sn}] v{nv} 발행 완료"

    @mcp.tool()
    def publish_repo_skill_tool(
        pattern: str, body: str, section_name: str = DEFAULT_SECTION
    ) -> str:
        """
        Repository Skills 새 버전을 발행한다.

        Args:
            pattern: Repository URL 부분 문자열 (비어있으면 default)
            body: Markdown 본문
            section_name: 카테고리 이름 (기본: "main")
        """
        record_mcp_tool_call("publish_repo_skill")
        with SessionLocal() as db:
            denied = check_write(db)
            if denied:
                return denied
            _, sn, nv = publish_repo_skill(db, pattern.strip(), body, section_name)
            pat_display = pattern.strip() or "(default)"
            return f"Repo Skill [{pat_display}/{sn}] v{nv} 발행 완료"

    @mcp.tool()
    def search_skills(
        query: str,
        app_name: str | None = None,
        scope: str = "all",
        top_n: int = 10,
    ) -> str:
        """
        스킬을 의미 검색한다 (벡터+FTS 하이브리드).

        get_global_skill 은 전체 스킬을 로드하는 반면,
        search_skills 는 쿼리와 관련된 스킬 청크만 검색해서 반환한다.

        스킬이 많을 때(수십~수백 개) 관련 스킬만 빠르게 찾을 때 사용.

        Args:
            query: 검색 쿼리 (자연어)
            app_name: 특정 앱의 스킬만 검색 (없으면 전체)
            scope: "all" | "global" | "app" | "repo"
            top_n: 반환할 최대 결과 수 (기본 10)
        """
        record_mcp_tool_call("search_skills")
        trimmed = _normalize_app_name(app_name or "")
        with SessionLocal() as db:
            denied = check_read(db, app_name=trimmed or None)
            if denied:
                return denied
            from app.services.search_skills import hybrid_skill_search
            chunks, mode = hybrid_skill_search(
                db,
                query=query,
                app_name=trimmed or None,
                scope=scope,
                top_n=top_n,
            )
            return json.dumps(
                {
                    "ok": True,
                    "search_mode": mode,
                    "count": len(chunks),
                    "chunks": chunks,
                },
                ensure_ascii=False,
            )
