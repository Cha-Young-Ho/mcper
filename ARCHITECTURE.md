# ARCHITECTURE.md — 기술 아키텍처

**Spec MCP**: FastAPI + MCP(Model Context Protocol) Streamable HTTP + PostgreSQL + Celery/Redis

---

## 시스템 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                      클라이언트 (Cursor/Claude)                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                    HTTP │ Streamable HTTP
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                  FastAPI 웹 서버 (:8000)                         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         MCP (Model Context Protocol)                     │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │ Tools:                                              │ │  │
│  │  │ • upload_spec_to_db          (기획서 추가)         │ │  │
│  │  │ • search_spec_and_code       (하이브리드 검색)      │ │  │
│  │  │ • push_spec_chunks_...       (벡터 임베딩 저장)    │ │  │
│  │  │ • push_code_index            (코드 그래프 색인)     │ │  │
│  │  │ • analyze_code_impact        (영향도 분석)         │ │  │
│  │  │ • find_historical_reference  (유사 기획서 찾기)     │ │  │
│  │  │ • get_global_rule            (에이전트 규칙 조회)   │ │  │
│  │  │ • publish_global_rule        (규칙 갱신)           │ │  │
│  │  │ • publish_repo_rule          (저장소 규칙)         │ │  │
│  │  │ • publish_app_rule           (앱 규칙)             │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  │                                                           │  │
│  │  라우터: /mcp (Streamable HTTP)                          │  │
│  │  미들웨어: Host/Origin 검증, CSRF 토큰                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         RESTful API (HTTP)                               │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │ POST   /api/auth/login                  (로그인)    │ │  │
│  │  │ POST   /api/auth/logout                 (로그아웃)  │ │  │
│  │  │ POST   /api/auth/change-password        (패스워드)  │ │  │
│  │  │ GET    /api/specs/{id}                  (기획서)    │ │  │
│  │  │ GET    /health                          (상태 확인) │ │  │
│  │  │ GET    /admin                           (대시보드)  │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         데이터 계층                                      │  │
│  │  Services:                                               │  │
│  │  • embeddings/     (로컬/OpenAI/Bedrock 벡터화)         │  │
│  │  • versioned_rules.py (규칙 버전 관리)                 │  │
│  │  • spec_*.py       (기획서 색인·검색)                   │  │
│  │  • mcp_*.py        (MCP 호스트 검증·권한)              │  │
│  │  • celery_*.py     (비동기 작업 모니터링)              │  │
│  └──────────────────────────────────────────────────────────┘  │
└───────────────┬────────────────────────────────────┬────────────┘
                │                                    │
        ┌───────▼────────┐               ┌──────────▼─────┐
        │  PostgreSQL    │               │  Redis (Celery) │
        │  (마운트 5432) │               │  (마운트 6379)  │
        │                │               │                 │
        │ • specs        │               │ • broker        │
        │ • spec_chunks  │               │ • result backend│
        │ • rules        │               │ • task queue    │
        │ • code_nodes   │               │                 │
        │ • auth         │               │                 │
        │ • ...          │               └─────────────────┘
        └────────────────┘                        │
                                           ┌──────▼──────┐
                                           │   Celery    │
                                           │  (워커)     │
                                           │             │
                                           │ • 임베딩    │
                                           │ • 색인      │
                                           │ • 청크      │
                                           └─────────────┘
```

---

## 핵심 모듈 구조

### 1. **MCP 계층** (`app/mcp_*.py`, `app/tools/`)

**책임**: 클라이언트(Cursor) ↔ 서버 간 도구 호출 + 규칙 관리

| 파일 | 역할 |
|------|------|
| `app/mcp_app.py` | **FastMCP** 인스턴스 + 모든 도구 등록 |
| `app/mcp_dynamic_mount.py` | ASGI 라우터 + Host 검증 + 트랜잭션 |
| `app/asgi/mcp_host_gate.py` | Host/Origin 화이트리스트 검증 |
| `app/tools/rag_tools.py` | RAG 도구 (검색, 푸시) |
| `app/tools/global_rules.py` | 규칙 도구 (조회, 발행, 버전) |
| `app/tools/specs.py` | 기획서 도구 (업로드, 검색) |

**호출 흐름**:
```
클라이언트 /mcp (POST/SSE)
  ↓
mcp_dynamic_mount (ASGI 래퍼)
  ↓
mcp_host_gate (Host 검증)
  ↓
FastMCP (도구 라우팅)
  ↓
tools/*.py (로직 실행)
  ↓
services/*.py + DB
```

---

### 2. **데이터 계층** (`app/db/`, `app/services/`)

#### 2.1 **데이터베이스 모델** (`app/db/*_models.py`)

| 테이블 | 설명 |
|--------|------|
| `specs` | 기획서 (제목, 내용, 대상 앱, 관련 파일) |
| `spec_chunks` | 기획서 청크 + 벡터 임베딩 (FTS 검색) |
| `code_nodes` | 코드 노드 (함수·클래스·모듈) + 벡터 |
| `code_edges` | 코드 의존성 (호출 관계, 임포트) |
| `global_rule_versions` | 전역 에이전트 규칙 버전 이력 |
| `repo_rule_versions` | 저장소별(URL 패턴) 규칙 버전 |
| `app_rule_versions` | 앱별 규칙 버전 |
| `mcp_allowed_hosts` | MCP 허용 Host 헤더 화이트리스트 |
| `auth` | 사용자 계정 (username, password_hash, ...) |
| `celery_tasks` | Celery 작업 상태 + 로그 |

#### 2.2 **서비스 계층** (`app/services/`)

**임베딩 엔진**
```
app/services/embeddings/
├── core.py                    ← 임베딩 인터페이스
├── factory.py                 ← 프로바이더 선택
└── backends/
    ├── local.py               ← sentence-transformers (기본)
    ├── openai.py              ← OpenAI Embeddings API
    ├── bedrock.py             ← AWS Bedrock
    └── utils.py               ← 재사용 헬퍼
```

**검색 & RAG**
```
• spec_admin.py               ← 기획서 CRUD
• spec_indexing.py            ← 청크 생성 + 색인
• search_hybrid.py            ← 벡터 + FTS + RRF 통합
• rag_health.py               ← RAG 상태 모니터링
```

**규칙 관리**
```
• versioned_rules.py          ← 규칙 버전 관리 (append-only)
```

**코드 분석** (향후)
```
• code_parser.py              ← 코드 파싱 인터페이스
• code_parser_python.py       ← Python AST 파서
• code_parser_javascript.py   ← JavaScript 파서
```

**통합 및 보안**
```
• mcp_host_validate.py        ← Host 검증
• mcp_auto_hosts.py           ← EC2 IMDS로 자동 등록
• mcp_security.py             ← 권한 검사 (미구현)
```

---

### 3. **비동기 작업** (`app/worker/`)

**Celery 기반 백그라운드 태스크**:

| 파일 | 역할 |
|------|------|
| `app/worker/celery_app.py` | Celery 인스턴스 설정 |
| `app/worker/tasks.py` | 정의된 태스크 (색인, 청크, 임베딩) |
| `app/services/celery_client.py` | 태스크 큐잉 헬퍼 |
| `app/services/celery_monitoring.py` | 대시보드용 상태 조회 |

**주요 태스크**:
```
• index_spec(spec_id)              ← 기획서 청크 생성 + 색인
• index_code_batch(nodes, edges)   ← 코드 노드·엣지 임베딩
• monitor_queue_depth()            ← 큐 길이 모니터링
```

---

### 4. **라우터 & 미들웨어** (`app/routers/`, `app/asgi/`)

#### 라우터
```
app/routers/
├── admin.py          ← 대시보드 (기획서, 규칙, 도구, 모니터링)
├── admin_base.py     ← 기본 분류 및 보안
├── admin_dashboard.py ← 대시보드 상태 조회
├── admin_rules.py    ← 규칙 관리 UI
├── admin_specs.py    ← 기획서 관리 UI
└── admin_tools.py    ← 도구 통계 조회
```

#### 미들웨어
```
app/asgi/
├── csrf_middleware.py  ← CSRF 토큰 검증
├── mcp_host_gate.py    ← Host/Origin 화이트리스트
└── (기타 ASGI 필터)
```

---

### 5. **인증** (`app/auth/`)

**JWT 세션 기반 인증** (선택):

| 파일 | 역할 |
|------|------|
| `app/auth/dependencies.py` | 토큰 검증 + 의존성 주입 |
| `app/auth/oauth.py` | OAuth2 (Google, GitHub) |
| `app/auth/router.py` | `/api/auth/*` 엔드포인트 |
| `app/auth/schemas.py` | 요청/응답 모델 |
| `app/auth/service.py` | 로직 (암호화, 토큰 발급) |
| `app/db/auth_models.py` | `auth_users` 테이블 ORM |

---

### 6. **설정 & 로깅** (`app/config.py`, `app/logging_config.py`)

```
app/config.py
├── ServerSettings        ← Uvicorn (host:port)
├── DatabaseSettings      ← Postgres (URL, pool)
├── EmbeddingSettings     ← 프로바이더 선택
├── CelerySettings        ← Redis (broker, backend)
├── MCPSettings           ← 마운트 경로, 보안
├── AuthSettings          ← JWT secret, OAuth 클라이언트
└── Settings              ← 전체 설정 (YAML + env)

app/logging_config.py
└── configure_logging()   ← 구조화 로깅 (JSON, 에이전트)
```

---

## 데이터 흐름

### 시나리오 1: 기획서 업로드

```
클라이언트 /mcp "upload_spec_to_db"
  ↓ (content, app_target, base_branch, related_files)
app/tools/specs.py::upload_spec_to_db
  ↓
app/services/spec_admin.py::create_spec
  ↓ (DB INSERT)
PostgreSQL specs 테이블
  ↓ (Celery 큐)
app/worker/tasks.py::index_spec(spec_id)
  ↓ (청크 생성, 임베딩, INSERT)
PostgreSQL spec_chunks 테이블
  ↓
클라이언트 ← 상태 응답 (✅ 색인 완료)
```

### 시나리오 2: 기획서 + 코드 검색

```
클라이언트 /mcp "search_spec_and_code"
  ↓ (query, app_target)
app/tools/specs.py::search_spec_and_code
  ↓
app/services/search_hybrid.py::hybrid_search
  ├─→ 벡터 검색     (spec_chunks 임베딩)
  ├─→ FTS 검색     (spec_chunks 텍스트)
  ├─→ 코드 검색    (code_nodes 임베딩)
  └─→ RRF 병합    (순위 합산)
  ↓
PostgreSQL 쿼리
  ↓
클라이언트 ← 결과 (spec_chunks + code_nodes)
```

### 시나리오 3: 에이전트 규칙 조회

```
클라이언트 /mcp "get_global_rule"
  ↓ (app_name, origin_url, version)
app/tools/global_rules.py::get_global_rule
  ↓
app/services/versioned_rules.py::fetch_rules
  ├─→ global_rule_versions (최신 또는 지정 version)
  ├─→ repo_rule_versions (origin URL 패턴 매칭)
  └─→ app_rule_versions (app_name)
  ↓
PostgreSQL 쿼리
  ↓
클라이언트 ← 규칙 본문 (Markdown)
```

---

## 배포 토폴로지

### Docker Compose (로컬/스테이징)

```yaml
services:
  web:
    image: spec-mcp:local
    ports: ["8001:8000"]
    volumes: ["..:/app"]           # 핫 리로드
    depends_on: ["db"]
    env:
      PYTHONPATH: .
      DATABASE_URL: postgresql://...
      ADMIN_PASSWORD: ...

  worker:
    image: spec-mcp:local
    command: celery -A app.worker.celery_app worker -l info
    env: (web와 동일)

  db:
    image: postgres:16
    ports: ["5433:5432"]
    volumes: ["postgres_data:/var/lib/postgresql/data"]

  redis:
    image: redis:7-alpine
    ports: ["6380:6379"]
```

### 프로덕션 (ECS/K8s)

```
┌─────────────────────┐
│      ALB            │ ← 공인 IP, HTTPS
└────────┬────────────┘
         │
    ┌────┴────┐
    │          │
┌───▼──┐ ┌───▼──┐
│ web  │ │ web  │  ← 오토스케일 (1..N)
│ :8000│ │ :8000│
└───┬──┘ └───┬──┘
    │        │
    └────┬───┘
         │ (RDS Postgres)
    ┌────▼────────┐
    │   RDS DB    │
    └─────────────┘

┌──────────────────┐
│  ElastiCache     │ ← Redis (Celery)
│  (Redis)         │
└──────────────────┘

┌──────────────────┐
│  ECS Fargate     │ ← Celery 워커 (1..M)
│  (worker)        │
└──────────────────┘
```

---

## 성능 특성

| 구간 | 예상 시간 | 병목 |
|------|---------|------|
| 기획서 업로드 | 100ms (즉시 반환) | 네트워크 |
| 기획서 청크 생성 | 2-5s (async) | Celery 큐 깊이 |
| 벡터 임베딩 | 500ms (로컬) ~ 2s (API) | 임베딩 모델 |
| 하이브리드 검색 | 50-200ms | DB 쿼리 + 벡터 거리 |
| 규칙 조회 | 10-30ms | DB 조회 |
| MCP 스트림 응답 | 실시간 | 네트워크 지연 |

---

## 보안 고려사항

### MCP 계층
- ✅ Host/Origin 화이트리스트 (DB 기반)
- ✅ CSRF 토큰 (POST 요청)
- ⚠️ 인증: JWT (선택적, 기본 비활성)

### 데이터 계층
- ✅ SQL Injection 방지 (ORM + 파라미터화)
- ✅ 비밀번호 해싱 (bcrypt)
- ⚠️ API 토큰 만료 검증 (구현 중)
- ❌ 레이트 제한 (미구현)

### 배포
- ✅ 환경변수 (secrets)
- ✅ TLS/HTTPS (ALB/리버스 프록시)
- ⚠️ WAF (선택적)

---

## 확장 포인트

### 1. **코드 파싱** (향후 우선순위 HIGH)
```
app/services/code_parser*.py
  ↓
AST 크롤러 → code_nodes + code_edges
  ↓
워커 색인 → PostgreSQL
```

### 2. **OAuth 추가**
```
app/auth/oauth.py
  ↓
/api/auth/google, /api/auth/github
  ↓
auth_users 테이블
```

### 3. **커스텀 RAG 통합**
```
app/services/search_custom.py
  ↓
하이브리드 검색에 domain-specific 로직 추가
```

---

## 관련 문서

- **README.md** — 실행 가이드
- **docs/DESIGN.md** — 설계 원칙
- **docs/RELIABILITY.md** — 배포 체크리스트
- **docs/SECURITY.md** — 보안 정책
