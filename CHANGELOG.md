# Changelog

모든 중요한 변경을 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식으로 기록.
버전 태그는 다음 릴리스 시 부여 예정 (현재 main 브랜치 누적).

## [Unreleased] — 2026-04-29 / 04-30 누적

두 세션에 걸쳐 감사 리포트(`docs/audit_2026-04-29.md`) 36건(P0×5 / P1×17 / P2×14)을 전수 해소하고, 스케일/LB 배치를 위한 선행 작업을 완료. `origin/main` 대비 55 커밋.

### Added

#### 신규 컨텐츠 타입 / 기능
- **Docs(문서) 컨텐츠 타입** 신규 추가 — Rules/Skills/Workflows 와 동급의 3계층(Global/Repository/App) 벡터검색 지원. (`250f405`)
- **Workflow Mermaid "한눈에 보기"** — 버전 단위 다이어그램 저장 + 어드민 모달 + MCP 조회/업로드 도구. (`220702f`, `2b33b22`, `de8e888`, `ebe8e4b`)

#### 스케일 / LB 준비 (환경변수 토글 기반, 기본 동작 변경 0)
- **L01–L03** `app/auth/session_store.py` — `MCPER_SESSION_STORE=memory|redis` 로 MCP OAuth 세션을 Redis 로 외부화. (`203b2ae`, `5539da5`)
- **L04–L05** 임베딩 sidecar 컨테이너 + `EMBEDDING_PROVIDER=sidecar` HTTP 백엔드. (`2ff0eb4`, `6788ccb`)
- **L06** PgBouncer 프로필 + `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` 환경변수화. (`1c508bf`)
- **L09** K8s/LB 호환 헬스 엔드포인트 3단계(`/health/live`, `/ready`, `/startup`) + 기존 `/health` alias 유지. (`6cc8525`)
- **L10** 프로세스 공용 Redis 클라이언트 풀 싱글톤. (`0d5c4d5`)

#### 테스트
- **Q10 초기 배치** — `tests/unit/test_tools_common.py`, `test_admin_rules_service.py`, `test_embeddings_backends.py`, `test_auth_service.py` 총 75 케이스. (`192a0f5`)
- **Phase2 확장** — `admin_rules_service` 21 추가(preview/list/get/delete/SectionPreview), `test_rule_cache.py` 26 케이스, `test_search_hybrid.py` 15(RRF) — 누적 **137 unit pass**. (`1ae39f1`, `0d414d0`)

#### 캐시 레이어
- **P12** `app/services/rule_cache.py` — `MCPER_RULE_CACHE=redis` 토글 시 `get_rules_markdown` Redis LRU 캐시 + `publish_*` 시 invalidate. 기본값에서는 no-op. (`40c7fca`)

### Changed

#### 대규모 구조 리팩터링
- **Q03** `app/routers/admin_rules.py` 1,849줄 → shell 325줄 + `admin_rules_global.py` (363) / `admin_rules_app.py` (582) / `admin_rules_repo.py` (585) 3 모듈 분할. main.py 에서 4개 병렬 include. URL·동작 완전 호환. (`7ee5001`)
- **Q04** `app/services/admin_rules_service.py` 신설 — 라우터의 `select()/delete()/func.count()` 직접 호출 13 지점을 서비스 함수로 이관. 라우터는 HTTP/템플릿만 담당. (`016ea64`)
- **Q09** `app/config.py` 373줄 → 스키마+싱글톤 153줄 + `app/config_merger.py` 349줄(defaults/YAML/env 병합 로직). 외부 API 동일. (`6ec40cd`)
- **Q12** `app/db/database.py` 사이드이펙트 import 11개 → `register_all_models()` 명시 함수 호출. (`4d3ceea`)

#### 코드 품질 통일
- **Q06** 공개 함수 반환 타입 100% 보강 — phase1 라우터 210개 + phase2 서비스·auth·main 전수. `ast.parse` 기반 스캔에서 누락 0건. (`0e482db`, `bd3ee76`)
- **Q07** `db = SessionLocal(); try/finally: db.close()` 패턴 25+ 블록을 `with SessionLocal() as db:` 로 통일. (`4d3ceea`)
- **Q11** 공개 함수 docstring 보강 — phase1 서비스/도구 55+건 + phase2 라우터 81건. (`32caeb0`, `b769bba`)
- **S07** MCP 도구 에러 응답 스키마 `{ok: false, error: str}` 통일 — `app/tools/_common.py` `error_payload`/`error_json` 헬퍼로 해당 도구 전수 전환. (`0b5cdb9`)

#### 성능
- **P01/P02** admin-rules 카드 목록 N+1 쿼리 제거 (101쿼리 → 3쿼리). (`9491f76`)
- **P03** `versioned_*` 테이블 `created_at` 인덱스 9개 추가.
- **P06** `list_sections_*` Python 정렬 → DB `DISTINCT ON`/`GROUP BY` 처리. (`f77f46e`)
- **P07** 어드민 카드 목록 서버사이드 페이지네이션 (`limit`/`offset`). (`9edc802`)
- **P08** `publish_repo` 이중 commit → 단일 트랜잭션 (`ensure_mcp_repo_pattern_pull_option(commit=False)`). (`6f69df8`)
- **P10** `IN(ranked_ids)` 후 Python 재정렬 → `ORDER BY CASE` DB 처리 (search_rules/skills/docs/workflows/hybrid). (`6f69df8`)
- **P11** 카드 목록에서 `body` TEXT 전체 로드 회피 — SQL `SUBSTRING(body, 1, 201)` 기반 preview 함수 3종 (`list_*_section_previews`). (`52682e5`)

### Fixed

- **Mermaid 모달 스크롤** — 긴 다이어그램의 위쪽 잘림 해결(`flex:1 1 auto` + `min-height:0`). (`de8e888`)
- **P09** `import_rules` 섹션 이중 순회 + `new_v` 마지막 값 바인딩 버그 수정. (`6f69df8`)
- **MCP stateful 세션** — Claude Code OAuth 호환을 위해 `stateless_http=False` 로 전환. (`57116e2`)
- **라이브 컨테이너 ADMIN_PASSWORD** 로컬 기본값을 랜덤 32자로 (S01/S02 기동 차단과 짝). (`284d7f6`)

### Security

- **S01/S02/S03/S06** 인증 활성(`MCPER_AUTH_ENABLED=true`) 상태에서 기본 `ADMIN_PASSWORD="changeme"` / 미설정 `AUTH_SECRET_KEY` 시 startup 차단(`RuntimeError`). (`633f178`)
- **S04** datasources postgres 백엔드 테이블명 화이트리스트 regex 검증. (`1f82814`)
- **S05** `data_tools` TOCTOU 제거 — 단일 세션에서 권한 검증 + 조회. (`6ff8bb8`)
- **S07** 에러 응답 스키마 통일 (위 Changed 참조). (`0b5cdb9`)
- **S08** CVE 4건 해소 + `python-jose` → `PyJWT` 마이그레이션:
  - `pdfminer.six` `20221105` → `20260107` (CVE-2025-64512 RCE, CVE-2025-70559 LPE)
  - `python-multipart` `0.0.22` → `0.0.27` (CVE-2026-40347 DoS)
  - `authlib` `1.6.9` → `1.6.11` (GHSA-jj8c-mmj3-mmgv OAuth CSRF)
  - `python-jose[cryptography]==3.5.0` → `PyJWT[crypto]==2.11.0`. 기존 `JWTError` 는 `InvalidTokenError` alias 로 하위 호환.
  - (`d68486f`, `cdd7f5b`)
- **S09** `docker-compose.test.yml` 하드코딩 테스트 암호 → `TEST_DB_PASSWORD`/`TEST_ADMIN_PASSWORD`/`TEST_AUTH_SECRET_KEY` env 외부화(기본값 유지). (`0b5cdb9`)

### Removed

- **Q13** vulture 데드코드 8건 제거 (`rollback_repo_rule` import, 미사용 `AnyUrl`/`OAuthAuthorizationServerProvider` import, `Index` import, `_skill_file_block` / `_workflow_file_block` 의 미사용 `section_display` 파라미터 등). 리포트: `docs/vulture_report_2026-04-30.md`. (`9354992`)

### Internal / Tooling

- **ruff format + lint** 전 코드 적용(117 파일 포맷, 자동 96건 + 수동 21건 린트 수정). (`09796eb`, `fa21f42`)
- pytest `asyncio_mode` 설정 제거 (async 테스트 미사용). (`911e76c`)
- 감사 리포트 `docs/audit_2026-04-29.md`, 설계 문서 3종(`docs/design-docs/session-store-redis.md`, `embedding-provider-migration.md`, `pgbouncer-setup.md`), vulture/deps audit 리포트 등.

### Verification Snapshot

- **Routes**: 240
- **MCP tools**: 51
- **Unit tests**: 137 pass (DB/Redis 의존 없이 MagicMock 기반)
- **Health endpoints**: `/health/live`, `/health/ready`, `/health/startup`, `/health/rag`, `/health` 모두 HTTP 200
- **ruff check**: clean (`app/` 전체)
- **`ast.parse` missing return type**: 0
- **MCP tool 함수 docstring 누락**: 0/51
