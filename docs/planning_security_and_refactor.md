# MCPER 보안 강화 & 리팩터링 기획서

**기획자**: @planner
**작성일**: 2026-03-30
**범위**: CRITICAL 3개 + HIGH 3개 (6개 항목)
**목표**: 운영 준비 단계로 진입, 보안 위험 제거, 코드 유지보수성 향상

> **상태 업데이트 (2026-03-31)**: Phase 1 (CRITICAL 3개) 완료. Phase 2 (HIGH 3개) 구현 대기 중.

---

## 📋 Executive Summary

프로젝트 평가 결과 CRITICAL 3개(보안) + HIGH 3개(구조/모니터링) 항목 식별.

| 우선순위 | 항목 | 영향도 | 복잡도 | Phase | 상태 |
|---------|------|--------|--------|-------|------|
| CRITICAL | Admin 패스워드 강제 | 🔴 높음 | ⭐ 낮음 | 1 | ✅ 완료 |
| CRITICAL | API 토큰 만료 검증 | 🔴 높음 | ⭐⭐ 중간 | 1 | ✅ 완료 |
| CRITICAL | CORS/CSRF 방어 | 🔴 높음 | ⭐⭐ 중간 | 1 | ✅ 완료 |
| HIGH | admin.py 모듈 분리 | 🟡 중간 | ⭐⭐⭐ 높음 | 2 | 대기 |
| HIGH | CodeNode 파서 (AST) | 🟡 중간 | ⭐⭐⭐⭐ 매우높음 | 2 | 대기 |
| HIGH | Celery 모니터링 | 🟡 중간 | ⭐⭐ 중간 | 2-3 | 대기 |

---

## 🔴 CRITICAL 항목 (Phase 1: 주 1)

### 1. Admin 기본 패스워드 강제 변경

**현황**: `ADMIN_PASSWORD=changeme` (기본값)으로 설정되어 있으나, 초기화 강제 메커니즘 없음.

**위험**: 프로덕션 배포 시에도 기본 패스워드 사용 가능 → 임의 접근 가능.

#### 1.1 요구사항

**유저 스토리**:
- As a DevOps / System Admin, I want to be forced to change the default admin password during first-time deployment, so that my MCPER instance is not vulnerable on day 1.

**범위**:
1. 런타임 시작 시(`lifespan`) admin 패스워드 검증
2. 기본값(`changeme`) 사용 중이면 로그 경고 + 어드민 UI 접근 차단
3. `/admin` 접근 시 강제 리다이렉트: `/admin/setup/change-password`
4. 새 패스워드 설정 후 `ADMIN_PASSWORD` 환경 변수 재설정 또는 DB 저장

**제약**:
- `MCPER_AUTH_ENABLED=true` (OAuth) 사용 시 이 항목 스킵 가능
- 강제 변경은 `MCPER_AUTH_ENABLED=false` (HTTP Basic) 시에만 필수

**정의된 완료 조건 (DoD)**:
- [ ] lifespan 시작 시 `ADMIN_PASSWORD == "changeme"` 감지
- [ ] 경고 로그 출력: `"CRITICAL: Admin using default password. Set ADMIN_PASSWORD environment variable."`
- [ ] 임시 "설정" 엔드포인트 추가: `GET /admin/setup/change-password` (로그인 불필요)
- [ ] 새 패스워드 설정 후 메모리 또는 DB에 반영
- [ ] 변경 후 `/admin` 재접근 가능 확인
- [ ] E2E 테스트: 기본 패스워드 → 변경 → 새 패스워드 로그인

#### 1.2 QA 시나리오

| 케이스 | 입력 | 기대 결과 |
|--------|------|---------|
| **정상** | 기본 패스워드 감지 | `/admin/setup/change-password` 페이지 강제 리다이렉트 |
| **정상** | 새 패스워드 설정 | 201 Created, 로그 기록, `/admin` 접근 가능 |
| **엣지** | MCPER_AUTH_ENABLED=true | 기본 패스워드 체크 스킵 |
| **엣지** | 환경 변수가 없으면 | 기본값 "changeme" 사용, 경고 표시 |
| **실패** | 패스워드 설정 중 DB 다운 | 트랜잭션 롤백, 메모리 상태 초기화 |

#### 1.3 구현 아키텍처

```
app/main.py lifespan
  ├─ configure_logging()
  ├─ _validate_startup_config()  ← 현존 함수 확장
  │  └─ new: _check_admin_password()  (기본값 감지 + 플래그 설정)
  ├─ init_db()
  └─ app.state.admin_password_change_required = True|False  (플래그)

app/routers/admin.py
  ├─ new: @router.get("/admin/setup/change-password")
  │  └─ 로그인 불필요, 기본 패스워드 체크 페이지 렌더링
  ├─ new: @router.post("/admin/setup/change-password")
  │  └─ 새 패스워드 해싱 → 메모리 업데이트 → /admin 리다이렉트
  └─ 기존 @router.get("/admin") 수정
     └─ if app.state.admin_password_change_required: redirect("/admin/setup/change-password")

app/templates/admin/setup/
  └─ new: change_password.html (스타일링, 최소한, base.html 상속 X)
```

**데이터 저장소**:
- 옵션 A (간단): 메모리 + 환경 변수 재설정 API
- 옵션 B (영구): 신규 `AdminConfig` 테이블 (key="admin_password_changed", value="2026-03-30T...")
  - 추천: 옵션 A (단순, 운영 친화)

#### 1.4 의존성 및 위험

- **블로커**: auth/service.py `hash_password()` 함수 확인 (이미 bcrypt 사용)
- **리스크**: 메모리 패스워드 변경 후 프로세스 재시작 시 초기값으로 복구
  - 완화: 환경 변수에 반영하도록 문서화
- **호환성**: 기존 배포(이미 설정됨)는 이 체크 우회 가능

#### 1.5 예상 작업량

| 작업 | 예상 시간 |
|------|---------|
| 코드 작성 | 2-3시간 |
| 테스트 | 1시간 |
| 문서화 | 30분 |
| **합계** | 3.5-4시간 |

---

### 2. API 토큰 만료 검증

**현황**: `ApiKey` 모델에 `expires_at` 필드가 있으나, 검증 로직이 `dependencies.py` 에서 불완전.

**위험**: 만료된 토큰도 유효한 것으로 간주 → 장기간 보안 위험.

#### 2.1 요구사항

**유저 스토리**:
- As a Security Architect, I want expired API tokens to be rejected immediately, so that compromised old tokens cannot be reused.

**범위**:
1. `dependencies.py` 의 `get_current_user_optional()` 수정
   - Bearer <API_KEY> 검증 시 expires_at 확인
2. `/auth/api-keys` 엔드포인트에서 만료된 키 필터링 (사용자 뷰)
3. Admin 대시보드에서 만료 임박 키 경고 표시
4. 정기적 정리 태스크 (선택): 만료 90일 이상 된 키 자동 삭제

**제약**:
- MCPER_AUTH_ENABLED=true 인 경우에만 적용
- Bearer 토큰(JWT)와 Bearer API 키(SHA256) 둘 다 만료 체크 필요

**정의된 완료 조건 (DoD)**:
- [ ] API 키 검증 시 `datetime.utcnow() > expires_at` 체크
- [ ] 만료된 키는 401 응답 (메시지: "API key expired")
- [ ] JWT 토큰도 만료 검증 확인 (기존: `decode_token()` 이미 `exp` 검증)
- [ ] `/auth/api-keys` GET 응답: 만료된 키 제외
- [ ] `/admin/api-keys` 대시보드: 만료 상태 색상 구분 (Red=만료됨, Yellow=7일내, Green=활성)
- [ ] 유닛 테스트: 만료된 키 거부 확인
- [ ] E2E 테스트: API 키 생성 → 시간 경과 시뮬레이션 → 거부 확인

#### 2.2 QA 시나리오

| 케이스 | 입력 | 기대 결과 |
|--------|------|---------|
| **정상** | 유효한 API 키, `expires_at` 미래 | 200 OK, 요청 처리 |
| **정상** | 유효한 API 키, `expires_at=None` (무기한) | 200 OK |
| **엣지** | API 키, `expires_at` 오늘 자정 | 401 (만료됨) |
| **엣지** | API 키, `expires_at` 7일 내 | 200 OK, UI 경고 표시 |
| **실패** | 만료된 키로 API 호출 | 401 Unauthorized: "API key expired" |
| **실패** | 존재하지 않는 키 | 401 Unauthorized: "Invalid API key" |

#### 2.3 구현 아키텍처

```
app/auth/service.py
  └─ new: def is_api_key_expired(expires_at: datetime | None) -> bool

app/auth/dependencies.py
  └─ async def get_current_user_optional(...)
     └─ if Bearer_API_KEY:
        ├─ key_hash = hash_api_key(token)
        ├─ api_key_row = db.query(ApiKey).filter(key_hash=key_hash).first()
        ├─ if not api_key_row or is_api_key_expired(api_key_row.expires_at):
        │  └─ raise HTTPException(401, "API key expired or invalid")
        └─ else: return api_key_row.user

app/routers/admin.py
  └─ GET /admin/api-keys
     ├─ 결과 필터링: expires_at > datetime.utcnow() or None
     └─ 템플릿에 status badge 표시 (색상: green/yellow/red)

app/templates/admin/
  └─ 신규 또는 수정: api_keys_list.html
     └─ 시각적 인디케이터 (만료 상태, 남은 일수)
```

**추가 고려사항**:
- JWT 토큰: 이미 `decode_token()` 에서 `exp` 검증 (jose 라이브러리)
- API 키: 만료 필드 추가했으므로 검증 로직만 추가

#### 2.4 의존성 및 위험

- **블로커**: `app/db/auth_models.py` 의 `ApiKey` 스키마 확인 (expires_at 필드 존재 여부)
- **리스크**: 기존 API 키들의 expires_at이 NULL 일 수 있음 (무기한 처리 필요)
- **호환성**: 만료 검증 추가 후 기존 클라이언트 영향 없음 (401 처리 가능)

#### 2.5 예상 작업량

| 작업 | 예상 시간 |
|------|---------|
| 코드 작성 | 1.5-2시간 |
| 테스트 | 1.5시간 |
| UI 업데이트 | 1시간 |
| **합계** | 4-4.5시간 |

---

### 3. CORS/CSRF 방어 강화

**현황**:
- CORS: `config.py` 의 `allowed_origins` 설정 있으나, 정확도 불명확
- CSRF: SameSite cookie 정책 + CSRF 토큰 미흡

**위험**: 크로스 사이트 공격(CORS bypass), CSRF 토큰 검증 부족.

#### 3.1 요구사항

**유저 스토리**:
- As a Security Officer, I want CORS and CSRF attacks to be prevented by design, so that admin UI is protected from malicious scripts.

**범위**:
1. CORS 설정 강화
   - `allowed_origins` 명확한 도메인 나열 (와일드카드 금지)
   - 프리플라이트 요청(OPTIONS) 올바른 헤더 응답
2. CSRF 토큰 추가
   - `/admin` 모든 POST/PUT/DELETE 요청에 CSRF 토큰 필요
   - 토큰 생성: 세션별 고유 값 (Redis 또는 메모리)
   - 검증: 요청의 `X-CSRF-Token` 헤더 확인
3. SameSite Cookie 강제
   - 모든 쿠키: `SameSite=Strict` (또는 `Lax`)
   - `Secure` 플래그 (HTTPS)

**제약**:
- API 엔드포인트와 UI 엔드포인트 구분
  - `/mcp` API: 기존 Host 화이트리스트 유지
  - `/admin` UI: CSRF 토큰 추가

**정의된 완료 조건 (DoD)**:
- [ ] CORS 헤더 명확: `Access-Control-Allow-Origin: <specific-domain>`
- [ ] 와일드카드(`*`) 제거 (정적 도메인만)
- [ ] CSRF 토큰 미들웨어 추가
- [ ] POST/PUT/DELETE 요청 시 토큰 검증
- [ ] 템플릿에서 토큰 자동 주입 (hidden field)
- [ ] 쿠키: `SameSite=Strict`, `Secure=true` (HTTPS)
- [ ] 단위 테스트: CORS preflight 처리
- [ ] E2E 테스트: CSRF 토큰 없는 요청 → 403
- [ ] OWASP CWE-352 (CSRF) 체크리스트 통과

#### 3.2 QA 시나리오

| 케이스 | 입력 | 기대 결과 |
|--------|------|---------|
| **정상** | 허용된 origin의 POST + CSRF 토큰 | 200 OK |
| **정상** | OPTIONS preflight (CORS) | 200 OK, `Access-Control-Allow-*` 헤더 |
| **엣지** | GET 요청 (CSRF 토큰 불필요) | 200 OK |
| **실패** | 허용 안 된 origin | CORS 거부 (브라우저 차단) |
| **실패** | POST + CSRF 토큰 없음 | 403 Forbidden |
| **실패** | POST + 잘못된 CSRF 토큰 | 403 Forbidden |
| **실패** | 크로스 도메인 쿠키 접근 | 불가 (SameSite=Strict) |

#### 3.3 구현 아키텍처

```
app/main.py
  └─ app.add_middleware(CORSMiddleware, allow_origins=[...], ...)
     ├─ allow_origins = settings.security.allowed_origins (명시적 리스트)
     ├─ allow_methods = ["GET", "POST", "PUT", "DELETE"]
     ├─ allow_headers = ["Content-Type", "X-CSRF-Token", "Authorization"]
     ├─ expose_headers = ["X-CSRF-Token"]
     └─ allow_credentials = True

app/middleware/csrf.py (새 파일)
  ├─ class CSRFMiddleware
  ├─ def generate_csrf_token(session_id: str) -> str
  │  └─ Redis 저장: `csrf_token:{session_id}` = token
  └─ def validate_csrf_token(session_id: str, token: str) -> bool

app/routers/admin.py
  ├─ GET /admin/csrf-token
  │  └─ 현재 세션의 CSRF 토큰 반환 (or headers)
  └─ 모든 수정 엔드포인트 (POST/PUT/DEL)
     └─ Depends(validate_csrf_token)

app/templates/admin/base.html
  └─ {% csrf_token %}  ← Jinja2 매크로로 hidden field 자동 주입

app/config.py
  └─ class SecuritySettings
     ├─ allowed_origins: list[str] = ["https://admin.example.com", ...]
     ├─ cors_allow_credentials: bool = True
     └─ csrf_token_expiry: int = 3600  # seconds
```

**쿠키 설정**:
```python
# app/main.py or dependencies.py
response.set_cookie(
    key="mcper_token",
    value=token,
    httponly=True,
    samesite="Strict",  # or "Lax"
    secure=True,        # HTTPS only
    max_age=3600
)
```

#### 3.4 의존성 및 위험

- **블로커**: config.py 의 `allowed_origins` 구조 확인
- **블로커**: Redis/메모리 세션 저장소 확인 (CSRF 토큰 용)
- **리스크**: HTTPS 없이 `Secure=true` 설정 시 쿠키 전송 불가
  - 완화: 개발 환경에서는 `Secure=false` 허용, 프로덕션은 강제
- **호환성**: 기존 API 클라이언트가 CSRF 토큰을 모르면 실패
  - 완화: `/mcp` API는 제외, `/admin` UI만 적용

#### 3.5 예상 작업량

| 작업 | 예상 시간 |
|------|---------|
| CORS 설정 수정 | 1시간 |
| CSRF 미들웨어 작성 | 2시간 |
| 템플릿 매크로 추가 | 1시간 |
| 쿠키 설정 통일 | 1시간 |
| 테스트 | 2시간 |
| **합계** | 7시간 |

---

## 🟡 HIGH 항목 (Phase 2: 주 2-3)

### 4. admin.py 모듈 분리 (1293줄 → 4개 라우터)

**현황**: `app/routers/admin.py` 가 1293줄로 모든 기능(규칙, 스펙, 도구, 통계)을 포함.

**위험**: 코드 유지보수성 저하, 파일 검색 어려움, 테스트 독립성 약함.

#### 4.1 요구사항

**유저 스토리**:
- As a Developer, I want admin.py to be split into logical modules, so that I can understand and modify rules/specs/tools independently.

**범위**:
1. 4개 모듈로 분할
   - `routers/admin_rules.py` (규칙 관리: 글로벌/앱/레포)
   - `routers/admin_specs.py` (스펙 업로드/검색/삭제)
   - `routers/admin_tools.py` (MCP 도구 카탈로그 + 통계)
   - `routers/admin.py` (대시보드, 헬스체크, 라우터 등록)
2. 공통 유틸 분리
   - `routers/admin_utils.py` (require_admin_user, 템플릿 헬퍼)
3. 라우터 등록 통합
   - `main.py` 에서 4개 라우터 모두 포함

**제약**:
- 기존 URL 경로 유지 (외부 링크 깨지지 않음)
- 템플릿 구조 유지 (사이드바, base.html)

**정의된 완료 조건 (DoD)**:
- [ ] 4개 라우터 파일 생성 + 각 <400줄
- [ ] admin.py 남은 줄 수 <300줄 (대시보드 + 라우터 등록만)
- [ ] 기존 엔드포인트 모두 작동 (URL 경로 동일)
- [ ] 임포트 순환참조 없음
- [ ] 단위 테스트: 각 라우터 엔드포인트 1개 이상
- [ ] 통합 테스트: 대시보드 + 한 가지 기능 end-to-end

#### 4.2 분할 계획

**admin_rules.py (글로벌 규칙, 앱 규칙, 레포 규칙)**:
```python
# GET  /admin/global-rules
# POST /admin/global-rules (버전 발행)
# GET  /admin/app-rules
# POST /admin/app-rules/{app} (버전 발행)
# GET  /admin/app-rules/{app}
# POST /admin/app-rules/{app}/append (추가)
# GET  /admin/repo-rules
# POST /admin/repo-rules (버전 발행)
# 총: 8 엔드포인트, ~300줄
```

**admin_specs.py (기획서 CRUD)**:
```python
# GET  /admin/specs (검색/필터)
# POST /admin/specs (업로드)
# GET  /admin/specs/{app}
# GET  /admin/plan/{id}
# PUT  /admin/plan/{id} (수정)
# DEL  /admin/plan/{id}
# GET  /admin/plans/bulk-upload
# POST /admin/plans/bulk-upload
# 총: 8 엔드포인트, ~350줄
```

**admin_tools.py (MCP 도구 + 통계)**:
```python
# GET  /admin/tools (카탈로그)
# GET  /admin/health
# GET  /admin/health/rag
# 총: 3 엔드포인트, ~150줄
```

**admin.py (대시보드 + 라우터 등록)**:
```python
# GET  /admin (대시보드)
# 라우터 등록 로직
# 총: ~150줄
```

#### 4.3 구현 순서

1. **Step 1**: `routers/admin_utils.py` 작성 (공통 함수)
   - `require_admin_user`, `spec_display_title`, `content_looks_like_blob` 등
2. **Step 2**: `routers/admin_rules.py` 추출 (가장 큼 + 자립적)
3. **Step 3**: `routers/admin_specs.py` 추출
4. **Step 4**: `routers/admin_tools.py` 추출
5. **Step 5**: 기존 `admin.py` 정리 + 라우터 등록

#### 4.4 의존성 및 위험

- **블로커**: admin.py 전체 코드 읽기 필요 (1293줄 → 기록관 추천)
- **리스크**: 엔드포인트 누락 또는 임포트 오류
  - 완화: 각 단계마다 `uvicorn main:app --reload` 테스트
- **호환성**: 모든 기존 엔드포인트 유지

#### 4.5 예상 작업량

| 작업 | 예상 시간 |
|------|---------|
| 코드 분석 | 2시간 (기록관 활용) |
| admin_utils.py 추출 | 1시간 |
| admin_rules.py 추출 | 2시간 |
| admin_specs.py 추출 | 2.5시간 |
| admin_tools.py 추출 | 1시간 |
| 통합 테스트 | 2시간 |
| **합계** | 10.5시간 |

---

### 5. CodeNode 자동 인덱싱 파서 (AST 기반)

**현황**: CodeNode 테이블이 존재하나, AST 크롤러 없어서 수동 입력 또는 외부 API 의존.

**영향**: RAG 검색 시 코드 컨텍스트 불완전 → 추천 품질 저하.

#### 5.1 요구사항

**유저 스토리**:
- As an AI Assistant using MCPER, I want to automatically index Python/JavaScript code symbols (functions, classes, methods) from a repository, so that my search results include relevant code context.

**범위**:
1. **Python AST 파서**: `ast` 모듈 사용
   - 클래스, 함수, 메서드, 중첩 블록 추출
   - 라인 범위, docstring, 데코레이터 기록
2. **JavaScript/TypeScript 파서**: `tree-sitter` 또는 정규식 간단 파서
   - 함수, 클래스, 화살표 함수, export 추출
3. **MCP 도구**: `push_code_index` 확장
   - 파일 목록 입력 → 자동 파싱 → CodeNode/CodeEdge 삽입
4. **메타데이터**: 각 노드에 저장
   - `kind`: "function"/"class"/"method"/"fragment"
   - `lineno_start`, `lineno_end`
   - `signature`: 함수 시그니처 또는 클래스 정의
   - `docstring`: 주석

**제약**:
- Python 3.8+ 코드만 지원 (JavaScript는 Phase 2)
- 에러 처리: 파싱 실패 시 로그만 기록, 인덱싱 계속
- 대용량 파일(>10MB): 스킵 또는 청킹

**정의된 완료 조건 (DoD)**:
- [ ] `app/services/code_parsers/` 디렉토리 생성
- [ ] `app/services/code_parsers/python_parser.py` (AST 기반 파싱)
- [ ] `app/services/code_parsers/interfaces.py` (파서 프로토콜)
- [ ] `app/tools/rag_tools.py` 의 `push_code_index_impl()` 호출 체인 확장
- [ ] CodeNode 삽입: batch upsert (stable_id 기준)
- [ ] CodeEdge 삽입: import/call 관계 추적
- [ ] 유닛 테스트: 샘플 Python 파일 파싱
- [ ] E2E: 샘플 레포 → CodeNode 100개 이상 생성 확인

#### 5.2 구현 계획

**Phase 1: Python 파서 (MVP)**

```python
# app/services/code_parsers/interfaces.py
from typing import Protocol

class CodeParser(Protocol):
    def parse(self, file_path: str, content: str) -> list[CodeNode]:
        """Extract symbols from code content"""
        ...

# app/services/code_parsers/python_parser.py
import ast

class PythonCodeParser:
    def parse(self, file_path: str, content: str) -> list[CodeNode]:
        """
        Extract functions, classes, methods from Python code.
        Returns list[(kind, name, lineno_start, lineno_end, signature, docstring)]
        """
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            logger.warning(f"Failed to parse {file_path}: {e}")
            return []

        nodes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                nodes.append(_extract_function(node, file_path))
            elif isinstance(node, ast.ClassDef):
                nodes.append(_extract_class(node, file_path))

        return nodes

def _extract_function(node: ast.FunctionDef, file_path: str) -> dict:
    return {
        "kind": "function",
        "symbol_name": node.name,
        "lineno_start": node.lineno,
        "lineno_end": node.end_lineno,
        "signature": ast.get_source_segment(...) or f"def {node.name}(...)",
        "docstring": ast.get_docstring(node),
    }

def _extract_class(node: ast.ClassDef, file_path: str) -> dict:
    return {
        "kind": "class",
        "symbol_name": node.name,
        "lineno_start": node.lineno,
        "lineno_end": node.end_lineno,
        "signature": f"class {node.name}",
        "docstring": ast.get_docstring(node),
    }
```

**Phase 2: 의존성 추출 (EdgeOf)**

```python
# ast.walk() 중 Import/ImportFrom 노드 감지
→ CodeEdge: source_id="current file's node" → target_id="imported module"
```

**Phase 3: 비동기 큐 통합**

```python
# app/worker/tasks.py
@celery_app.task(name="index_code_async")
def index_code_async(app_target: str, file_list: list[str]):
    """
    1. 각 파일 읽기
    2. 파일별 파서 선택 (python_parser.py vs js_parser.py)
    3. 파싱 → CodeNode 생성
    4. 배치 upsert
    """
    ...
```

#### 5.3 의존성 및 위험

- **블로커**: `app/services/` 구조 확인, 임베딩 API 호출 방식 확인
- **리스크**: 대용량 파일 파싱 시 메모리/CPU 스파이크
  - 완화: 파일 크기 제한 (>10MB skip), 타임아웃 설정
- **리스크**: 동적 import/eval 있는 코드는 파싱 불가
  - 완화: 정적 분석만 지원, 문서화
- **리스크**: JavaScript 파서 복잡도 높음
  - 완화: Python만 먼저, JS는 Phase 2

#### 5.4 예상 작업량

| 작업 | 예상 시간 |
|------|---------|
| Python 파서 작성 | 3시간 |
| 테스트 케이스 | 2시간 |
| 메타데이터 추출 (signature/docstring) | 1시간 |
| Celery 통합 | 1시간 |
| 실제 레포 테스트 | 1시간 |
| 문서화 | 1시간 |
| **합계** | 9시간 |

---

### 6. Celery 모니터링 강화

**현황**: Celery 백그라운드 작업은 있으나, 실패 추적 대시보드가 없음.

**영향**: 기획서 인덱싱 실패를 발견하지 못함 → 검색 결과 불완전.

#### 6.1 요구사항

**유저 스토리**:
- As an Admin, I want to see which specs have failed to index and why, so that I can retry them or investigate issues.

**범위**:
1. **실패 추적 DB**
   - 신규 테이블: `TaskFailure` (task_id, spec_id, error_message, created_at)
2. **UI 대시보드**
   - `/admin/celery/tasks` (진행 중인 작업, 실패 목록)
   - `/admin/celery/failed-specs` (실패한 스펙별 상세)
3. **자동 복구**
   - 실패한 스펙 자동 재시도 API: `POST /admin/celery/retry/{task_id}`
4. **모니터링 엔드포인트**
   - `/health/rag` 확장: 큐 깊이, 활성 작업 수, 최근 실패율

**제약**:
- Celery Flower 대시보드는 선택사항 (자체 UI 우선)
- Redis 장애 시 fallback: 메모리 로깅

**정의된 완료 조건 (DoD)**:
- [ ] `TaskFailure` 테이블 생성
- [ ] index_spec_task 실패 시 로그 저장
- [ ] `/admin/celery/failed-specs` UI
- [ ] `/health/rag` 확장: task queue 메트릭
- [ ] 자동 재시도 버튼
- [ ] 대시보드: 최근 24시간 실패율 표시
- [ ] 유닛 테스트: 실패 추적 로직
- [ ] E2E: 인덱싱 실패 → 대시보드 표시 확인

#### 6.2 구현 계획

**Step 1: DB 모델 추가**

```python
# app/db/celery_models.py (신규 파일)
from sqlalchemy import Column, Integer, String, DateTime, Text
from app.db.database import Base

class TaskFailure(Base):
    __tablename__ = "celery_task_failures"

    task_id: str = Column(String[256], unique=True, index=True)
    spec_id: int = Column(Integer, ForeignKey("specs.id"), nullable=True)
    task_name: str = Column(String[128])  # "index_spec", "index_code_batch"
    error_type: str = Column(String[256])  # Exception class name
    error_message: str = Column(Text)
    retry_count: int = Column(Integer, default=0)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    failed_at: datetime = Column(DateTime, default=datetime.utcnow)
```

**Step 2: Celery 작업 에러 핸들러**

```python
# app/worker/tasks.py
from celery import states

@celery_app.task(name="index_spec", bind=True)
def index_spec_task(self, spec_id: int):
    try:
        # 기존 로직
        ...
    except Exception as e:
        db = SessionLocal()
        try:
            # 실패 기록
            failure = TaskFailure(
                task_id=self.request.id,
                spec_id=spec_id,
                task_name="index_spec",
                error_type=type(e).__name__,
                error_message=str(e),
            )
            db.add(failure)
            db.commit()
        finally:
            db.close()

        # 재시도
        if self.request.retries < 3:
            self.retry(exc=e, countdown=10)
        else:
            self.update_state(state=states.FAILURE, meta=str(e))
```

**Step 3: Admin UI**

```python
# app/routers/admin_celery.py (신규 파일)
@router.get("/admin/celery/failed-specs")
async def view_failed_specs(_user: str = Depends(require_admin_user), db: Session = Depends(get_db)):
    """List specs that failed to index"""
    failures = db.query(TaskFailure)\
        .filter(TaskFailure.spec_id.isnot(None))\
        .order_by(TaskFailure.failed_at.desc())\
        .limit(50)\
        .all()

    specs = db.query(Spec).filter(Spec.id.in_([f.spec_id for f in failures])).all()
    spec_map = {s.id: s for s in specs}

    return templates.TemplateResponse("admin/celery_failed_specs.html", {
        "request": request,
        "failures": failures,
        "specs": spec_map,
    })

@router.post("/admin/celery/retry/{task_id}")
async def retry_task(task_id: str, _user: str = Depends(require_admin_user), db: Session = Depends(get_db)):
    """Retry failed task"""
    failure = db.query(TaskFailure).filter(TaskFailure.task_id == task_id).first()
    if not failure:
        raise HTTPException(404, "Task not found")

    if failure.spec_id:
        celery_app.send_task("index_spec", args=[failure.spec_id])
        failure.retry_count += 1
        db.commit()

    return {"ok": True, "retried": True, "retry_count": failure.retry_count}
```

**Step 4: 헬스 체크 확장**

```python
# app/main.py
@app.get("/health/rag")
async def health_rag(db: Session = Depends(get_db)):
    """Extended health check for RAG indexing"""
    from celery.result import AsyncResult

    # 기존 체크
    specs_total = db.query(Spec).count()
    specs_indexed = db.query(SpecChunk).distinct(SpecChunk.spec_id).count()

    # Celery 상태
    inspect = celery_app.control.inspect()
    active_tasks = len(inspect.active() or {})
    pending_tasks = len(celery_app.control.inspect().reserved() or {})

    # 실패율
    failures_24h = db.query(TaskFailure)\
        .filter(TaskFailure.failed_at >= datetime.utcnow() - timedelta(hours=24))\
        .count()

    return {
        "ok": True,
        "specs": {
            "total": specs_total,
            "indexed": specs_indexed,
            "coverage": specs_indexed / specs_total if specs_total > 0 else 0,
        },
        "celery": {
            "broker_ok": True,  # Redis 연결 확인
            "active_tasks": active_tasks,
            "pending_tasks": pending_tasks,
            "queue_depth": active_tasks + pending_tasks,
        },
        "failures_24h": failures_24h,
    }
```

#### 6.3 의존성 및 위험

- **블로커**: Celery inspect() API 작동 확인
- **블로커**: Redis 연결 상태 확인 API
- **리스크**: 대량의 TaskFailure 레코드 → 디스크 증가
  - 완화: 자동 정리 태스크 (30일 이상 레코드 삭제)
- **리스크**: 재시도 API 남용 가능
  - 완화: 최대 재시도 횟수 제한

#### 6.4 예상 작업량

| 작업 | 예상 시간 |
|------|---------|
| DB 모델 추가 | 0.5시간 |
| Celery 에러 핸들러 | 1시간 |
| Admin UI + 엔드포인트 | 2시간 |
| /health/rag 확장 | 1시간 |
| 테스트 | 1.5시간 |
| **합계** | 6시간 |

---

## 📅 Phase별 일정 및 마일스톤

### Phase 1: CRITICAL 보안 (주 1)

**목표**: 운영 배포 전 보안 위험 제거

| 항목 | 담당 | 시작 | 예상 |
|------|------|------|------|
| 1. Admin 패스워드 강제 | @coder | 월 | 4시간 |
| 2. API 토큰 만료 | @coder | 월-화 | 4.5시간 |
| 3. CORS/CSRF | @coder + @tester | 화-수 | 7시간 |
| **Phase 1 합계** | | | **15.5시간** (약 2일 반) |

**마일스톤**:
- 월: 항목 1 완료
- 화: 항목 2 완료
- 수-목: 항목 3 완료 + 통합 테스트
- 목: Phase 1 검수

### Phase 2a: 높은 우선순위 구조 개선 (주 2)

**목표**: 코드 유지보수성 향상 + RAG 완성도

| 항목 | 담당 | 시작 | 예상 |
|------|------|------|------|
| 4. admin.py 분리 | @coder + @tester | 목 | 10.5시간 |
| 5. CodeNode 파서 | @coder | 금-월 | 9시간 |
| **Phase 2a 합계** | | | **19.5시간** (약 3일) |

**마일스톤**:
- 목-금: admin.py 분리 완료
- 금-월: CodeNode 파서 완료 (파이썬만)

### Phase 2b: 모니터링 (주 2-3)

**목표**: 운영 가시성 확보

| 항목 | 담당 | 시작 | 예상 |
|------|------|------|------|
| 6. Celery 모니터링 | @coder + @tester | 월 | 6시간 |
| **Phase 2b 합계** | | | **6시간** (약 1일) |

**마일스톤**:
- 월-화: Celery 모니터링 대시보드 완료

---

## 🔀 병렬 작업 가능성

### Group A: 보안 (Phase 1)

| 항목 | 의존성 | 병렬 가능 |
|------|--------|----------|
| 1. Admin 패스워드 | 없음 | ✅ 단독 |
| 2. API 토큰 만료 | 토큰 검증 로직 (기존) | ✅ 병렬 (1과) |
| 3. CORS/CSRF | config.py, Redis | ❓ 부분 병렬 (2와) |

**권장**: 1과 2를 병렬, 3은 2 완료 후 → 전체 단축 가능

### Group B: 구조 개선 (Phase 2)

| 항목 | 의존성 | 병렬 가능 |
|------|--------|----------|
| 4. admin.py 분리 | 없음 | ✅ 단독 |
| 5. CodeNode 파서 | 임베딩 API (기존) | ✅ 병렬 (4와) |
| 6. Celery 모니터링 | Celery 작업 (기존) | ✅ 병렬 (4, 5와) |

**권장**: 4, 5, 6 모두 병렬 진행 → Phase 2 단축 가능

### 최적화 일정

```
Phase 1 (보안):  Mon-Wed (3일)
  ├─ Mon: 항목 1 + 항목 2 병렬
  ├─ Tue: 항목 2 마무리 + 항목 3 시작
  └─ Wed: 항목 3 완료 + 통합 테스트

Phase 2 (구조): Thu-Tue (3일)
  ├─ Thu: 항목 4 (admin.py) + 항목 5 (CodeNode) 병렬 시작
  ├─ Fri: 4, 5 진행 + 항목 6 (Celery) 병렬 추가
  ├─ Mon: 4, 5, 6 병렬 진행
  └─ Tue: 전체 테스트 + 검수

총 기간: 2주 (Phase 1 + 2)
```

---

## 🎯 협업 모델

### 각 항목별 주체

| 항목 | 주도 | 협업 | 검수 |
|------|------|------|------|
| 1. Admin 패스워드 | @coder | - | @senior |
| 2. API 토큰 만료 | @coder | @tester | @senior |
| 3. CORS/CSRF | @coder + @tester | - | @senior |
| 4. admin.py 분리 | @coder + 기록관 | @tester | @senior |
| 5. CodeNode 파서 | @coder | @tester | @senior |
| 6. Celery 모니터링 | @coder | @tester | @infra |

### 에이전트 역할

- **@coder**: 핵심 구현 (각 항목)
- **@tester**: 테스트 케이스, 엣지 케이스 검증 (항목 2-6)
- **@senior**: 아키텍처 설계 검토, 코드 리뷰
- **@archivist**: admin.py 분석 (항목 4) → 메모 작성
- **@infra**: Celery/Redis 설정 검수 (항목 6)

### 협력 체크포인트

1. **@coder 구현 → @tester 테스트**: 매일 저녁
2. **@senior 코드 리뷰**: 각 항목 완료 후
3. **@infra 배포 검수**: Phase 1 완료 후

---

## 📊 성공 지표

### Phase 1 (보안)

- ✅ Admin 기본 패스워드 초기 변경 강제
- ✅ API 토큰 만료 검증 작동
- ✅ CORS/CSRF 공격 방지 확인 (보안 감사)
- ✅ 모든 엔드포인트 HTTPS 가능 (SameSite cookie)

### Phase 2 (구조/모니터링)

- ✅ admin.py <300줄 (분리 완료)
- ✅ 4개 라우터 모듈 작동 (URL 경로 동일)
- ✅ CodeNode 자동 생성 (샘플 레포 >100개 노드)
- ✅ Celery 실패 추적 대시보드 활성화
- ✅ /health/rag 메트릭 표시

---

## ⚠️ 위험 및 완화 전략

### 위험 1: Phase 1 기간 내 보안 검증 부족

**위험도**: 🔴 높음
**완화**:
- 각 항목별 OWASP 체크리스트 준용
- 보안 감사자 별도 검수 (선택)
- Phase 1 → 프로덕션 배포 전 보안 테스트 필수

### 위험 2: admin.py 분리 중 엔드포인트 누락

**위험도**: 🟡 중간
**완화**:
- 기록관으로 전체 엔드포인트 리스트 추출
- 분리 후 모든 URL 경로 테스트 자동화
- 침투 테스트 (모든 엔드포인트 접근 확인)

### 위험 3: CodeNode 파싱 성능 이슈 (대용량)

**위험도**: 🟡 중간
**완화**:
- 파일 크기 제한 (>10MB skip)
- 파싱 타임아웃 설정 (30초)
- 실제 레포 테스트 (최소 1000개 파일)

### 위험 4: Celery Redis 장애 시 모니터링 불가

**위험도**: 🟡 중간
**완화**:
- Redis 재시작 자동화
- TaskFailure 테이블도 추적 (DB 기반 폴백)
- /health/rag 에서 Redis 상태 체크

---

## 🧪 테스트 전략

### Unit Tests (각 항목별)

1. **Admin 패스워드**: 기본값 감지, 변경, 로그인 확인
2. **API 토큰**: 만료된 키 거부, 유효한 키 수락
3. **CORS/CSRF**: preflight 응답, CSRF 토큰 검증
4. **admin.py 분리**: 라우터 등록 확인, 엔드포인트 매핑
5. **CodeNode 파서**: Python 파일 파싱, 메타데이터 추출
6. **Celery 모니터링**: 실패 로깅, 재시도 로직

### Integration Tests

- Phase 1: UI 로그인 → 관리 기능 전체 작동
- Phase 2: 스펙 업로드 → CodeNode 자동 생성 → 검색 작동

### E2E Tests (Selenium/Playwright)

- Admin UI 초기 설정 (패스워드 변경)
- 규칙/스펙 편집 (CSRF 토큰 포함)
- Celery 실패 대시보드 확인

---

## 📝 산출물

### 기획 문서 (이 파일)

✅ 완료

### 추가 필요 문서

1. **기술 설계서** (@senior):
   - CSRF 토큰 저장소 선택 (Redis vs 메모리)
   - CodeNode 파싱 알고리즘 상세
   - admin.py 모듈 분할 다이어그램

2. **테스트 계획** (@tester):
   - 각 항목별 테스트 케이스
   - 보안 감사 체크리스트
   - 성능 테스트 시나리오

3. **배포 가이드** (@infra):
   - Phase 1 후 프로덕션 배포 절차
   - 마이그레이션 전략 (기존 API 키, 규칙)
   - 롤백 계획

---

## ✅ 기획 완료

**기획자**: @planner
**작성일**: 2026-03-30
**상태**: 준비 완료 → @senior 설계 단계로 이동

**다음 단계**:
1. @senior: 각 항목별 기술 설계서 작성 (3-5일)
2. @coder: 기술 설계 검토 후 구현 시작 (1주)
3. @tester: 테스트 케이스 작성 (병렬)
4. @infra: 배포 계획 수립 (병렬)

