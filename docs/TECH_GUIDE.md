# MCPER 기술 지침

**프로젝트 기술 스택 및 아키텍처 가이드.**
운영 규칙은 루트 `CLAUDE.md` 참고. 에이전트별 상세 가이드는 `.agents/` 참고.

---

## 프로젝트 개요

FastAPI + FastMCP + PostgreSQL(pgvector) + Redis + Celery 스택.
기획서(Spec) 청킹·벡터화 → RAG 기반 MCP 도구 서빙 + 버전 관리형 규칙 시스템 + 코드 그래프 인덱싱.
사내 전용 프라이빗 네트워크 설계. 인증은 선택적 Feature Flag.

---

## 핵심 원칙

- **인프라 중립**: 앱 코드는 환경 변수만 읽음. 배포 설정은 `infra/` 에서만.
- **Feature Flag**: `MCPER_AUTH_ENABLED` / `MCPER_ADMIN_ENABLED` / `MCPER_MCP_ENABLED` 로 기능 ON/OFF.
- **프라이빗 네트워크**: 기본 바인딩 `127.0.0.1`. K8s는 ClusterIP + Nginx IP 화이트리스트.
- **append-only 규칙**: 규칙(Rule)은 삭제·수정 없이 버전만 추가. 롤백은 이전 버전 재publish.
- **임베딩 교체 시 전량 재생성**: 모델이나 dim 변경 시 기존 벡터 전부 무효. 재인덱싱 필수.

---

## 디렉터리 구조

```
stz-mcp/
├── main.py                    # uvicorn 진입점
├── Dockerfile                 # 프로덕션 이미지
├── requirements.txt
├── config.yaml
├── app/
│   ├── main.py                # FastAPI 앱, lifespan, 라우터
│   ├── config.py              # 설정 부트스트랩
│   ├── logging_config.py      # JSON/text 로깅
│   ├── mcp_app.py             # FastMCP 인스턴스
│   ├── mcp_dynamic_mount.py   # MCP ASGI 게이트
│   ├── mcp_tools_docs.py      # 도구 메타데이터
│   ├── asgi/                  # Transport 보안
│   ├── auth/                  # JWT/OAuth
│   ├── db/                    # SQLAlchemy 모델
│   ├── routers/               # FastAPI 라우터
│   ├── services/              # 비즈니스 로직
│   ├── tools/                 # MCP 도구
│   ├── worker/                # Celery 앱
│   ├── templates/             # Jinja2 HTML
│   ├── static/                # CSS/JS
│   └── prompts/               # 규칙 시드 마크다운
├── infra/
│   ├── docker/                # Docker Compose + .env
│   └── kubernetes/            # K8s 매니페스트
└── docs/                      # 기획 문서
```

---

## 주요 모듈

### `app/main.py` — FastAPI 앱 + Lifespan

**Lifespan 실행 순서:**
```
configure_logging() → _validate_startup_config() → configure_embedding_backend()
→ init_db() → seed_if_empty() → seed_repo_if_empty() → seed_sample_spec_if_empty()
→ seed_admin_user_if_empty() → sync_mcp_allowed_hosts() → McpDynamicASGI.init()
```

**라우터 등록 조건:**
```python
if _ADMIN_ENABLED:   app.include_router(admin_router)
if _AUTH_ENABLED:    app.include_router(auth_router)
if _MCP_ENABLED:     app.mount(MCP_MOUNT_PATH, mcp_asgi)
```

**엔드포인트:**
- `GET /health` — DB SELECT 1 체크
- `GET /health/rag` — DB + Celery + Redis 상태

---

### `app/config.py` — 설정 부트스트랩

**우선순위:** 환경 변수 > config.<env>.yaml > config.yaml > 기본값

**YAML 플레이스홀더 지원:** `${VAR}` / `${VAR:-default}`

---

### `app/db/` — 데이터베이스

**초기화 흐름:**
```
CREATE EXTENSION vector
→ Base.metadata.create_all()
→ _apply_lightweight_migrations()  # ALTER TABLE
→ _apply_rag_indexes()              # GIN, HNSW
```

**주요 테이블:**
- `specs` — 기획서
- `spec_chunks` — 청크 + 벡터 (HNSW 인덱스)
- `code_nodes` / `code_edges` — 코드 그래프
- `*_rule_version` — 버전 관리 규칙
- `mcper_users` / `mcper_api_keys` — 인증
- `mcp_allowed_hosts` — Host 허용 목록

**마이그레이션:** Alembic 미사용. `_apply_lightweight_migrations()` 에서 직접 실행.

---

### `app/services/embeddings/` — 임베딩 서비스

**공급자:** local(SentenceTransformer) / openai / localhost / bedrock

**사용:**
```python
from app.services.embeddings.core import embed_texts, embed_query
vectors = embed_texts(["text1", "text2"])
```

**중요:** 직접 backend 인스턴스 사용 금지.

---

### `app/services/chunking.py` — 텍스트 청킹

**상수:**
```python
DEFAULT_CHUNK_CHARS = 1800
DEFAULT_OVERLAP_CHARS = 180
```

**분할 우선순위:** `\n\n` → `\n` → `. ` → ` ` → 문자

---

### `app/worker/` — Celery 백그라운드

**태스크:**
- `index_spec` — 기획서 청킹 + 임베딩
- `index_code_batch` — 코드 노드 임베딩 + 그래프 upsert

**재시도:** max_retries=3, countdown=10s

---

### `app/tools/` — MCP 도구

**도구 구현 위치:**
- `specs.py` — 기획서 업로드/검색
- `rag_tools.py` — 코드 그래프 + 과거 레퍼런스
- `global_rules.py` — 규칙 관리

**등록:** `mcp_app.py` 에서 `register_*()` 호출

---

## 환경 변수 (간편 참조)

| 변수 | 기본값 | 용도 |
|------|--------|------|
| `DATABASE_URL` | — | PostgreSQL URL |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery 브로커 |
| `MCPER_ADMIN_ENABLED` | `true` | 어드민 UI |
| `MCPER_MCP_ENABLED` | `true` | MCP 엔드포인트 |
| `MCPER_AUTH_ENABLED` | `false` | JWT/OAuth |
| `MCPER_DOC_PARSE_ENABLED` | `false` | PDF/DOCX 파싱 |
| `EMBEDDING_PROVIDER` | `local` | local/openai/localhost/bedrock |
| `EMBEDDING_DIM` | `384` | 벡터 차원 |
| `LOG_FORMAT` | `text` | text/json |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `ADMIN_PASSWORD` | `changeme` | HTTP Basic (auth disabled) |
| `AUTH_SECRET_KEY` | — | JWT 서명 키 (필수) |

---

## 프로덕션 체크리스트

- [ ] `MCPER_AUTH_ENABLED=true` + 강한 `AUTH_SECRET_KEY`
- [ ] `ADMIN_PASSWORD` 변경
- [ ] `MCPER_HOST_BIND=127.0.0.1` + Nginx/Ingress 앞단
- [ ] `LOG_FORMAT=json`
- [ ] `MCP_BYPASS_TRANSPORT_GATE=false`
- [ ] K8s `secret.yaml` 실제 시크릿 주입
- [ ] DB 볼륨 백업 정책 (pgvector 보존 중요)
- [ ] `.gitignore` 에 `infra/kubernetes/secret.yaml` 확인

---

## 자세한 기술 내용

각 모듈별 상세 구현은 루트 `CLAUDE.md` 이전 버전에 포함. 필요 시 `git show HEAD~1:CLAUDE.md` 로 확인 가능.

