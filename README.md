<p align="center">
  <img src="docs/assets/mcper-logo.svg" alt="MCPER" width="180" height="180"/>
</p>

<h1 align="center">MCPER</h1>

<p align="center">
  <b>MCP Harness Server for LLM Agents</b><br/>
  <sub>Rules · Skills · Workflows 를 버저닝된 중앙 저장소에서 LLM 클라이언트에 on-demand 로 공급</sub>
</p>

---

## 프로젝트가 푸는 문제

AI 에이전트가 여러 저장소·프로젝트를 넘나들며 작업할 때 발생하는 고질적 문제:

| 문제 | MCPER 의 해결 |
|---|---|
| 저장소마다 에이전트 규칙이 제각각, 관리 어렵다 | **3계층 규칙**(Global → Repository → App) + `publish_*_rule` 로 중앙 관리 |
| 과거 기획서·결정 이력을 기억 못 한다 | `upload_document` → pgvector 기반 하이브리드 검색 (`search_documents`, `find_historical_reference`) |
| 팀별/서비스별 권한이 필요한데 MCP 는 인증이 없다 | OAuth 2.1 PKCE + DCR + (Domain, App, Role) RBAC, Google OAuth 로그인 |
| 규칙을 바꾸면 모든 프로젝트에 재배포해야 한다 | `check_rule_versions` 로 버전만 비교, 바뀐 것만 `get_global_rule` 재수신 |
| 워크플로우를 시각적으로 공유하고 싶다 | `set_workflow_mermaid_tool` + Mermaid 한눈에보기 모달 |

---

## 아키텍처

<p align="center">
  <img src="docs/assets/architecture.svg" alt="MCPER architecture" width="800"/>
</p>

**Client LLM ↔ MCPER ↔ RULE / SKILL / WORKFLOW** — MCP 프로토콜로 LLM 클라이언트가 버저닝된 컨텐츠 스토어에 접근.

---

## 주요 기능

### 🧱 3계층 컨텐츠 버전 관리

각 컨텐츠 타입은 **Global** / **Repository(URL 패턴)** / **App** 3개 스트림을 독립 버저닝.

| 타입 | 용도 | 주요 MCP 도구 |
|---|---|---|
| **Rules** | 에이전트 행동 지침 (AI 가 따라야 할 규칙) | `get_global_rule`, `publish_global_rule`, `publish_app_rule`, `append_to_app_rule`, `search_rules`, `check_rule_versions` |
| **Skills** | 재사용 스킬·시스템 지식 | `get_global_skill`, `publish_*_skill_tool`, `search_skills` |
| **Workflows** | 작업 절차 · 에이전트 팀 조합 (Mermaid 지원) | `get_global_workflow`, `publish_*_workflow_tool`, `search_workflows`, `set_workflow_mermaid_tool`, `get_workflow_mermaid_tool` |
| **Docs** | 일반 문서(레퍼런스·가이드) | `get_global_doc`, `publish_*_doc_tool`, `search_docs`, `update_doc` |

### 📄 기획서·코드 검색 (RAG)

- `upload_document` / `upload_documents_batch` — 기획서 등록 (자동 청킹 + 임베딩)
- `search_documents` — 벡터 + FTS 하이브리드 (RRF 결합)
- `find_historical_reference` — 새 기획 초안 텍스트로 유사 과거 기획서 유사도 검색
- `push_code_index` / `analyze_code_impact` — 코드 그래프 인덱싱 + 영향 분석

### 🔐 인증 + 서비스별 권한

- **OAuth 2.1 PKCE + Dynamic Client Registration** (Claude Code / Cursor MCP OAuth 호환)
- **Google OAuth** 로그인 (Admin UI)
- **RBAC**: `(domain, app, role)` 3차원 — `role ∈ {viewer, editor, admin}`
- **마스터 단일 계정** `admin` (모든 권한 bypass)
- Google 로그인 유입 유저는 `is_admin=False` 로 생성 → 마스터가 `/admin/users/{id}/permissions` 에서 권한 부여
- MCP 도구 호출 시 **권한 없는 앱 요청은 서버에서 거절** (일반 유저 → `{"ok": false, "error": "Permission denied"}`)

### 🎨 어드민 UI

- `/admin` — 대시보드 (MCP 도구별 호출 통계)
- `/admin/plans` — 기획서 관리 (앱별 카드 → 이름 수정 / 내용 삭제 / 앱 삭제)
- `/admin/rules-*` — Rules Global / App / Repo 3 분할 라우터
- `/admin/skills-*`, `/admin/workflows-*`, `/admin/docs-*` — 동일 패턴
- `/admin/users`, `/admin/rbac` — 사용자·권한 관리
- `/admin/celery` — Celery 작업 실패 모니터링

### 🧩 스케일 / 운영 토글 (기본값에서는 동작 변경 0)

| ENV | 값 | 효과 |
|---|---|---|
| `MCPER_SESSION_STORE` | `memory` (기본) / `redis` | MCP OAuth 세션 Redis 외부화 → LB 다중 인스턴스 |
| `EMBEDDING_PROVIDER` | `local` / `sidecar` / `openai` / `bedrock` | 임베딩 백엔드 분리 |
| `MCPER_RULE_CACHE` | `off` / `redis` | 룰 응답 Redis LRU 캐시 |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | 정수 | PgBouncer 앞단 도입 시 낮게 |
| docker-compose profile `sidecar-embed`, `pgbouncer` | 선택 기동 | 임베딩 sidecar / PgBouncer 컨테이너 |

### 🧪 품질 인프라

- **139+ 단위 테스트** (tests/unit/): auth/permissions, admin_rules_service, rule_cache, search hybrid(RRF), embeddings, worker tasks 등
- `ruff format` + `ruff check` 전 코드 clean
- `djlint` 로 Jinja 템플릿 린트
- `pip-audit` CVE 해소 (pdfminer.six / authlib / python-multipart)

---

## 기술 스택

- **Python 3.13** · FastAPI · FastMCP (Streamable HTTP)
- **PostgreSQL + pgvector** (벡터 검색) · **Redis** (세션·캐시·브로커) · **Celery** (비동기 인덱싱)
- 임베딩: **sentence-transformers** (로컬 CPU, `all-MiniLM-L6-v2`, 384d) · **OpenAI** · **Bedrock** · **sidecar(HTTP)**
- 인증: **PyJWT** · **bcrypt** · **Authlib** (OAuth 서버) · **itsdangerous**

---

## 구동법

### 🐳 Docker Compose (권장)

```bash
git clone https://github.com/Cha-Young-Ho/mcper.git
cd mcper/infra/docker
docker compose up -d --build
```

기본 설정:
- 웹: `http://localhost:8001`
- Admin UI: `http://localhost:8001/admin` (아이디/비번: **`admin` / `changeme`**)
- Postgres: `localhost:5433` (호스트용)
- Redis: `localhost:6380`

**헬스 체크**:
```bash
curl http://localhost:8001/health        # 기본
curl http://localhost:8001/health/live   # liveness
curl http://localhost:8001/health/ready  # DB/Redis/임베딩 준비
curl http://localhost:8001/health/startup  # lifespan 완료
```

### 💻 로컬 개발 (Python)

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Postgres · Redis 는 별도로 띄워야 함 (예: docker compose up db redis)
export DATABASE_URL=postgresql://user:password@localhost:5433/mcpdb
export CELERY_BROKER_URL=redis://localhost:6380/0
export PYTHONPATH=.

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### ☁️ 운영 배포 (HTTPS)

```bash
cd infra/docker
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d --build
# Caddy 가 80/443 인계받아 Let's Encrypt 자동 발급
```

`Caddyfile` 의 도메인을 본인 소유 도메인으로 수정하여 사용.

### 🔧 환경 설정

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | — | Postgres 연결 |
| `CELERY_BROKER_URL` | — | Redis (비우면 큐 없이 동기 폴백) |
| `ADMIN_USER` / `ADMIN_PASSWORD` | `admin` / `changeme` | 마스터 계정 (운영 시 변경 권장) |
| `MCPER_AUTH_ENABLED` | `false` | 사용자 인증 활성 |
| `AUTH_SECRET_KEY` | — | JWT/CSRF 서명 키 (`MCPER_AUTH_ENABLED=true` 시 필수) |
| `AUTH_GOOGLE_CLIENT_ID` / `AUTH_GOOGLE_CLIENT_SECRET` | — | Google OAuth (설정 시 로그인 페이지에 버튼 노출) |
| `OAUTH_REDIRECT_BASE` | `http://localhost:8001` | OAuth 콜백 기본 URL |
| `EMBEDDING_PROVIDER` | `local` | `local`/`sidecar`/`openai`/`bedrock` |
| `EMBEDDING_DIM` | `384` | 벡터 차원 (모델과 맞춰야 함) |
| `MCPER_RULE_CACHE` | `off` | `redis` 시 룰 응답 캐시 |

`.env.local` 파일을 `infra/docker/` 에 두면 Compose 가 자동 로드.

---

## 사용 예시

### 1) Cursor / Claude Code 에 MCP 서버 등록

**Cursor** (`~/.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "mcper": { "url": "http://localhost:8001/mcp" }
  }
}
```

**Claude Code**:
```bash
claude mcp add --transport http mcper http://localhost:8001/mcp
```

**운영 (HTTPS + OAuth)**:
```bash
claude mcp add --transport http mcper https://<your-domain>/mcp
# 첫 호출 시 브라우저로 OAuth 인증 페이지 열림
```

### 2) 에이전트에서 룰 받아오기

에이전트 프롬프트 예:
```
이 프로젝트 룰 받아와 줘
```

→ MCP 가 `get_global_rule(app_name="my_app", origin_url="git@github.com:org/repo.git")` 호출 → Global + Repository(URL 매칭) + App 룰을 **한 개의 마크다운으로 머지**하여 반환 → 에이전트가 `CLAUDE.md` 또는 `.cursor/rules/` 에 자동 저장.

### 3) 새 앱 룰 추가

```
publish_app_rule(
  app_name="my_app",
  body="# My App Rules\n\n- 이 저장소는 TypeScript 만 사용...\n- PR 템플릿 필수..."
)
```
→ 서버가 버전 번호 자동 부여. `append_to_app_rule` 로 기존 룰에 이어 붙이기도 가능.

### 4) 기획서 업로드 + 유사 기획서 검색

```
upload_document(
  content="새 기획: ...",
  app_target="my_app",
  base_branch="main",
  related_files=["src/feature/..."]
)

# 나중에 유사 과거 기획 찾을 때
find_historical_reference(
  new_spec_text="이번에 만들려는 기능의 초안 ...",
  app_target="my_app"
)
```

### 5) 워크플로우 Mermaid 등록

```
publish_app_workflow_tool(
  app_name="my_app",
  body="# 배포 워크플로우\n...",
  section_name="deploy"
)
set_workflow_mermaid_tool(
  scope="app",
  app_name="my_app",
  section_name="deploy",
  version=1,
  mermaid="flowchart TD\n  A[PR 생성] --> B[리뷰] --> C[머지]"
)
```
→ `/admin/app-workflows/app/my_app/s/deploy/v/1` 페이지의 **"한눈에 보기"** 버튼으로 다이어그램 확인.

### 6) 사용자 권한 부여 (마스터 계정에서)

1. `admin/changeme` 로 `/admin` 로그인
2. 사용자가 Google 로 첫 로그인 → 자동 생성 (`is_admin=False`, 권한 없음)
3. `/admin/users/{id}/permissions` 에서 `(domain=dev, app=my_app, role=editor)` 부여
4. 해당 사용자 MCP 호출 시 `my_app` 에만 쓰기 가능, 다른 앱은 자동 거절

---

## 디렉터리 구조

```
app/
├── main.py                 # FastAPI + lifespan + 라우터 마운트
├── mcp_app.py              # FastMCP 인스턴스 + 51 tool 등록
├── config.py / config_merger.py  # 설정 병합 (YAML + env)
├── asgi/                   # MCP host gate + CSRF 미들웨어
├── auth/                   # OAuth · RBAC · JWT · 세션 스토어
├── db/                     # SQLAlchemy 모델 · 마이그레이션 · seed
├── routers/                # Admin UI REST + 템플릿 렌더
├── services/               # 비즈니스 로직 (versioned_*, search_*, rule_cache ...)
├── tools/                  # MCP 도구 구현 (documents/rules/skills/workflows/docs/rag/data)
├── spec/ rule/ skill/ workflow/ doc/  # 도메인별 서비스·리포지토리 분리
├── worker/                 # Celery 태스크
├── templates/              # Jinja2 어드민 템플릿 (80+)
└── static/                 # admin.css / admin.js / vendor (codemirror, mermaid)

infra/docker/               # docker-compose.yml / Dockerfile / Caddy
docs/                       # 감사·설계·세션 요약·가이드 문서
scripts/                    # reset_admin_password / seed_rules / reindex_* 등
tests/unit/                 # 139+ 단위 테스트 (MagicMock 기반, DB 불필요)
```

상세 아키텍처: [`ARCHITECTURE.md`](ARCHITECTURE.md) · 설계 원칙: [`docs/design-docs/core-beliefs.md`](docs/design-docs/core-beliefs.md) · 보안: [`docs/SECURITY.md`](docs/SECURITY.md) · 운영·배포: [`docs/RELIABILITY.md`](docs/RELIABILITY.md) · 변경 이력: [`CHANGELOG.md`](CHANGELOG.md)

---

## 라이선스 / 기여

개인 프로젝트. 이슈/PR 환영.
