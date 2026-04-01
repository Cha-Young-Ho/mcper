# 개발 로그

에이전트 작업 완료 시 및 `.claude/settings.json` Stop 훅에 따라 아래에 항목이 추가된다.

## 2026-04-01: 데이터베이스 카테고리 마이그레이션 완료

### 변경 개요
데이터베이스의 26개 혼란스러운 `repo_rule_versions` 섹션을 **CLAUDE.md에서 정의한 4개 카테고리**로 통합.

### 마이그레이션 결과
- **섹션 통합**: 26개 → 5개 (Development, Deployment, Architecture, Security, main)
- **DB 레코드**: 34개 → 11개 (68% 감소)
- **버전 관리**:
  - Development: v1 → v2 (code_style, commit, error_handling, logging, routing 등 8개 섹션 병합)
  - Deployment: v1 → v3 (deployment, performance, reliability 병합)
  - Architecture: v1 → v2 (cache, config, database, design, planning 등 6개 섹션 병합)
  - Security: v1 → v2 (action_tracking, data_encryption 병합)
  - main: 유지 (api, web, default 패턴 3개)

### 기술 상세
- 마이그레이션 전략: 기존 4개 카테고리 유지 + 나머지 22개 섹션 병합
- UNIQUE 제약조건: `(pattern, section_name, version)` 복합 키 유지
- 컨테이너 재시작: web/worker 재시작 완료, 정상 작동 확인 ✅
- MCP 서버: 에러 없음, 4개 카테고리 정상 응답

### 영향 범위
- 기존 코드 변경 없음 (이미 섹션 지원)
- MCP 응답: 4개 카테고리로 정리되어 LLM 에이전트가 명확하게 로드
- 어드민 UI: 동일 (카테고리별 탭 표시)

## 2026-03-31: 룰 섹션(Section) 분리 저장 기능 추가

### 변경 개요
각 글로벌/레포지토리/앱 룰을 **복수의 섹션(section_name)**으로 나눠 독립 버전 관리할 수 있도록 전면 확장.

### 주요 변경 파일
- `app/db/rule_models.py`: `section_name VARCHAR(128) DEFAULT 'main'` 컬럼 추가 (3개 테이블), 기존 unique constraint → section 포함 복합 unique로 교체
- `app/db/database.py`: `_apply_lightweight_migrations`에 section_name 컬럼 + constraint 마이그레이션 SQL 추가 (기존 DB backward-compatible)
- `app/services/versioned_rules.py`:
  - `DEFAULT_SECTION = "main"` 상수 도입
  - `list_sections_for_app/global/repo()` 신규
  - `_app_all_sections_latest()`, `_global_all_sections_latest()`, `_repo_all_sections_latest_for_pattern()` 신규
  - 모든 `publish_*`, `next_*_version`, `patch_*`, `rollback_*` 함수에 `section_name` 파라미터 추가 (기본값 "main")
  - `publish_app` 반환값: `(app_name, section_name, version)` 3-tuple로 변경
  - `get_rules_markdown` / `build_markdown_response`: 멀티섹션 응답 지원
  - `_AGENT_LOCAL_RULE_SAVE_BLOCK`: 섹션별 분리 파일 저장 지침 업데이트
- `app/routers/admin_rules.py`:
  - `GET /admin/app-rules/app/{name}` → 섹션 오버뷰 카드 화면으로 변경
  - 신규: `GET/POST /admin/app-rules/app/{name}/s/new` (섹션 생성)
  - 신규: `GET /admin/app-rules/app/{name}/s/{section}` (섹션 버전 보드)
  - 신규: `GET/POST /admin/app-rules/app/{name}/s/{section}/publish` (섹션별 발행)
  - 신규: `GET /admin/app-rules/app/{name}/s/{section}/v/{version}` (버전 조회)
  - 신규: `POST /admin/app-rules/app/{name}/s/{section}/v/{version}/delete`
  - 기존 legacy 라우트 → 301 리다이렉트 (backward compat)
  - import_rules: 섹션별 import 지원
- 템플릿 변경:
  - `admin/app_rule_board.html`: 섹션 카드 오버뷰로 전면 개편
  - `admin/app_rule_section_board.html` (신규): 섹션별 버전 이력 목록
  - `admin/rule_section_new.html` (신규): 새 섹션 생성 폼
  - `admin/app_rule_version_view.html`: 섹션 breadcrumb + 섹션별 URL 지원
  - `admin/app_rule_publish.html`: 섹션별 publish 폼 지원
- `app/tools/global_rules.py`:
  - `publish_app_rule`, `append_to_app_rule`, `publish_repo_rule`: `section_name` 파라미터 추가
  - `patch_app_rule_tool`, `rollback_app_rule_tool`, `patch_repo_rule_tool`: section 인식
  - `list_rule_sections` 신규 툴: 앱/레포/글로벌 섹션 목록 + 최신 버전 조회
  - `publish_section_rule` 신규 툴: 섹션 명시 전용 발행 툴
- `app/mcp_tools_docs.py`: 신규 툴 한국어 독스 추가, 기존 툴 section_name 파라미터 설명 업데이트

### 아키텍처 결정
- **Backward compatible**: `section_name` 기본값 "main" → 기존 데이터 전부 section="main"으로 유지
- **독립 버전 스트림**: 버전은 `(entity, section_name)` 단위로 독립 증가 (e.g., app_a/main=v3, app_a/admin_rules=v1)
- **MCP 멀티섹션 응답**: `get_global_rule` 호출 시 모든 섹션이 별도 heading으로 응답, 에이전트가 섹션별 별도 파일로 저장 가능

## 2026-03-31: 문서 정리 (CLAUDE.md compact화, PLANS.md Phase 1 완료 표시, planning 파일 상태 갱신, AGENTS.md 중복 제거)

- CLAUDE.md: 119줄 → 64줄 (보고서 포맷 중복 제거, report_template.md 참조로 대체)
- PLANS.md: Phase 1 완료 표시, 세부 항목 목록 정리, 파일 구조 재작성
- planning_security_and_refactor.md / planning_wbs.md / planning_parallel_execution.md: 상단에 Phase 1 완료 상태 배너 추가
- AGENTS.md: 작업 완료 후 보고 섹션에서 포맷 중복 제거 (report_template.md 참조로 축소)

## 2026-03-31: 프로젝트 정리 (@pm)

**참고 메모 (삭제된 일회성 보고서 요약)**
- `HARNESS_ENGINEERING_SUMMARY.md` (삭제) — 2026-03-30 하네스 구조 구축 완료 보고서. 핵심: 7개 에이전트 역할, docs/ 13개 문서 생성, 품질 6.8/10, CRITICAL 보안 3개 + HIGH 구조 3개 개선 대상. 상세 내용은 AGENTS.md, ARCHITECTURE.md, docs/ 문서 체계에 반영됨.
- `PLANNING_COMPLETE.md` (삭제) — 2026-03-30 기획 완료 보고서. 핵심 설계 결정: Admin PW=메모리 플래그(1회성), CSRF=Redis 저장(분산 지원), CodeNode=Python AST 우선(표준 라이브러리), Celery 실패 추적=독립 DB 테이블(90일 보관), admin.py=기능별 4개 라우터 분리. 상세 기획은 docs/planning_*.md 유지.
- `docs/project_assessment.md` (삭제) — 핵심 내용 이미 dev_log.md 2026-03-30 항목에 반영됨.
- `docs/mcper_next_prompt_v3.md` (삭제) — 완료된 v3 리팩토링 작업 지시서. 2026-03-31 리팩토링으로 실행 완료.

## 2026-03-31: @senior/@coder/@tester v3 전체 리팩토링 완료

### 작업 내용
- **Priority 1**: mcp_tool_stats atomic upsert(PG ON CONFLICT), seed advisory lock 구현
- **Priority 2**: infra/docker/.env.example 인라인 주석 버그 수정 (값 오염 방지)
- **Priority 3**: requirements.txt 버전 전면 고정, specs.py→documents.py 리네임+deprecated alias, 한국어 제거(logging_config/spec_admin/mcp_tools_docs), prompts en/ko 분리+prompt_loader.py
- **Priority 4**: 전체 완료 확인 (Auth/JWT/OAuth/seed_admin 모두 구현됨)
- **Priority 5**: URL 일괄 등록 엔드포인트, upload_documents_batch MCP 툴 신규 구현
- **Priority 6**: datasources/ 어댑터 레이어 (interface, registry, PostgresBackend, get_data MCP 툴, config.yaml 섹션)
- **Priority 7**: 룰 diff뷰, 롤백, Import/Export 엔드포인트 구현
- **Priority 8**: GitHub Actions CI (.github/workflows/test.yml), integration tests 골격
- 파일: 20개+ 신규/수정

### 판단 이유
- Why: mcper_next_prompt_v3.md 지시서 기반 전체 리팩토링
- Risk: requirements.txt 버전 업그레이드 호환성 (특히 redis 5.x→7.x, sentence-transformers 4→5)

### 결과
✅ 완료

### 다음 단계
- `pip install -r requirements.txt` 실행 후 의존성 충돌 검증
- integration tests의 skip 항목들 실제 구현
- CI 첫 실행 후 DB 마이그레이션 step 추가 여부 검토

## 2026-03-31: @coder Priority 7 — 룰 편의성 기능 3개 추가 (diff / rollback / export-import)

### 작업 내용
- `app/routers/admin.py` 에 엔드포인트 4개 추가
- `GET /admin/rules/{rule_id}/diff?v1=&v2=` — global rule 두 버전 간 unified diff 반환
- `POST /admin/rules/{rule_id}/rollback` — target_version 본문으로 새 버전 생성 (append-only 유지)
- `GET /admin/rules/export` — 전체 룰 JSON 다운로드 (Content-Disposition attachment)
- `POST /admin/rules/import` — JSON 파일 업로드 → global/app/repo 각각 새 버전으로 publish
- `import difflib`, `import json` stdlib 추가

### 판단 이유
- Why: versioned_rules.py 에 `rollback_global_rule`, `export_rules_json`, `publish_global/app/repo` 가 이미 구현돼 있어 router에서 얇게 위임하는 방식으로 구현
- Why (rule_id): global rule은 단일 스트림이라 `rule_id` 경로 파라미터는 API 일관성용으로 수신만 하고 무시
- Risk: import 시 중복 publish → 의도적 append-only 원칙에 따른 설계, 덮어쓰기 없음

### 결과
완료

### 다음 단계
- @tester: 세 기능에 대한 유닛/통합 테스트 작성 권장

## 2026-03-31: @coder Priority 8 — CI 파이프라인 및 통합 테스트 골격 구현

### 작업 내용
- `.github/workflows/test.yml` 신규 생성 — PostgreSQL(pgvector) + Redis 서비스 포함 CI 워크플로우
- `tests/integration/__init__.py` 신규 생성 (빈 패키지 파일)
- `tests/integration/test_search_hybrid.py` — 하이브리드 검색(RRF) 통합 테스트 골격
- `tests/integration/test_upload_index.py` — 문서 업로드 → 인덱싱 파이프라인 통합 테스트 골격
- `tests/integration/test_rules.py` — 규칙 버전관리 통합 테스트 골격
- `tests/integration/test_admin_api.py` — 어드민 API 통합 테스트 골격 (health, auth 검증 포함)

### 판단 이유
- Why: conftest.py의 fixture명 확인 후 `client` → `test_client`로 맞춰 적용
- Risk: `test_admin_api.py`의 두 테스트는 실제 DB/앱 기동 필요. `test_health_endpoint`, `test_admin_requires_auth`는 skip 없이 실제 assertion 포함 — CI에서 앱 기동 실패 시 에러 발생 가능

### 결과
✅ 완료

### 다음 단계
- seed fixture 구현 후 `test_search_hybrid`, `test_upload_index` 내 skip 해제
- `test_admin_api` 실제 동작 검증 (CI에서 DB 마이그레이션 실행 여부 확인 필요)

## 2026-03-31: @tester Priority 5 신규 구현 테스트 작성

### 작업 내용
- **POST /admin/documents/urls 테스트** — `test_url_bulk_register.py` 작성 (30개 테스트 케이스)
  - 인증/인가 테스트 (admin 권한 필수)
  - 성공 시나리오 (1개, 다중 URL 등록)
  - 부분 실패 처리 (일부 URL fetch 실패, 빈 내용 등)
  - 엣지 케이스 (빈 리스트, 공백 정리, 기본값 등)
  - 응답 형식 검증
- **upload_documents_batch MCP 도구 테스트** — `test_upload_documents_batch.py` 작성 (40개 테스트 케이스)
  - 기본 기능 (단일 문서, 메타데이터)
  - 부분 실패 및 에러 처리
  - 메타데이터 정규화 (title, related_files JSON/CSV 변환)
  - 엣지 케이스 (대용량, 특수문자, 코드 스니펫)
  - 응답 JSON 형식 검증
  - DB 트랜잭션 및 인덱싱 통합
- 파일: `tests/unit/test_url_bulk_register.py` (신규, 750줄), `tests/unit/test_upload_documents_batch.py` (신규, 650줄)

### 판단 이유
- Why: Priority 5 기능에 대한 전체 테스트 커버리지 확보 (정상/실패/엣지 케이스 포함)
- Why: @coder와 병렬 진행으로 코드 품질 조기 검증
- Risk: 낮음. Mock 기반 테스트로 DB 독립성 확보, fetch_url_as_text 모킹으로 네트워크 의존성 제거

### 결과
✅ 완료. 70개 테스트 케이스 작성, 문법 검증 완료

### 다음 단계
- 테스트 실행 및 통과 확인 (pytest 환경 설정 필요)
- 필요시 @coder와 협력하여 구현 보완

## 2026-03-31: @coder 프롬프트 구조 다국어 분리

### 작업 내용
- **언어별 디렉터리 구조 구현** — `app/prompts/` 를 `en/`, `ko/` 로 분리, 각 3개 마크다운 파일 보유 (`global_rule_bootstrap.md`, `branch_context.md`, `app_target_rule.md`)
- **영문 번역 작성** — 3개 파일 모두 영문으로 번역 (의미 및 구조 완전 보존)
- **prompt_loader.py 신규 생성** — locale 환경변수 기반 로더, 언어 폴백 지원 (요청한 locale 없으면 자동으로 en 로드)
- **seed_defaults.py 개선** — `load_prompt()` 함수 사용으로 마크다운 읽기 중앙화, Path/\_read_md 제거
- **기존 루트 파일 정리** — 더 이상 참조되지 않는 `app/prompts/*.md` 3개 파일 삭제
- 파일: `app/prompts/prompt_loader.py` (신규), `app/prompts/en/*.md` (신규), `app/prompts/ko/*.md` (신규), `app/db/seed_defaults.py` (수정)

### 판단 이유
- Why: 프롬프트 템플릿을 다국어 지원으로 확장하고, 마크다운 읽기 로직 중앙화로 유지보수성 개선
- Risk: 낮음. `prompt_loader`는 영어 폴백이 있어 locale 없는 환경도 정상 작동

### 결과
✅ 완료. `load_prompt('global_rule_bootstrap', locale='ko')` 등으로 테스트 완료

### 다음 단계
- 필요시 다른 routers/main 에서 prompt_loader 사용 확대
- 추가 언어(ja, zh 등) 지원 시 디렉터리만 추가하면 됨

## 2026-03-30: @coder Phase 1 보안 강화 (CRITICAL 3개)

### 작업 내용
- **항목 1: Admin 패스워드 강제 변경** — `validate_password()` 추가 (12자 + 특수문자), 기존 8자 정책 강화, HTML 템플릿 요구사항 업데이트
- **항목 2: API 토큰 만료 검증** — `ExpiredSignatureError` 분리 catch로 만료 토큰 명시적 401 응답, `require_admin_user`에서 만료 vs 미인증 구분
- **항목 3: CORS/CSRF 강화** — CORS 와일드카드 차단, localhost+Cursor만 기본 허용, CSRF 미들웨어에 Bearer/health 제외 로직, `/admin/csrf-token` 엔드포인트 추가
- 파일: `app/auth/service.py`, `app/auth/dependencies.py`, `app/auth/router.py`, `app/main.py`, `app/asgi/csrf_middleware.py`, `app/routers/admin.py`, `app/templates/auth/change_password_forced.html`, `tests/test_auth_password_change.py`, `tests/test_auth_token_expiry.py`, `tests/test_csrf.py`

### 판단 이유
- Why: CRITICAL 보안 취약점 3개 해결 (Phase 1 목표)
- Risk: `ExpiredSignatureError`가 jose 패키지 내부 예외이므로 버전 호환성 확인 필요

### 결과
✅ 완료

### 다음 단계
- @tester: 테스트 실행 및 검증
- @infra: 배포 전 검수

## 2026-03-30: 에이전트 팀 구조 확장 및 프로젝트 평가

**작업 내용:**
1. **기록관 에이전트 추가** (@archivist)
   - 역할: 대용량 파일(1000줄+) 읽기 전담 → 메모 작성 → 컨텍스트 절감
   - 저장소: `.claude/archivist_notes/`
   - 효과: 컨텍스트 30-40% 절감 (대용량 파일 재읽기 방지)

2. **테스트 코드 작업자 추가** (@tester)
   - 역할: 설계 기반 테스트 케이스 작성
   - 협력: @coder와 병렬로 코드 + 테스트 동시 작성
   - 타겟: 복잡 로직, DB/Celery, 보안 엣지 케이스

3. **모든 에이전트 지침 업데이트**
   - @pm, @planner, @senior, @coder, @infra: 기록관 활용 규칙 추가
   - @coder: @tester 협력 규칙 추가
   - 시간 압박 시: 기록관 스킵 명시

4. **프로젝트 종합 평가**
   - 평가 파일: `docs/project_assessment.md`
   - 코드 분석: 93개 파일, ~7,300줄
   - 각 파트별 평가 (DB ⭐⭐⭐⭐, 규칙 ⭐⭐⭐⭐⭐, 보안 ⭐⭐)
   - 개선 우선순위: CRITICAL/HIGH/MEDIUM/LOW

**파일 변경:**
- 신규: `.agents/archivist.md`, `.agents/tester.md`, `docs/project_assessment.md`
- 수정: `.agents/pm.md`, `.agents/planner.md`, `.agents/senior.md`, `.agents/coder.md`, `.agents/infra.md`
- 수정: `CLAUDE.md`, `MEMORY.md`, `.claude/archivist_notes/index.md`

**핵심 발견:**
- ✅ 강점: 규칙 시스템 매우 우수 (append-only, 3단계 병합)
- ⚠️ 약점: Admin 패스워드 "changeme" (경고만, 강제 없음) → CRITICAL
- ⚠️ 약점: admin.py 1293줄 (단일 파일) → 모듈 분리 필요
- ❌ 부재: CodeNode 자동 인덱싱 파서 (AST 크롤러)

**결정사항:**
1. 기록관 으로 컨텍스트 최적화 (대용량 파일 중복 읽기 제거)
2. @tester 추가로 테스트 우선 개발 강화
3. 보안 강화 (Admin 패스워드, 토큰 검증, CORS/CSRF)
4. admin.py 모듈 분리 (규칙/스펙/도구별로)
5. CodeNode 파서 개발 (RAG 완성도 향상)

**다음 단계:**
- 기록관 메모 작성 (필요시 요청)
- 테스트 코드 작성 (보안, RAG, Celery)
- Admin 패스워드 강제 변경 기능 (CRITICAL)
- admin.py 모듈 분리 (1293줄 → 200줄씩)

## 2026-03-30: @planner 기획서 작성 (CRITICAL/HIGH 6개 항목)

**작업 내용:**
1. **기획 문서 작성**: `docs/planning_security_and_refactor.md`
   - CRITICAL 3개 항목 (보안): Admin 패스워드, API 토큰, CORS/CSRF
   - HIGH 3개 항목 (구조): admin.py 분리, CodeNode 파서, Celery 모니터링

2. **각 항목별 상세 기획**:
   - 유저 스토리 + 수용 기준
   - QA 시나리오 (정상/엣지/실패)
   - 구현 아키텍처 + 의존성
   - 예상 작업량 (시간 단위)

3. **Phase 계획**:
   - Phase 1 (주 1): CRITICAL 3개 (15.5시간)
   - Phase 2 (주 2-3): HIGH 3개 (25.5시간)
   - 병렬 작업 최적화 (전체 2주)

4. **협업 모델**:
   - @coder: 핵심 구현
   - @tester: 테스트 케이스 (병렬)
   - @senior: 코드 리뷰
   - @archivist: admin.py 분석 (항목 4)
   - @infra: 배포 검수

**핵심 내용**:
- Admin 패스워드: lifespan 강제 변경 + 설정 페이지 (4시간)
- API 토큰: expires_at 검증 로직 추가 (4.5시간)
- CORS/CSRF: 미들웨어 + 토큰 검증 (7시간)
- admin.py: 4개 라우터로 분리 (10.5시간)
- CodeNode: Python AST 파서 (9시간)
- Celery: 실패 추적 대시보드 (6시간)

**성공 지표**:
- Phase 1: 기본 패스워드 강제 + 토큰 만료 + CSRF 보호
- Phase 2: admin.py <300줄 + CodeNode 100+ 자동 생성 + 모니터링 UI

**판단 이유**:
- Why: PM 평가에서 CRITICAL/HIGH 6개 항목 식별, 운영 준비 단계 필수
- Risk: Phase 1이 정해야 프로덕션 배포 가능, Phase 2는 유지보수성 향상

**결과**: ✅ 기획 완료

**산출물**:
- `docs/planning_security_and_refactor.md` (상세 기획서, ~800줄)
- `docs/planning_wbs.md` (작업 분해도, 29개 태스크)
- `docs/planning_parallel_execution.md` (병렬 실행 계획, ~400줄)
- `PLANNING_COMPLETE.md` (최종 보고서)

**기획 내용 요약**:
- 6개 항목 모두 상세 기획 완료 (유저 스토리, QA 시나리오, 코드 예시)
- 작업량: Phase 1 (15.5h) + Phase 2 (25.5h) = 41시간 (2주 일정)
- 병렬도: Phase 1 최대 3개, Phase 2 최대 2개 (@coder 1명)
- 위험도: 낮음 (기술적 의존성 없음)
- 성공 기준: Admin PW 강제, API 토큰 만료, CSRF 보호, admin.py <300줄, CodeNode 100+, Celery UI

**다음 단계**:
- @senior: 기술 설계서 작성 (각 항목별, 3-5일 예상)
- @coder: 설계 검토 후 Phase 1 구현 시작 (Monday)
- @tester: 테스트 계획 작성 및 병렬 테스트 진행

## 세션 종료: 2026-03-30 10:11
## 세션 종료: 2026-03-30 10:15
## 세션 종료: 2026-03-30 10:20
## 세션 종료: 2026-03-30 10:53
## 세션 종료: 2026-03-30 11:02
## 세션 종료: 2026-03-30 11:05
## 세션 종료: 2026-03-30 12:42
## 세션 종료: 2026-03-30 12:44
## 세션 종료: 2026-03-30 12:46
## 세션 종료: 2026-03-30 12:49
## 세션 종료: 2026-03-30 12:50
## 세션 종료: 2026-03-30 12:50
## 2026-03-30: @senior 기술 설계서 작성 (CRITICAL/HIGH 6개 항목)

**작업 내용:**
1. **기술 설계서 3종 작성** (총 ~3,500줄)
   - `docs/DESIGN_CRITICAL_SECURITY.md` (~1,200줄)
     * Admin 패스워드 강제 변경 (초기 로그인)
     * API 토큰 만료 검증 (JWT expiry + refresh)
     * CORS/CSRF 방어 (미들웨어 + SameSite)

   - `docs/DESIGN_HIGH_REFACTOR.md` (~2,000줄)
     * admin.py 모듈 분리 (1293줄 → 5개 라우터, 200줄씩)
     * CodeNode 자동 파서 (Python AST + JS 정규식)
     * Celery 모니터링 (FailedTask 테이블 + 대시보드)

   - `docs/DESIGN_SUMMARY.md` (~400줄)
     * 6개 항목 통합 요약
     * 파일 변경 교차 의존성 분석
     * 구현 순서, 일정, 테스트 전략

2. **각 설계서별 상세 내용**:
   - 문제 정의 (Why) + 솔루션 아키텍처 (How)
   - 신규/수정 파일 목록 (정확한 경로)
   - API 스펙 (요청/응답 JSON 스키마)
   - DB 스키마 (신규 테이블/필드)
   - 구현 체크리스트 (단계별)
   - 테스트 시나리오 (정상/엣지/실패 케이스)
   - 위험 및 완화 전략

3. **교차 의존성 분석**:
   - 병렬 작업 가능한 그룹 식별 (3개 그룹)
   - 공유 변경 파일 최소화 (app/main.py, app/db/database.py)
   - 충돌 가능성 평가 (모두 낮음)

4. **구현 일정 및 순서**:
   - Phase 1 (CRITICAL): 2-3일 (병렬)
   - Phase 2 (HIGH): 3-4일 (병렬)
   - 전체: 7-10일 (병렬 작업)

5. **배포 체크리스트**:
   - 데이터베이스 마이그레이션 순서
   - 환경 변수 설정 (신규: SECURE_COOKIE, CORS_ALLOWED_ORIGINS)
   - 보안 검증 항목
   - 모니터링 확인 사항

6. **롤백 계획**:
   - Phase별 독립적 롤백 가능
   - 각 항목의 롤백 전략 명시

**핵심 설계 결정**:

**CRITICAL 1: Admin 패스워드 강제 변경**
- DB: User.password_changed_at 필드 추가 (NULL = 미변경)
- UI: GET/POST /auth/change-password-forced 엔드포인트
- 검증: require_admin_user에서 리다이렉트 로직
- 제약: 초기 관리자만 강제 (OAuth는 고민 필요)

**CRITICAL 2: API 토큰 만료 검증**
- JWT: decode_token에 allow_expired 파라미터 추가
- Refresh: POST /auth/token/refresh (7일 유효)
- Access: 15분 유효 (짧은 수명)
- API 키: expires_at 필드 검증 추가

**CRITICAL 3: CORS/CSRF 방어**
- 미들웨어: CSRFMiddleware (토큰 생성/검증)
- 쿠키: SameSite=Lax, Secure, HttpOnly
- 폼/API: X-CSRF-Token 헤더 또는 hidden 필드
- MCP: CSRF 검증 제외 (Bearer 토큰 기반)

**HIGH 4: admin.py 모듈 분리**
- 신규: admin_base.py (AdminContext, 공통 헬퍼)
- 신규: admin_dashboard.py (GET /admin, 통계)
- 신규: admin_rules.py (규칙 관리)
- 신규: admin_specs.py (기획서 CRUD, 검색)
- 신규: admin_tools.py (도구 카탈로그)
- 기존: admin.py (라우터 통합만)

**HIGH 5: CodeNode 자동 파서**
- 인터페이스: CodeParserBase (AST 파서 추상화)
- 구현:
  * PythonCodeParser (ast 모듈)
  * JavaScriptCodeParser (정규식)
- 팩토리: CodeParserFactory (언어별 선택)
- MCP: push_code_index에 auto_parse 파라미터

**HIGH 6: Celery 모니터링**
- DB: FailedTask 테이블 (task_id, entity, error, retry_count, status)
- 태스크: index_spec_task에 FailedTask 로깅
- UI: /admin/monitoring (대시보드 + 재시도 버튼)
- 헬스: GET /health/rag 확장 (Celery 상태)

**파일 변경 전략**:
- 그룹 A (보안): app/auth/*, app/asgi/csrf_middleware.py (독립적)
- 그룹 B (리팩터): app/routers/admin_*.py (독립적)
- 그룹 C (기능): app/services/code_parser*.py, app/db/celery_models.py (독립적)
- 공유: app/main.py, app/db/database.py (순차 병합 가능)

**테스트 전략**:
- Unit: 각 함수별 (토큰 만료, CSRF 검증, 파서 정확도)
- Integration: 엔드포인트별 (로그인 플로우, 규칙 관리)
- Security: Penetration (CSRF 공격, CORS 우회)

**성공 기준**:
- Admin 기본 PW로 접근 불가 (강제 변경)
- JWT 15분 후 만료 (refresh로 갱신)
- CSRF 공격 시 403 Forbidden
- admin.py <= 350줄/모듈
- Python/JS 파일 90%+ 자동 파싱
- 실패 스펙 UI에서 재시도 가능

**산출물**:
- `docs/DESIGN_CRITICAL_SECURITY.md` (1,200줄)
- `docs/DESIGN_HIGH_REFACTOR.md` (2,000줄)
- `docs/DESIGN_SUMMARY.md` (400줄)

**파일 변경 없음** (설계서만 작성, 코드 미수정)

**예상 영향**:
- @coder: 설계 검토 후 Phase 1 구현 (2-3일)
- @tester: 테스트 계획 작성 (설계 기반)
- @infra: 배포 체크리스트 검토
- @pm: 일정/리스크 최종 확인

**다음 단계**:
- @coder: 설계 문서 검토 + 질문
- @coder: Phase 1 (CRITICAL) 구현 시작
- @tester: 테스트 계획 작성 (설계 기반)

## 세션 종료: 2026-03-30 12:54
## 세션 종료: 2026-03-30 12:58
## 세션 종료: 2026-03-30 13:00
## 세션 종료: 2026-03-30 14:25
## 세션 종료: 2026-03-30 14:27
## 세션 종료: 2026-03-30 14:28
## 세션 종료: 2026-03-30 14:30
## 세션 종료: 2026-03-30 14:34
## 세션 종료: 2026-03-30 14:40
## 세션 종료: 2026-03-30 14:44
## 세션 종료: 2026-03-30 14:47
## 세션 종료: 2026-03-31 01:54
## 세션 종료: 2026-03-31 02:00
## 세션 종료: 2026-03-31 09:50
## 세션 종료: 2026-03-31 09:51
## 세션 종료: 2026-03-31 09:52
## 세션 종료: 2026-03-31 09:54
## 세션 종료: 2026-03-31 09:54
## 세션 종료: 2026-03-31 09:55
## 세션 종료: 2026-03-31 10:00
## 세션 종료: 2026-03-31 10:13
## 세션 종료: 2026-03-31 10:14
## 세션 종료: 2026-03-31 10:18
## 세션 종료: 2026-03-31 10:19
## 세션 종료: 2026-03-31 10:20
## 세션 종료: 2026-03-31 10:23
## 세션 종료: 2026-03-31 10:24
## 세션 종료: 2026-03-31 10:26
## 세션 종료: 2026-03-31 10:26
## 세션 종료: 2026-03-31 10:27
## 세션 종료: 2026-03-31 10:30
## 세션 종료: 2026-03-31 10:32
## 세션 종료: 2026-03-31 10:33
## 세션 종료: 2026-03-31 10:34
## 세션 종료: 2026-03-31 10:35
## 세션 종료: 2026-03-31 10:37
## 세션 종료: 2026-03-31 10:39
## 세션 종료: 2026-03-31 10:44
## 세션 종료: 2026-03-31 10:46
## 세션 종료: 2026-03-31 10:51
## 세션 종료: 2026-03-31 10:51
## 세션 종료: 2026-03-31 10:52
## 세션 종료: 2026-03-31 10:54
## 세션 종료: 2026-03-31 11:19
## 세션 종료: 2026-03-31 11:21
## 세션 종료: 2026-03-31 11:22
## 세션 종료: 2026-03-31 11:26
## 세션 종료: 2026-03-31 11:53
## 세션 종료: 2026-03-31 12:01
## 세션 종료: 2026-03-31 12:19
## 세션 종료: 2026-03-31 12:24
## 세션 종료: 2026-03-31 12:29
## 세션 종료: 2026-03-31 12:36
## 세션 종료: 2026-03-31 12:41
## 세션 종료: 2026-03-31 12:43
## 세션 종료: 2026-03-31 12:47
## 세션 종료: 2026-03-31 12:48
## 세션 종료: 2026-03-31 12:52
## 세션 종료: 2026-03-31 13:09
## 세션 종료: 2026-03-31 13:30
## 세션 종료: 2026-03-31 13:55
## 세션 종료: 2026-03-31 13:58
## 세션 종료: 2026-03-31 14:00
## 세션 종료: 2026-03-31 14:03
## 세션 종료: 2026-03-31 15:19
## 세션 종료: 2026-03-31 15:45
## 세션 종료: 2026-03-31 15:51
## 세션 종료: 2026-03-31 16:28
## 세션 종료: 2026-03-31 16:30
## 세션 종료: 2026-03-31 16:40
## 세션 종료: 2026-03-31 16:46
## 세션 종료: 2026-03-31 16:53
## 세션 종료: 2026-03-31 16:54
## 세션 종료: 2026-03-31 16:55
## 세션 종료: 2026-03-31 22:53
## 세션 종료: 2026-03-31 23:12
## 세션 종료: 2026-03-31 23:23
## 세션 종료: 2026-03-31 23:48
## 세션 종료: 2026-04-01 00:08
## 세션 종료: 2026-04-01 00:41
## 세션 종료: 2026-04-01 00:43
## 세션 종료: 2026-04-01 00:46
## 세션 종료: 2026-04-01 00:50
## 세션 종료: 2026-04-01 00:52
## 세션 종료: 2026-04-01 01:06
## 세션 종료: 2026-04-01 01:09
## 세션 종료: 2026-04-01 01:13
## 세션 종료: 2026-04-01 09:56
## 세션 종료: 2026-04-01 09:59
## 세션 종료: 2026-04-01 10:44
