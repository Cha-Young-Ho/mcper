# Spec MCP (FastAPI + MCP Streamable HTTP + Postgres)

FastAPI 앱에 **MCP(Model Context Protocol)** 서버를 **Streamable HTTP**로 마운트하고, 기획서(`specs`) 저장·검색과 **브랜치 기반 시스템 프롬프트** MCP 툴을 제공한다. (Cursor는 URL 기반 연결 시 Streamable HTTP를 우선 사용한다.)

## 요구 사항

- Docker / Docker Compose (권장)
- 또는 Python **3.13+** (`mcp` 패키지 요구; 로컬 `python3` 버전은 `python3 --version` 으로 확인)

## 디렉터리 구조

```text
app/                     # 애플리케이션 패키지
  main.py                # FastAPI 앱, /health, MCP 마운트
  mcp_app.py             # FastMCP 인스턴스 + 툴 등록
  db/
  tools/
  services/
  prompts/
docker/
  Dockerfile
  docker-compose.yml
docs/
  mcp-rules.example.mdc   # Cursor `.cursor/rules/mcp-rules.mdc` 템플릿 (alwaysApply)
main.py                  # uvicorn 호환 진입점 (app.main re-export)
requirements.txt
```

## 환경 변수

| 변수 | 설명 | 예시 |
|------|------|------|
| `DATABASE_URL` | Postgres 연결 문자열 | `postgresql://user:password@db:5432/mcpdb` |
| `ADMIN_USER` | 어드민 UI HTTP Basic 사용자명 | `admin` |
| `ADMIN_PASSWORD` | 어드민 UI 비밀번호 (**운영에서는 반드시 변경**) | `changeme` |
| `GIT_DEFAULT_BASE_BRANCH` | Git에서 base를 못 쓸 때 기본 기준 브랜치 | `main` |
| `GIT_REPO_ROOT` | `git` 명령 실행 기준 경로 (선택) | `/path/to/repo` |

## Docker로 실행

프로젝트 **루트**에서:

```bash
docker compose -f docker/docker-compose.yml up --build
```

(`docker/docker-compose.yml`에 `name: spec-mcp`가 있어서 프로젝트/볼륨 이름이 `spec-mcp_*`로 잡힌다.)

**핫 리로드:** `web`은 `uvicorn --reload` + 볼륨 `..:/app` 으로 호스트에서 `app/` 등을 수정하면 프로세스가 다시 뜬다. `uvicorn[standard]`(watchfiles) + `WATCHFILES_FORCE_POLLING=1` 로 Docker Desktop에서도 감지가 잘 되게 해 두었다. 리눅스 네이티브 Docker만 쓰고 CPU가 아깝으면 compose에서 `WATCHFILES_FORCE_POLLING` 줄을 지워도 된다.

`db`는 `pg_isready` 헬스체크 후에만 `web`이 시작되도록(`depends_on: condition: service_healthy`) 맞춰 두었고, 앱 쪽 `init_db()`도 DB가 늦게 뜨는 경우 짧게 재시도한다.

- **HTTP (호스트)**: `http://localhost:8001` → 컨테이너 내부 `8000`
- **헬스체크**: `GET http://localhost:8001/health`
- **MCPER 어드민 (HTTP Basic)**: `http://localhost:8001/admin` — 대시보드(MCP **호출 수**), **기획서** / **기획서–코드**, **Rules**(접이식: Global / Repository / Apps), **Tools**(접이식 상세), 재시드. Compose 기본 계정은 `ADMIN_USER` / `ADMIN_PASSWORD` (기본값 `admin` / `changeme`).
- **Postgres (호스트에서 접속할 때만)**: `localhost:5433` → 컨테이너 `5432` (`web`은 Docker 네트워크 안에서 `db:5432`로 붙으므로 `DATABASE_URL` 변경 없음)

이미지만 빌드할 때:

```bash
docker build -f docker/Dockerfile -t spec-mcp .
```

## Cursor 규칙 파일 (자동 로드)

- **`get_global_rule` 2차 응답**은 **마크다운으로만** 내려가며, 에이전트가 **Cursor / Claude / Antigravity / Gemini** 등 사용 환경에 맞는 경로·포맷으로 저장한다 (응답 말미 CRITICAL 절 참고). Cursor 기본: **`.cursor/rules/mcp-rules.mdc`** + `alwaysApply: true`.
- **`.cursor.global`** 은 Cursor가 공식 “항상 읽기” 경로가 아니므로 쓰지 않는다.
- 형식 예시: [`docs/mcp-rules.example.mdc`](docs/mcp-rules.example.mdc)

## MCP (Cursor 연결)

**Cursor `mcp.json`의 `url`에는 아래를 넣으면 된다** (SSE 전용 URL `/mcp/sse`가 아님):

```json
"url": "http://localhost:8001/mcp"
```

| 용도 | 경로 (Compose 기준) |
|------|---------------------|
| Streamable HTTP (MCP 본체) | `http://localhost:8001/mcp` |

Docker가 떠 있는지, 포트가 `8001`인지 먼저 확인할 것.

## MCP 툴

1. **`upload_spec_to_db`** — `content`, `app_target`, `base_branch`, `related_files` → `specs` INSERT.
2. **`search_spec_and_code`** — `query`, `app_target` → 본문·`related_files` ILIKE 검색 (최대 50건, JSON).
3. **`get_global_rule`** — **조회 전용**. 인자: `app_name` (선택), `version` (선택), **`origin_url` (선택, 권장 — 에이전트가 `git remote -v` 로 얻은 origin fetch URL)**, `repo_root` (선택).  
   - `app_name` 없음: **global 만**. `version` 은 **global** 에 적용.  
   - `app_name` 있음: **global 최신** + **repository 룰**(URL 패턴; **`origin_url` 우선**, 없으면 서버 Git) + **앱 룰**; `version` 은 **앱 룰** 에만 적용.  
   - 요청한 `version` 행이 없으면 서버가 **최신으로 폴백**하고 본문에 안내 문구를 붙임.  
   - INI **`app_name` 만** (예: `your_app_name`). `/master` 등 금지.  
   - 2차 응답: MCP는 본문만 제공 → 에이전트가 환경별로 저장. Cursor 기본: `.cursor/rules/mcp-rules.mdc`. 예시: [`docs/mcp-rules.example.mdc`](docs/mcp-rules.example.mdc).
4. **`check_rule_versions`** — `app_name`·`origin_url`·`repo_root` (선택). 서버 DB **최신** global / app / repo 의 **버전 정수**만 JSON. 로컬 `rule_meta` 와 다르면 `get_global_rule` 로 다시 받아 로컬을 최신으로 맞출 것.
5. **`publish_global_rule`** — `body` 만. **버전 번호는 서버가 자동 증가** (클라이언트가 버전 지정 불가). JSON `{ "scope", "version" }` 반환.
6. **`publish_repo_rule`** — `pattern`, `body`. origin URL에 매칭되는 **패턴별** 다음 버전을 서버가 부여. JSON `{ "scope", "pattern", "version" }`.
7. **`publish_app_rule`** — `app_name`, `body` 만. **앱 룰 전체 본문**을 새 버전으로. JSON `{ "scope", "app_name", "version" }`.
8. **`append_to_app_rule`** — `app_name`, `append_markdown`. **최신 앱 룰 뒤에** 덧붙여 새 버전. JSON `{ "scope", "app_name", "version", "appended": true }`.

**에이전트 트리거:** 프로젝트 루트에 `.cursorrules`를 두고 "세션 시작 시 get_global_rule 호출" 문구를 넣으면 유리하다. 예시는 [`.cursorrules.example`](.cursorrules.example) 참고.

룰은 **Postgres**의 `global_rule_versions` / `repo_rule_versions` / `app_rule_versions` 를 사용한다. **런타임은 항상 DB 조회**만 한다. **최신 행은 `version = MAX(version)` 조건으로 조회**한다. 첫 기동 시 `app/db/seed_defaults.py` 가 global(md) + 앱·레포 초기 행을 ORM으로 넣는다(번들 `.sql` 파일 없음). 운영 변경은 **`/admin`** 또는 MCP `publish_*` / 호스트에서 `DATABASE_URL` 로 직접 DB 반영.

### 룰 시드

- **첫 기동**: `global_rule_versions`가 비어 있으면 `global_rule_bootstrap.md` + 앱·레포 기본 행을 한 번 자동 삽입한다.
- **기존 DB**: global 은 있는데 `repo_rule_versions`만 비어 있으면 기동(또는 `python scripts/seed_rules.py`) 시 repo 기본 행만 보충한다.
- **수동 (강제 덮어쓰기)**: 프로젝트 루트에서 (DB 접속 가능한 환경에서)

```bash
export PYTHONPATH=.
export DATABASE_URL=postgresql://user:password@localhost:5433/mcpdb   # 호스트에서 Docker DB 쓸 때 예시
python scripts/seed_rules.py --force
```

Docker Compose 안에서:

```bash
docker compose -f docker/docker-compose.yml exec web python scripts/seed_rules.py --force
```

## DB 스키마

기동 시 `init_db()`로 테이블 자동 생성.

| 테이블 | 용도 |
|--------|------|
| `specs` | 기획서 (`id`, `title` 선택, `content`, `app_target`, `base_branch`, `related_files` JSON). 첫 기동 시 `your_app_name` 예시 1건 자동 삽입 |
| `global_rule_versions` | 전역 룰, 버전 순증 (`version` 유니크, `body`, `created_at`) |
| `repo_rule_versions` | origin URL 패턴별 룰 (`pattern` + `version` 유니크, `sort_order`, `body`, `created_at`) |
| `app_rule_versions` | 앱별 룰 이력 (`app_name` + `version` 유니크, `body`, `created_at`) |
| `mcp_app_pull_options` | 앱별로 `get_global_rule` 시 `__default__` 앱 스트림을 **추가로** 붙일지 (`app_name` PK, `include_app_default`) — `/admin` 해당 앱 보드에서 토글 |
| `mcp_rule_return_options` | id=1 한 행. **Repository** `default`(빈 패턴) 스트림 병합 여부 (`include_repo_default`) — `/admin` Repository rules 목록에서 토글 |
| `mcp_tool_call_stats` | MCP 툴별 누적 호출 수 (`tool_name` PK, `call_count`) — `/admin` 대시보드 |

*(예전 `rule_templates` / `app_target_rules` / `repo_profile_rules` 테이블은 DB에 남아 있을 수 있으나 앱은 사용하지 않는다. 깨끗이 하려면 DB에서 수동 DROP.)*

**기존 DB에 `specs.title` 컬럼이 없으면:** 앱 기동 시 `init_db()` 안에서 `ALTER TABLE specs ADD COLUMN IF NOT EXISTS title …` 를 자동 실행한다. 수동으로 맞추려면:

```bash
psql "$DATABASE_URL" -f scripts/add_spec_title_column.sql
```

## 로컬 개발

**Python 3.13+** (프로젝트 표준). macOS 기본 `python3`가 3.9 이하면 [python.org](https://www.python.org/downloads/) 또는 `brew install python@3.13` 후 `python3.13 -m venv .venv` 등으로 맞춘다. 저장소 루트 `.python-version` 은 pyenv용 힌트다.

```bash
pip install -r requirements.txt
export PYTHONPATH=.
export DATABASE_URL=postgresql://user:password@localhost:5432/mcpdb
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

또는:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

선택: `pip install -e .` (의존성은 `requirements.txt`로 별도 설치).
