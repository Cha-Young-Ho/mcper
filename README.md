# Spec MCP (FastAPI + MCP Streamable HTTP + Postgres)

FastAPI 앱에 **MCP(Model Context Protocol)** 서버를 **Streamable HTTP**로 마운트하고, 기획서(`specs`) 저장·검색과 **브랜치 기반 시스템 프롬프트** MCP 툴을 제공한다. (Cursor는 URL 기반 연결 시 Streamable HTTP를 우선 사용한다.)

## 요구 사항

- Docker / Docker Compose (권장)
- 또는 Python **3.13+** (`mcp` 패키지 요구; 로컬 `python3` 버전은 `python3 --version` 으로 확인)

## 디렉터리 구조

```text
app/                     # 애플리케이션 패키지
  main.py                # FastAPI 앱, /health, MCP 마운트
  config.py              # config.yaml + 환경변수 병합 (Settings)
  mcp_app.py             # FastMCP 인스턴스 + 툴 등록
  mcp_dynamic_mount.py   # MCP 마운트 + Host 게이트 (DB 매 요청)
  asgi/mcp_host_gate.py  # MCP 앞단 Host/Origin 검사
  db/
  tools/
  services/
  prompts/
docker/
  Dockerfile
  docker-compose.yml
docs/
  mcp-rules.example.mdc   # Cursor `.cursor/rules/mcp-rules.mdc` 템플릿 (alwaysApply)
  repository-rule-mcper-specs.md  # 클라이언트 에이전트용: 기획서 업로드·검색 룰 (Repo rules / CLAUDE.md / .cursor 에 복사)
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
| `CELERY_BROKER_URL` | Redis 브로커 (비우면 스펙 청크 자동 인덱싱·코드 큐 비활성) | `redis://redis:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery 결과 백엔드 (선택, 기본은 broker와 동일) | `redis://redis:6379/0` |
| `EMBEDDING_DIM` | 벡터 차원(**선택한 sentence-transformers 모델 출력과 동일**해야 함). 기본 MiniLM → `384` | `384` |
| `LOCAL_EMBEDDING_MODEL` | HuggingFace / sentence-transformers 모델 id | `sentence-transformers/all-MiniLM-L6-v2` |
| `MCPER_CONFIG` / `MCPER_CONFIG_PATH` | 부트스트랩 YAML 경로 (선택) | `/app/config.yaml` |
| `MCP_ALLOWED_ORIGINS` | MCP `TransportSecurity`용 Origin 목록, 쉼표 구분 (선택) | `http://203.0.113.7:8001` |

루트에 [`config.example.yaml`](config.example.yaml) 을 참고해 `config.yaml` 을 두면 `server` / `mcp.mount_path` / `security.allowed_origins` / `database` / `celery` 등을 한곳에서 읽는다. YAML 문자열 안에는 ``${VAR}`` / ``${VAR:-기본값}`` 치환을 지원한다. **같은 항목은 표준 환경변수가 YAML 보다 우선**한다 (`DATABASE_URL`, `PORT`, `CELERY_BROKER_URL` 등 — [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) 의 `EnvBootstrapSettings`). **MCP에 허용할 `Host` 헤더** 는 YAML이 아니라 **어드민 → «MCP 연결»** DB.

**Docker 리빌드:** [`docker/Dockerfile`](docker/Dockerfile) 은 `requirements.txt` → `pip` → 소스 순으로 레이어를 쌓고, 루트 [`.dockerignore`](.dockerignore) 로 컨텍스트를 줄였다. `requirements.txt` 를 안 바꿨으면 코드만 고친 뒤 **이미지 리빌드 없이** 볼륨 마운트 + `uvicorn --reload` 만으로 반영된다.

**빌드 로그가 수 분 걸리는 흔한 이유**

| 구간 | 설명 |
|------|------|
| 의존성 설치 | [`sentence-transformers`](requirements.txt) 가 **PyTorch** 를 끌어오는데, 기본 PyPI 는 **CUDA(수 GB)** 휠을 잡는 경우가 많음. [`docker/Dockerfile`](docker/Dockerfile) 에서 **먼저** `torch` 를 [CPU 인덱스](https://download.pytorch.org/whl/cpu)로 깔고, 나머지는 **`uv pip install`** 로 처리해 시간·이미지 크기를 줄였음. |
| `exporting layers` | 레이어가 무거우면 압축·저장이 길어짐. **web / worker 가 같은 이미지 태그** (`spec-mcp:local`) 를 쓰면 동일 Dockerfile 을 **한 번만** 빌드·내보내기(이전에는 서비스마다 export 가 중복될 수 있음). |
| 매번 `--build` | **코드만** 고친 거면 `docker compose up` 만으로 충분하고 **`--build`는 생략**하는 게 맞음(볼륨 `..:/app` + `--reload`). **의존성/Dockerfile을 바꿨을 때만** `build` 또는 `up --build`. |

**가이드와의 차이 (이 레포 기준)** MCP 허용 **Host** 는 **어드민 «MCP 연결» + DB** 에 등록하고, **매 MCP 요청** [`app/asgi/mcp_host_gate.py`](app/asgi/mcp_host_gate.py) 에서 조회해 검사한다 (재시작·ASGI 갈아끼우기 불필요). SDK 쪽 DNS 리바인딩 검사는 끄고, **Origin** 은 `config`/환경변수 `allowed_origins` 로 [`mcp_host_gate`](app/asgi/mcp_host_gate.py) 에서 검사한다.

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
- **MCPER 어드민 (HTTP Basic)**: `http://localhost:8001/admin` — 대시보드(MCP **호출 수**), **기획서**(상세에서 **수정·삭제**, 삭제 시 `spec_chunks` CASCADE) / **기획서–코드**, **Rules**(접이식: Global / Repository / Apps), **Tools**(접이식 상세), 재시드. Compose 기본 계정은 `ADMIN_USER` / `ADMIN_PASSWORD` (기본값 `admin` / `changeme`).
- **Postgres (호스트에서 접속할 때만)**: `localhost:5433` → 컨테이너 `5432` (`web`은 Docker 네트워크 안에서 `db:5432`로 붙으므로 `DATABASE_URL` 변경 없음)
- **Redis (호스트)**: `localhost:6380` → 컨테이너 `6379` (Celery 브로커)
- **워커**: `worker` 서비스가 `celery`로 `index_spec` / `index_code_batch` 처리(임베딩·DB 쓰기는 FastAPI 메인과 분리)
- **Ollama (선택)**: `docker compose --profile local-embed -f docker/docker-compose.yml up` 시 `ollama` 컨테이너만 추가(호스트 직접 설치 대신 로컬 실험용). **임베딩은 기본적으로 sentence-transformers(로컬 CPU)** 만 사용한다.

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

**EC2 / 공인 IP로 붙일 때:** 클라이언트가 보내는 `Host` 와 정확히 같아야 한다. 예: `ports: "8001:8000"` 이면 Cursor URL 은 `http://<공인IP>:8001/mcp` 이고, 어드민 **«MCP 연결»** 에 `<공인IP>:8001` 을 등록한다. (이전의 Host 헤더를 `127.0.0.1` 로 바꾸는 우회 ASGI 는 제거되었다.)

**`/health` 는 200인데 MCP 만 `421` / `Invalid Host`:** DB·어드민에 **클라이언트가 보내는 `Host` 와 동일한** `host:port` 가 들어가 있는지 확인한다. 게이트는 [`mcp_host_gate`](app/asgi/mcp_host_gate.py) 가 **매 요청** DB를 본다. 여전히 이상하면 `mcp>=1.26.0` 과 이미지 재빌드를 확인한다.

## MCP 툴

1. **`upload_spec_to_db`** — `content`, `app_target`, `base_branch`, `related_files` → `specs` INSERT.
2. **`search_spec_and_code`** — `query`, `app_target` → `spec_chunks`가 있으면 **벡터+FTS+RRF** 하이브리드, 없으면 기존 ILIKE (JSON).
3. **`push_code_index`** — 코드 노드/엣지 JSON을 큐에 넣어 워커가 임베딩 후 `code_nodes`/`code_edges`에 저장.
4. **`analyze_code_impact`** — 질의로 시드 노드 후 그래프 상·하류 JSON.
5. **`find_historical_reference`** — 신규 기획 텍스트와 유사한 과거 스펙 청크·`related_files`.
6. **`get_global_rule`** — **조회 전용**. 인자: `app_name` (선택), `version` (선택), **`origin_url` (선택, 권장 — 에이전트가 `git remote -v` 로 얻은 origin fetch URL)**, `repo_root` (선택).  
   - `app_name` 없음: **global 만**. `version` 은 **global** 에 적용.  
   - `app_name` 있음: **global 최신** + **repository 룰**(URL 패턴; **`origin_url` 우선**, 없으면 서버 Git) + **앱 룰**; `version` 은 **앱 룰** 에만 적용.  
   - 요청한 `version` 행이 없으면 서버가 **최신으로 폴백**하고 본문에 안내 문구를 붙임.  
   - INI **`app_name` 만** (예: `your_app_name`). `/master` 등 금지.  
   - 2차 응답: MCP는 본문만 제공 → 에이전트가 환경별로 저장. Cursor 기본: `.cursor/rules/mcp-rules.mdc`. 예시: [`docs/mcp-rules.example.mdc`](docs/mcp-rules.example.mdc).
7. **`check_rule_versions`** — `app_name`·`origin_url`·`repo_root` (선택). 서버 DB **최신** global / app / repo 의 **버전 정수**만 JSON. 로컬 `rule_meta` 와 다르면 `get_global_rule` 로 다시 받아 로컬을 최신으로 맞출 것.
8. **`publish_global_rule`** — `body` 만. **버전 번호는 서버가 자동 증가** (클라이언트가 버전 지정 불가). JSON `{ "scope", "version" }` 반환.
9. **`publish_repo_rule`** — `pattern`, `body`. origin URL에 매칭되는 **패턴별** 다음 버전을 서버가 부여. JSON `{ "scope", "pattern", "version" }`.
10. **`publish_app_rule`** — `app_name`, `body` 만. **앱 룰 전체 본문**을 새 버전으로. JSON `{ "scope", "app_name", "version" }`.
11. **`append_to_app_rule`** — `app_name`, `append_markdown`. **최신 앱 룰 뒤에** 덧붙여 새 버전. JSON `{ "scope", "app_name", "version", "appended": true }`.

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
| `mcp_app_pull_options` | 앱별로 `get_global_rule` 시 `__default__` 앱 스트림을 **추가로** 붙일지 (`app_name` PK, `include_app_default`) — `/admin` 앱 카드·앱 보드에서 토글. 행이 없으면 `mcp_rule_return_options.include_app_default` 전역 기본값 사용 |
| `mcp_repo_pattern_pull_options` | Repository **패턴**(카드)마다 `default`(빈 패턴) repo 스트림 병합 여부 (`pattern` PK, `include_repo_default`) — `/admin` Repository rules 카드에서 토글. 행이 없으면 `mcp_rule_return_options.include_repo_default` 로 폴백 |
| `mcp_rule_return_options` | id=1 한 행. `include_repo_default`: 패턴별 옵션 행이 없을 때 repo default 병합 폴백. `include_app_default`: 앱별 옵션 행이 없을 때 앱 default 병합 기본값 — `/admin` Global rules 보드에서 전역 토글 |
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
