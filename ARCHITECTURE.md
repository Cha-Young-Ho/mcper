# ARCHITECTURE.md — 기술 아키텍처

FastAPI + MCP(Streamable HTTP) + PostgreSQL(pgvector) + Redis/Celery

---

## 시스템 개요

```
클라이언트 (Cursor/Claude)
    │ Streamable HTTP
    ▼
FastAPI (:8000)
├── /mcp ─→ FastMCP ─→ tools/*.py ─→ services/*.py ─→ DB
├── /admin ─→ Jinja2 UI (규칙/스킬/기획서 관리)
├── /auth ─→ JWT/OAuth (선택적)
└── /health ─→ DB + Celery 상태
    │                       │
    ▼                       ▼
PostgreSQL (pgvector)    Redis → Celery Worker
├── specs + spec_chunks     └── 청킹·임베딩 비동기
├── code_nodes + code_edges
├── *_rule_versions (Global/Repo/App)
├── *_skill_versions
├── mcper_users + api_keys
└── mcp_allowed_hosts
```

---

## 핵심 모듈

### MCP 계층

| 파일 | 역할 |
|------|------|
| `mcp_app.py` | FastMCP 인스턴스 + 도구 등록 + instructions |
| `mcp_dynamic_mount.py` | ASGI 래퍼 + Host 검증 |
| `tools/documents.py` | 기획서 업로드/검색 |
| `tools/global_rules.py` | 규칙 조회/발행/버전 관리 |
| `tools/skill_tools.py` | 스킬 조회/발행 |
| `tools/rag_tools.py` | 코드 그래프 + 유사 기획서 |
| `tools/data_tools.py` | 범용 데이터 소스 |

호출 흐름: 클라이언트 → mcp_dynamic_mount → Host 검증 → FastMCP → tools → services → DB

### 데이터베이스

| 테이블 | 용도 |
|--------|------|
| `specs` | 기획서 (title, content, app_target) |
| `spec_chunks` | 청크 + pgvector 임베딩 (parent/child) |
| `code_nodes/edges` | 코드 심볼 그래프 + 임베딩 |
| `global/repo/app_rule_versions` | 3계층 규칙 (섹션별 버전) |
| `global/repo/app_skill_versions` | 3계층 스킬 (섹션별 버전) |
| `mcp_allowed_hosts` | Host 화이트리스트 |
| `mcper_users/api_keys` | 인증 |

마이그레이션: Alembic 미사용. `_apply_lightweight_migrations()`에서 직접 ALTER TABLE.

### 서비스 계층

| 서비스 | 파일 | 핵심 |
|--------|------|------|
| 검색 | `search_hybrid.py` | Vector + FTS + RRF 병합 |
| 규칙 | `versioned_rules.py` | 3계층 조립 + build_markdown_response |
| 스킬 | `versioned_skills.py` | 규칙과 동일 구조 |
| 임베딩 | `embeddings/` | Pluggable (local/openai/bedrock) |
| 청킹 | `chunking.py` | 1800자/180 overlap, heading-aware |
| 인덱싱 | `spec/service.py` | DI 패턴 (Strategy+Repository+Embedding) |

### Celery 태스크

| 태스크 | 트리거 |
|--------|--------|
| `index_spec` | 기획서 업로드 시 청킹+임베딩 |
| `index_code_batch` | 코드 그래프 푸시 시 임베딩 |

Celery 미설정 시 `enqueue_or_index_sync()`로 동기 폴백.

---

## 데이터 흐름

**기획서 업로드**: upload_document → DB INSERT → Celery index_spec → 청크+임베딩 → spec_chunks

**검색**: search_documents → embed_query → Vector top40 + FTS top40 → RRF 병합 → parent context 첨부

**규칙 조회**: get_global_rule(app_name, origin_url) → Global latest + Repo(URL 매칭) + App latest → Markdown 조립

---

## 배포

### Docker Compose (로컬)
```
web (:8000) + worker (Celery) + db (postgres:16, :5433) + redis (:6380)
```

### 프로덕션
ALB → ECS/K8s web (autoscale) → RDS PostgreSQL + ElastiCache Redis + Fargate Worker

---

## 보안

- Host/Origin 화이트리스트 (DB 기반)
- CSRF 토큰
- JWT 인증 (선택적, `MCPER_AUTH_ENABLED`)
- ORM 파라미터화 (SQL injection 방지)
- bcrypt 비밀번호 해싱
