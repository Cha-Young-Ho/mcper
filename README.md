<p align="center">
  <img src="docs/assets/mcper-logo.svg" alt="MCPER" width="180" height="180"/>
</p>

<h1 align="center">MCPER</h1>

<p align="center">
  <b>MCP Harness Server for LLM Agents</b><br/>
  <sub>Rules · Skills · Workflows 를 버저닝된 중앙 저장소에서 LLM 클라이언트에 on-demand 로 공급</sub>
</p>

---

## 프로젝트 소개

MCPER 는 Cursor AI · Claude Code · Codex · Copilot · Local LLM 등 **MCP 호환 LLM 클라이언트**에 프로젝트별 · 팀별 **행동 지침(Rules) · 재사용 패턴(Skills) · 작업 절차(Workflows)** 를 중앙에서 관리하고 on-demand 로 공급하는 MCP 서버다. FastAPI + FastMCP(Streamable HTTP) 기반으로, 각 컨텐츠는 Global / Repository / App 3계층으로 버저닝된다.

<p align="center">
  <img src="docs/assets/architecture.svg" alt="MCPER architecture" width="900"/>
</p>

---

## 빌드 & 실행

### Docker Compose (권장)

```bash
git clone https://github.com/Cha-Young-Ho/mcper.git
cd mcper/infra/docker
docker compose up -d --build
```

- 웹: `http://localhost:8001`
- Admin UI: `http://localhost:8001/admin` (`admin` / `changeme`)

**헬스 체크**:
```bash
curl http://localhost:8001/health
```

### 로컬 개발 (Python)

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Postgres · Redis 는 별도 기동 필요 (예: docker compose up db redis)
export DATABASE_URL=postgresql://user:password@localhost:5433/mcpdb
export CELERY_BROKER_URL=redis://localhost:6380/0
export PYTHONPATH=.

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 운영 배포 (HTTPS)

```bash
cd infra/docker
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d --build
```

Caddy 가 80/443 인계받아 Let's Encrypt 자동 발급. `Caddyfile` 의 도메인은 본인 소유 도메인으로 수정.

---

## 사용법

### 1) MCP 클라이언트에 등록

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

운영 환경 (HTTPS + OAuth):
```bash
claude mcp add --transport http mcper https://<your-domain>/mcp
# 첫 호출 시 브라우저로 OAuth 인증 페이지 열림
```

### 2) 에이전트에서 룰 받아오기

채팅 창에 자연어로 요청:
```
이 프로젝트 룰 받아와 줘
```

MCPER 가 Global + Repository + App 룰을 한 개의 마크다운으로 머지해 반환. 에이전트가 `CLAUDE.md` 또는 `.cursor/rules/...` 에 자동 저장.

### 3) 어드민 UI 에서 컨텐츠 관리

`http://localhost:8001/admin` 로그인 후:

- **Rules / Skills / Workflows / Docs** — Global · App · Repository 카테고리별 CRUD
- **기획서** — 앱별 카드 (이름 수정 / 내용 삭제 / 앱 삭제)
- **Users / RBAC** — Google 로그인으로 들어온 사용자에게 `(도메인, 앱, role)` 권한 부여
- **Celery** — 비동기 인덱싱 작업 모니터링

### 4) 환경 설정 (자주 쓰는 값)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | — | Postgres 연결 |
| `CELERY_BROKER_URL` | — | Redis (비우면 동기 폴백) |
| `ADMIN_USER` / `ADMIN_PASSWORD` | `admin` / `changeme` | 마스터 계정 |
| `MCPER_AUTH_ENABLED` | `false` | 사용자 인증 활성 |
| `AUTH_SECRET_KEY` | — | JWT/CSRF 서명 키 (인증 활성 시 필수) |
| `AUTH_GOOGLE_CLIENT_ID` / `AUTH_GOOGLE_CLIENT_SECRET` | — | 설정 시 로그인 페이지에 Google 버튼 노출 |
| `OAUTH_REDIRECT_BASE` | `http://localhost:8001` | OAuth 콜백 기본 URL |
| `EMBEDDING_PROVIDER` | `local` | `local`/`sidecar`/`openai`/`bedrock` |

`.env.local` 파일을 `infra/docker/` 에 두면 Compose 가 자동 로드.

---

## 더 알아보기

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — 내부 구조 상세
- [`docs/SECURITY.md`](docs/SECURITY.md) — 인증·권한·CSRF·CORS
- [`docs/RELIABILITY.md`](docs/RELIABILITY.md) — 운영·배포·스케일
- [`CHANGELOG.md`](CHANGELOG.md) — 변경 이력
