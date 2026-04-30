"""MCP tools: code graph push, impact analysis, historical spec reference."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import Spec
from app.db.rag_models import SpecChunk
from app.services.celery_client import enqueue_index_code_batch
from app.services.mcp_tool_stats import record_mcp_tool_call
from app.services.search_hybrid import (
    hybrid_code_seed_ids,
    spec_chunk_vector_ids,
    traverse_code_graph,
)
from app.services.embeddings import embed_query
from app.services.spec_indexing import insert_spec_chunks_with_embeddings
from app.tools._auth_check import check_read, check_write
from app.tools._common import error_json


def _parse_json_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            data = json.loads(s)
            return list(data) if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
    return []


def push_code_index_impl(
    app_target: str,
    file_paths: list[str] | str,
    nodes: list[dict[str, Any]] | str,
    edges: list[dict[str, Any]] | str,
) -> str:
    record_mcp_tool_call("push_code_index")
    with SessionLocal() as _db:
        denied = check_write(_db)
        if denied:
            return denied
    if isinstance(file_paths, list):
        fps = [str(x).strip() for x in file_paths if str(x).strip()]
    else:
        fps = [str(x).strip() for x in _parse_json_list(file_paths) if str(x).strip()]
    nodes_l = nodes if isinstance(nodes, list) else _parse_json_list(nodes)
    edges_l = edges if isinstance(edges, list) else _parse_json_list(edges)
    payload = {"file_paths": fps, "nodes": nodes_l, "edges": edges_l}
    ok = enqueue_index_code_batch(app_target.strip().lower(), payload)
    if not ok:
        return json.dumps(
            {
                "ok": False,
                "error": "Celery broker not configured or enqueue failed",
                "action_required": "Set CELERY_BROKER_URL and run worker container",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "ok": True,
            "message": "index_code_batch enqueued",
            "app_target": app_target.strip().lower(),
            "nodes_queued": len(nodes_l),
            "edges_queued": len(edges_l),
        },
        ensure_ascii=False,
    )


def analyze_code_impact_impl(query: str, app_target: str) -> str:
    record_mcp_tool_call("analyze_code_impact")
    with SessionLocal() as db:
        try:
            denied = check_read(db)
            if denied:
                return denied
            seeds = hybrid_code_seed_ids(
                db, query=query, app_target=app_target, top_n=5
            )
            if not seeds:
                return json.dumps(
                    {
                        "ok": True,
                        "message": "no code nodes indexed for this app (use push_code_index first)",
                        "graph": None,
                    },
                    ensure_ascii=False,
                )
            graph = traverse_code_graph(
                db,
                app_target=app_target,
                seed_ids=seeds,
            )
            return json.dumps(
                {"ok": True, "seed_ids": seeds, "graph": graph}, ensure_ascii=False
            )
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "action_required": "check embedding.dim / provider, code index",
                },
                ensure_ascii=False,
            )


def push_spec_chunks_with_embeddings_impl(spec_id: int, chunks_json: Any) -> str:
    """로컬에서 임베딩한 청크를 DB에 직접 반영 (서버 워커 큐 밀릴 때 폴백)."""
    record_mcp_tool_call("push_spec_chunks_with_embeddings")
    with SessionLocal() as _db:
        denied = check_write(_db)
        if denied:
            return denied
    if isinstance(chunks_json, str):
        s = chunks_json.strip()
        if not s:
            return json.dumps(
                {"ok": False, "error": "chunks_json empty"},
                ensure_ascii=False,
            )
        try:
            data = json.loads(s)
        except json.JSONDecodeError as exc:
            return json.dumps(
                {"ok": False, "error": f"invalid json: {exc}"},
                ensure_ascii=False,
            )
    elif isinstance(chunks_json, list):
        data = chunks_json
    else:
        return json.dumps(
            {
                "ok": False,
                "error": "chunks_json must be JSON array string or list",
            },
            ensure_ascii=False,
        )
    if not isinstance(data, list):
        return json.dumps(
            {"ok": False, "error": "chunks must be a JSON array"},
            ensure_ascii=False,
        )
    with SessionLocal() as db:
        try:
            return json.dumps(
                insert_spec_chunks_with_embeddings(db, spec_id, data),
                ensure_ascii=False,
            )
        except Exception as exc:
            db.rollback()
            return error_json(str(exc))


def find_historical_reference_impl(
    new_spec_text: str, app_target: str, top_n: int = 5
) -> str:
    record_mcp_tool_call("find_historical_reference")
    with SessionLocal() as db:
        try:
            denied = check_read(db)
            if denied:
                return denied
            snippet = (new_spec_text or "")[:8000]
            if not snippet.strip():
                return json.dumps(
                    {
                        "ok": False,
                        "error": "new_spec_text empty",
                        "action_required": "pass spec body",
                    },
                    ensure_ascii=False,
                )
            try:
                qvec = embed_query(snippet)
            except Exception as exc:
                return json.dumps(
                    {
                        "ok": False,
                        "error": f"embed failed: {exc}",
                        "action_required": (
                            "config.yaml embedding.provider(local|openai|localhost|bedrock) 및 "
                            "embedding.dim·API 키·모델을 맞출 것"
                        ),
                    },
                    ensure_ascii=False,
                )
            v_ids = spec_chunk_vector_ids(
                db, app_target=app_target, query_embedding=qvec, limit=30
            )
            ranked = v_ids[:top_n]
            if not ranked:
                return json.dumps(
                    {
                        "ok": True,
                        "message": "no similar chunks (index specs with Celery worker first)",
                        "matches": [],
                    },
                    ensure_ascii=False,
                )
            chunks = db.scalars(select(SpecChunk).where(SpecChunk.id.in_(ranked))).all()
            by_id = {c.id: c for c in chunks}
            spec_ids = {c.spec_id for c in chunks}
            specs = {
                s.id: s
                for s in db.scalars(select(Spec).where(Spec.id.in_(spec_ids))).all()
            }
            matches: list[dict[str, Any]] = []
            for cid in ranked:
                ch = by_id.get(cid)
                if not ch:
                    continue
                sp = specs.get(ch.spec_id)
                matches.append(
                    {
                        "chunk_id": ch.id,
                        "spec_id": ch.spec_id,
                        "chunk_excerpt": ch.content[:2000],
                        "metadata": ch.chunk_metadata,
                        "spec_title": sp.title if sp else None,
                        "related_files": sp.related_files if sp else [],
                        "base_branch": sp.base_branch if sp else None,
                    }
                )
            return json.dumps({"ok": True, "matches": matches}, ensure_ascii=False)
        except Exception as exc:
            return error_json(str(exc))


def register_rag_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def push_spec_chunks_with_embeddings(spec_id: int, chunks_json: Any) -> str:
        """
        서버 Celery 워커 대신 로컬에서 직접 임베딩한 벡터를 spec_chunks에 저장한다 (폴백 전용).

        언제 쓰는가:
        - Celery 워커가 중단됐거나 큐가 지연돼서 임베딩이 안 될 때
        - 서버 임베딩 모델 대신 다른 모델로 로컬 임베딩한 결과를 직접 넣고 싶을 때

        주의: 벡터 차원이 서버의 EMBEDDING_DIM과 반드시 일치해야 한다.
        일반적인 상황에서는 upload_document를 쓰면 서버가 자동으로 임베딩한다.

        chunks_json: [{ "content": "...", "embedding": [float,...], "metadata": {...} }, ...]
        """
        return push_spec_chunks_with_embeddings_impl(spec_id, chunks_json)

    @mcp.tool()
    def push_code_index(
        app_target: str,
        file_paths: list[str] | str,
        nodes: list[dict[str, Any]] | str,
        edges: list[dict[str, Any]] | str,
    ) -> str:
        """
        코드 파일의 AST/심볼 인덱스를 서버에 등록한다.

        언제 쓰는가:
        - 코드를 처음 인덱싱할 때 또는 파일을 수정한 뒤 인덱스를 갱신할 때
        - analyze_code_impact를 쓰기 전에 먼저 인덱스를 만들어야 할 때

        nodes: 각 심볼(함수·클래스 등) 정보
          - stable_id: 파일경로+심볼명 기반 고유 ID
          - file_path, symbol_name, kind (function/class/method), content

        edges: 심볼 간 관계
          - source_stable_id, target_stable_id, relation (예: CALLS, IMPORTS)

        file_paths에 포함된 경로의 기존 인덱스는 먼저 삭제 후 재삽입된다.
        """
        return push_code_index_impl(app_target, file_paths, nodes, edges)

    @mcp.tool()
    def analyze_code_impact(query: str, app_target: str) -> str:
        """
        특정 코드를 수정했을 때 영향받는 상위/하위 코드를 그래프로 찾는다.

        언제 쓰는가:
        - "payment_service.py 바꾸면 어디까지 영향받아?" 같은 질문에 답할 때
        - 리팩토링 전 의존성 파악이 필요할 때

        search_documents와의 차이:
        - search_documents: 기획서/문서 검색
        - analyze_code_impact: 코드 심볼 의존성 그래프 탐색

        push_code_index로 먼저 코드 인덱스가 만들어져 있어야 한다.
        """
        return analyze_code_impact_impl(query, app_target)

    @mcp.tool()
    def find_historical_reference(
        new_spec_text: str, app_target: str, top_n: int = 5
    ) -> str:
        """
        지금 작성하려는 기획서 초안과 의미적으로 유사한 과거 기획서를 찾는다.

        언제 쓰는가:
        - 새 기획서를 쓰기 전에 "예전에 비슷한 기능을 어떻게 설계했지?" 확인할 때
        - 기획서 초안이 있고 관련 과거 기획 + 관련 파일 경로를 참고하고 싶을 때

        search_documents와의 차이:
        - search_documents: 키워드/주제로 기획서를 찾는 일반 검색
        - find_historical_reference: 기획서 본문 전체를 넘겨서 의미 유사도로 비교
          → 관련 파일 경로(related_files)까지 함께 반환해서 코드 위치 파악에 유용

        new_spec_text: 작성 중인 기획서 텍스트 (최대 8000자)
        top_n: 반환할 유사 기획서 개수 (기본 5)
        """
        return find_historical_reference_impl(new_spec_text, app_target, top_n)
