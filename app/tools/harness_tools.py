"""MCP tools: MCPER project harness document sync, search, and retrieval.

Also provides upload_harness for publishing local harness files to MCP.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy import cast, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.types import String

from app.db.database import SessionLocal
from app.db.models import Spec
from app.services.celery_client import enqueue_or_index_sync
from app.services.mcp_tool_stats import record_mcp_tool_call
from app.services.search_hybrid import hybrid_spec_search
from app.services.versioned_rules import publish_app
from app.services.versioned_skills import publish_app_skill, publish_repo_skill
from app.tools._auth_check import check_read, check_write

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HARNESS_APP_TARGET = "mcper_harness"
HARNESS_BASE_BRANCH = "main"
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

HARNESS_REGISTRY: list[dict[str, str]] = [
    # Core
    {"name": "CLAUDE.md", "scope": "core", "path": "CLAUDE.md"},
    {"name": "ARCHITECTURE.md", "scope": "core", "path": "ARCHITECTURE.md"},
    {"name": "MEMORY.md", "scope": "core", "path": "MEMORY.md"},
    # Agent
    {"name": "pm.md", "scope": "agent", "path": ".agents/pm.md"},
    {"name": "planner.md", "scope": "agent", "path": ".agents/planner.md"},
    {"name": "senior.md", "scope": "agent", "path": ".agents/senior.md"},
    {"name": "coder.md", "scope": "agent", "path": ".agents/coder.md"},
    {"name": "tester.md", "scope": "agent", "path": ".agents/tester.md"},
    {"name": "infra.md", "scope": "agent", "path": ".agents/infra.md"},
    {"name": "archivist.md", "scope": "agent", "path": ".agents/archivist.md"},
    {"name": "report_template.md", "scope": "agent", "path": ".agents/report_template.md"},
    # Guide
    {"name": "PLANS.md", "scope": "guide", "path": "docs/PLANS.md"},
    {"name": "RELIABILITY.md", "scope": "guide", "path": "docs/RELIABILITY.md"},
    {"name": "SECURITY.md", "scope": "guide", "path": "docs/SECURITY.md"},
    {"name": "QUALITY_SCORE.md", "scope": "guide", "path": "docs/QUALITY_SCORE.md"},
    {"name": "PRODUCT_SENSE.md", "scope": "guide", "path": "docs/PRODUCT_SENSE.md"},
    {"name": "FRONTEND.md", "scope": "guide", "path": "docs/FRONTEND.md"},
    # Design
    {"name": "DESIGN_SUMMARY.md", "scope": "design", "path": "docs/DESIGN_SUMMARY.md"},
    {"name": "DESIGN_CRITICAL_SECURITY.md", "scope": "design", "path": "docs/DESIGN_CRITICAL_SECURITY.md"},
    {"name": "DESIGN_HIGH_REFACTOR.md", "scope": "design", "path": "docs/DESIGN_HIGH_REFACTOR.md"},
    # Principles
    {"name": "core-beliefs.md", "scope": "principles", "path": "docs/design-docs/core-beliefs.md"},
    {"name": "design-index.md", "scope": "principles", "path": "docs/design-docs/index.md"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tags_for_entry(entry: dict[str, str]) -> list[str]:
    """Build related_files tags for a registry entry."""
    return [f"scope:{entry['scope']}", f"path:{entry['path']}"]


def _extract_tag(tags: list[str], prefix: str) -> str | None:
    """Extract value from a tag list by prefix (e.g., 'scope:' -> 'core')."""
    for tag in tags:
        if tag.startswith(prefix):
            return tag[len(prefix) :]
    return None


def _load_harness_specs(db: Session) -> dict[str, Spec]:
    """Load all harness Spec rows, keyed by path tag."""
    stmt = select(Spec).where(Spec.app_target == HARNESS_APP_TARGET)
    rows = list(db.scalars(stmt).all())
    result: dict[str, Spec] = {}
    for row in rows:
        path = _extract_tag(row.related_files or [], "path:")
        if path:
            result[path] = row
    return result


def _ilike_pattern(term: str) -> str:
    """Build ILIKE pattern with % / _ escaped."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def sync_harness_docs_impl() -> str:
    """Sync filesystem harness files to DB. Idempotent."""
    record_mcp_tool_call("sync_harness_docs")
    with SessionLocal() as _db:
        denied = check_write(_db)
        if denied:
            return denied
    db: Session = SessionLocal()
    inserted = 0
    updated = 0
    unchanged = 0
    errors: list[str] = []
    try:
        existing = _load_harness_specs(db)

        for entry in HARNESS_REGISTRY:
            filepath = _REPO_ROOT / entry["path"]
            if not filepath.is_file():
                errors.append(f"file not found: {entry['path']}")
                continue

            content = filepath.read_text(encoding="utf-8").replace("\r\n", "\n")
            tags = _tags_for_entry(entry)
            title = entry["name"].removesuffix(".md")

            spec = existing.get(entry["path"])
            if spec is not None:
                if spec.content == content:
                    unchanged += 1
                    continue
                # Content changed — update
                spec.content = content
                spec.title = title
                spec.related_files = tags
                db.commit()
                enqueue_or_index_sync(spec.id)
                updated += 1
                logger.info("harness updated: %s (id=%s)", entry["path"], spec.id)
            else:
                # New entry — insert
                row = Spec(
                    title=title,
                    content=content,
                    app_target=HARNESS_APP_TARGET,
                    base_branch=HARNESS_BASE_BRANCH,
                    related_files=tags,
                )
                db.add(row)
                db.commit()
                db.refresh(row)
                enqueue_or_index_sync(row.id)
                inserted += 1
                logger.info("harness inserted: %s (id=%s)", entry["path"], row.id)

        return json.dumps(
            {
                "ok": True,
                "inserted": inserted,
                "updated": updated,
                "unchanged": unchanged,
                "errors": errors,
                "total_registry": len(HARNESS_REGISTRY),
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        db.rollback()
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


def search_harness_docs_impl(query: str, scope: str | None = None) -> str:
    """Hybrid search over harness docs with optional scope filter."""
    record_mcp_tool_call("search_harness_docs")
    db: Session = SessionLocal()
    try:
        denied = check_read(db)
        if denied:
            return denied
        top_n = 20 if scope else 10
        chunks, mode = hybrid_spec_search(
            db, query=query, app_target=HARNESS_APP_TARGET, top_n=top_n
        )

        if mode == "hybrid_ok" and chunks:
            if scope:
                scope_tag = f"scope:{scope}"
                chunks = [
                    c
                    for c in chunks
                    if scope_tag in (c.get("related_files") or [])
                ]
            return json.dumps(
                {
                    "ok": True,
                    "search_mode": "hybrid_rrf",
                    "count": len(chunks),
                    "chunks": chunks,
                },
                ensure_ascii=False,
            )

        # Fallback: ILIKE on harness specs
        pattern = _ilike_pattern(query)
        json_text = cast(Spec.related_files, String)
        stmt = (
            select(Spec)
            .where(Spec.app_target == HARNESS_APP_TARGET)
            .where(
                or_(
                    Spec.content.ilike(pattern, escape="\\"),
                    Spec.title.ilike(pattern, escape="\\"),
                    json_text.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Spec.id.desc())
            .limit(30)
        )
        rows = list(db.scalars(stmt).all())

        if scope:
            scope_tag = f"scope:{scope}"
            rows = [r for r in rows if scope_tag in (r.related_files or [])]

        results = [
            {
                "id": r.id,
                "title": r.title,
                "scope": _extract_tag(r.related_files or [], "scope:"),
                "path": _extract_tag(r.related_files or [], "path:"),
                "content": r.content[:500],
                "content_length": len(r.content),
            }
            for r in rows
        ]
        sm = "legacy_ilike_supplement" if mode == "indexed_no_match" else "legacy_ilike"
        return json.dumps(
            {
                "ok": True,
                "search_mode": sm,
                "count": len(results),
                "results": results,
                "chunks": [],
                "hybrid_note": mode,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


def get_harness_config_impl(target: str) -> str:
    """Retrieve full content of a specific harness doc by name."""
    record_mcp_tool_call("get_harness_config")
    db: Session = SessionLocal()
    try:
        denied = check_read(db)
        if denied:
            return denied
        stmt = select(Spec).where(Spec.app_target == HARNESS_APP_TARGET)
        rows = list(db.scalars(stmt).all())

        if not rows:
            return json.dumps(
                {
                    "ok": False,
                    "error": "no harness docs registered — run sync_harness_docs first",
                },
                ensure_ascii=False,
            )

        # Normalize target
        t = target.strip().removesuffix(".md").lower()

        # 1st: exact title match (case-insensitive)
        for row in rows:
            if (row.title or "").lower() == t:
                return _harness_config_response(row)

        # 2nd: path stem match
        for row in rows:
            path = _extract_tag(row.related_files or [], "path:")
            if path:
                stem = Path(path).stem.lower()
                if stem == t:
                    return _harness_config_response(row)

        # 3rd: partial match on title
        for row in rows:
            if t in (row.title or "").lower():
                return _harness_config_response(row)

        available = sorted({row.title or "?" for row in rows})
        return json.dumps(
            {
                "ok": False,
                "error": f"harness doc '{target}' not found",
                "available": available,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


def _harness_config_response(row: Spec) -> str:
    """Format a single harness doc for get_harness_config response."""
    tags = row.related_files or []
    return json.dumps(
        {
            "ok": True,
            "title": row.title,
            "scope": _extract_tag(tags, "scope:"),
            "path": _extract_tag(tags, "path:"),
            "content": row.content,
            "content_length": len(row.content),
        },
        ensure_ascii=False,
    )


def list_harness_docs_impl() -> str:
    """List all registered harness docs."""
    record_mcp_tool_call("list_harness_docs")
    db: Session = SessionLocal()
    try:
        denied = check_read(db)
        if denied:
            return denied
        stmt = (
            select(Spec)
            .where(Spec.app_target == HARNESS_APP_TARGET)
            .order_by(Spec.id)
        )
        rows = list(db.scalars(stmt).all())
        docs = []
        for row in rows:
            tags = row.related_files or []
            docs.append(
                {
                    "id": row.id,
                    "title": row.title,
                    "scope": _extract_tag(tags, "scope:"),
                    "path": _extract_tag(tags, "path:"),
                    "content_length": len(row.content),
                }
            )
        return json.dumps(
            {"ok": True, "count": len(docs), "docs": docs},
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


def upload_harness_impl(
    app_name: str,
    files: list[dict[str, str]],
    origin_url: str | None = None,
) -> str:
    """Upload local harness files to MCP as skills and/or rules.

    Each file dict has:
      - path: relative file path (e.g., ".claude/ARCHITECTURE.md")
      - content: file content
      - type: "skill" | "rule" (default: "skill")
      - scope: "app" | "repo" (default: "app")
      - section_name: skill/rule section name (default: derived from path)
    """
    record_mcp_tool_call("upload_harness")
    db: Session = SessionLocal()
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        app_key = app_name.strip().lower()
        denied = check_write(db, app_name=app_key or None)
        if denied:
            return denied
        if not app_key:
            return json.dumps(
                {"ok": False, "error": "app_name is required"},
                ensure_ascii=False,
            )

        # Derive repo pattern from origin_url if provided
        repo_pattern = ""
        if origin_url:
            url = origin_url.strip()
            # Extract repo name: git@github.com:org/repo.git -> repo
            for sep in ["/", ":"]:
                if sep in url:
                    candidate = url.rsplit(sep, 1)[-1]
                    candidate = candidate.removesuffix(".git").strip()
                    if candidate:
                        repo_pattern = candidate
                        break

        for i, f in enumerate(files):
            try:
                path = f.get("path", f"file_{i}")
                content = f.get("content", "")
                file_type = f.get("type", "skill")
                scope = f.get("scope", "app")
                section_name = f.get("section_name", "")

                if not content.strip():
                    errors.append(f"empty content: {path}")
                    continue

                # Derive section_name from path if not provided
                if not section_name:
                    stem = Path(path).stem.lower()
                    # Remove common prefixes
                    for prefix in ("skill", "rule"):
                        stem = stem.removeprefix(prefix).strip("-_")
                    section_name = stem or "main"

                if file_type == "rule":
                    if scope == "repo" and repo_pattern:
                        _, sn, v = publish_repo_rule_entry(
                            db, repo_pattern, content, section_name
                        )
                        results.append({
                            "path": path,
                            "type": "rule",
                            "scope": "repo",
                            "pattern": repo_pattern,
                            "section": sn,
                            "version": v,
                        })
                    else:
                        _, sn, v = publish_app(db, app_key, content, section_name)
                        results.append({
                            "path": path,
                            "type": "rule",
                            "scope": "app",
                            "app_name": app_key,
                            "section": sn,
                            "version": v,
                        })
                else:  # skill
                    if scope == "repo" and repo_pattern:
                        _, sn, v = publish_repo_skill(
                            db, repo_pattern, content, section_name
                        )
                        results.append({
                            "path": path,
                            "type": "skill",
                            "scope": "repo",
                            "pattern": repo_pattern,
                            "section": sn,
                            "version": v,
                        })
                    else:
                        _, sn, v = publish_app_skill(
                            db, app_key, content, section_name
                        )
                        results.append({
                            "path": path,
                            "type": "skill",
                            "scope": "app",
                            "app_name": app_key,
                            "section": sn,
                            "version": v,
                        })

            except Exception as exc:
                errors.append(f"{path}: {exc}")

        return json.dumps(
            {
                "ok": True,
                "uploaded": len(results),
                "errors": errors,
                "results": results,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        db.rollback()
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


def publish_repo_rule_entry(
    db: Session, pattern: str, body: str, section_name: str
) -> tuple[str, str, int]:
    """Wrapper for publish_repo with keyword args."""
    from app.services.versioned_rules import publish_repo
    return publish_repo(db, pattern, body, section_name=section_name)


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register_harness_tools(mcp: FastMCP) -> None:
    """Register harness doc tools on a FastMCP instance."""

    @mcp.tool()
    def sync_harness_docs() -> str:
        """
        MCPER 프로젝트의 하네스 파일(CLAUDE.md, .agents/*.md, docs/*.md 등)을
        DB에 동기화한다. 이미 동일한 내용이면 건너뛰고, 변경된 파일만 갱신+재색인한다.

        언제 쓰는가:
        - MCPER 프로젝트 문서가 변경된 후 검색 인덱스를 갱신할 때
        - 최초 하네스 문서 등록 시

        반환: 삽입/갱신/변경없음 건수
        """
        return sync_harness_docs_impl()

    @mcp.tool()
    def search_harness_docs(query: str, scope: str | None = None) -> str:
        """
        MCPER 프로젝트 하네스 문서를 벡터+FTS 하이브리드로 검색한다.

        언제 쓰는가:
        - MCPER의 아키텍처, 규칙, 에이전트 가이드 등을 찾을 때
        - "보안 정책이 뭐야?", "코더 에이전트 역할은?" 같은 질문에 답할 때

        scope (선택): core, agent, guide, design, principles 중 하나로 범위 제한
        """
        return search_harness_docs_impl(query=query, scope=scope)

    @mcp.tool()
    def get_harness_config(target: str) -> str:
        """
        특정 하네스 문서의 전체 내용을 이름으로 가져온다 (부트스트래핑용).

        언제 쓰는가:
        - "CLAUDE.md 내용 보여줘", "pm 에이전트 가이드 가져와" 같은 직접 조회
        - 에이전트 초기화 시 특정 문서를 컨텍스트에 로드할 때

        target: 문서 이름 (예: "CLAUDE", "pm", "ARCHITECTURE", "core-beliefs")
        """
        return get_harness_config_impl(target=target)

    @mcp.tool()
    def list_harness_docs() -> str:
        """
        등록된 모든 하네스 문서 목록을 반환한다 (제목, 범위, 경로, 길이).

        언제 쓰는가:
        - 어떤 하네스 문서가 등록되어 있는지 확인할 때
        - get_harness_config이나 search_harness_docs 전에 문서 이름을 확인할 때
        """
        return list_harness_docs_impl()

    @mcp.tool()
    def upload_harness(
        app_name: str,
        files: list[dict[str, str]],
        origin_url: str | None = None,
    ) -> str:
        """
        로컬 하네스 파일들을 MCP에 일괄 업로드한다 (스킬·룰 등록).

        언제 쓰는가:
        - 로컬에 구축한 하네스(.claude/*, CLAUDE.md 등)를 리모트 MCP에 올릴 때
        - "이 프로젝트 하네스 올려줘", "로컬 스킬 MCP에 등록해줘" 같은 요청
        - 팀원과 하네스를 공유하고 싶을 때

        사용법:
        (1) 로컬 하네스 파일들을 읽는다 (.claude/agents/*.md, .claude/skills/*/skill.md, .claude/docs/*.md 등)
        (2) 각 파일을 files 배열에 담아 호출한다

        files 배열의 각 항목:
        - path: 파일 경로 (예: ".claude/agents/code.md") — 식별용
        - content: 파일 내용 전체
        - type: "skill" (기본값) 또는 "rule"
        - scope: "app" (기본값) 또는 "repo" (origin_url 필요)
        - section_name: 섹션 이름 (생략 시 파일명에서 자동 추출)

        예시:
        upload_harness(
            app_name="my_app",
            origin_url="git@github.com:org/my-repo.git",
            files=[
                {"path": ".claude/agents/code.md", "content": "...", "type": "skill", "section_name": "agent-code"},
                {"path": ".claude/docs/SECURITY.md", "content": "...", "type": "skill", "section_name": "security"},
                {"path": ".claude/rules/event.md", "content": "...", "type": "rule", "section_name": "event"},
            ]
        )

        반환: 업로드 건수, 에러 목록, 각 파일별 결과 (scope, section, version)
        """
        return upload_harness_impl(
            app_name=app_name, files=files, origin_url=origin_url
        )
