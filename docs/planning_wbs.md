# MCPER 6개 항목 작업 분해도 (WBS)

**작성일**: 2026-03-30
**범위**: CRITICAL 3개 + HIGH 3개 항목의 태스크 레벨 분해

> **상태 업데이트 (2026-03-31)**: 1~3번 항목(CRITICAL, Phase 1) 완료. 4~6번 항목(HIGH, Phase 2) 구현 대기 중.

---

## 1. Admin 패스워드 강제 변경 (4시간)

### 1.1 기본 패스워드 감지 및 플래그 설정 (1시간)

```
1.1.1 app/main.py lifespan 수정
      ├─ _check_admin_password() 함수 추가
      ├─ 환경 변수 "changeme" 감지
      ├─ app.state.admin_password_change_required = True
      └─ 경고 로그 출력: "CRITICAL: Using default admin password"

1.1.2 app/auth/service.py 확인
      └─ hash_password() 동작 확인 (bcrypt)
```

**의존성**: 없음
**소요**: 1시간

---

### 1.2 설정 엔드포인트 추가 (1.5시간)

```
1.2.1 app/routers/admin.py 새 엔드포인트 추가
      ├─ GET /admin/setup/change-password (로그인 불필요)
      │  └─ 조건: app.state.admin_password_change_required == True
      │     - 입력 폼 렌더링
      │     - 로그인 기록 없이 진행
      ├─ POST /admin/setup/change-password
      │  ├─ 입력: old_password, new_password, confirm
      │  ├─ 검증: old_password == ADMIN_PASSWORD (환경 변수)
      │  ├─ 변경: 메모리에 새 패스워드 저장
      │  ├─ 플래그: app.state.admin_password_change_required = False
      │  └─ 응답: 리다이렉트 /admin + 성공 메시지
      └─ 에러 처리: 패스워드 일치 실패 → 400

1.2.2 app/templates/admin/setup/ 디렉토리 생성
      └─ change_password.html
         ├─ base.html 상속 X (로그인 없이 표시)
         ├─ 스타일: 최소한 (admin.css 제외)
         ├─ 폼: old_password, new_password, confirm
         └─ 제출 버튼 + 경고 메시지
```

**의존성**: 1.1 완료 후
**소요**: 1.5시간

---

### 1.3 기존 Admin 엔드포인트 리다이렉트 (0.5시간)

```
1.3.1 app/routers/admin.py GET /admin 수정
      ├─ 조건 확인: app.state.admin_password_change_required
      ├─ True 이면: 302 Redirect /admin/setup/change-password
      └─ False 이면: 기존 대시보드 렌더링

1.3.2 require_admin_user 의존성 수정 (선택)
      └─ 패스워드 미설정 상태는 로그인 불가 (optional)
```

**의존성**: 1.2 완료 후
**소요**: 0.5시간

---

### 1.4 테스트 (0.5시간)

```
1.4.1 단위 테스트 (test_admin_password.py)
      ├─ 기본 패스워드 감지 확인
      ├─ 변경 후 플래그 갱신 확인
      ├─ 잘못된 old_password 거부 확인
      └─ 변경 후 /admin 접근 가능 확인

1.4.2 수동 테스트
      ├─ 환경 변수 ADMIN_PASSWORD=changeme 설정
      ├─ 앱 시작 → 로그 확인
      ├─ /admin 접근 → /admin/setup/change-password 리다이렉트
      ├─ 새 패스워드 설정
      └─ /admin 재접근 → 대시보드 표시
```

**의존성**: 1.3 완료 후
**소요**: 0.5시간

---

## 2. API 토큰 만료 검증 (4.5시간)

### 2.1 데이터 모델 확인 (0.5시간)

```
2.1.1 app/db/auth_models.py 확인
      ├─ ApiKey 테이블 스키마 확인
      ├─ expires_at 필드 존재 여부 확인
      ├─ 기존 데이터의 expires_at = NULL 여부 확인
      └─ 필요시 컬럼 추가 (ALTER TABLE)

2.1.2 JWT 토큰 만료 검증 로직 확인 (이미 존재)
      └─ app/auth/service.py decode_token() → jose exp 검증
```

**의존성**: 없음
**소요**: 0.5시간

---

### 2.2 API 키 검증 로직 추가 (1.5시간)

```
2.2.1 app/auth/service.py 새 함수 추가
      ├─ is_api_key_expired(expires_at: datetime | None) -> bool
      │  ├─ expires_at == None: return False (무기한)
      │  ├─ expires_at > datetime.utcnow(): return False
      │  └─ else: return True
      └─ validate_api_key_with_expiry(token: str) -> (bool, User | None)
         ├─ hash_api_key(token) 호출
         ├─ DB 조회: ApiKey.key_hash == hashed
         ├─ is_api_key_expired() 체크
         ├─ 만료 시: 401, "API key expired"
         └─ 유효 시: User 객체 반환

2.2.2 app/auth/dependencies.py get_current_user_optional() 수정
      ├─ Bearer <API_KEY> 처리 부분 수정
      ├─ 기존: hash_api_key() → DB 조회
      ├─ 신규: hash_api_key() → DB 조회 → is_api_key_expired() 체크
      └─ 실패 시: HTTPException(401, "API key expired or invalid")

2.2.3 JWT 토큰 만료 로직 확인 (기존)
      └─ decode_token() 이미 exp 검증 (jose 라이브러리)
```

**의존성**: 2.1 완료 후
**소요**: 1.5시간

---

### 2.3 Admin UI 업데이트 (1.5시간)

```
2.3.1 app/routers/admin.py GET /admin/api-keys 수정
      ├─ 결과 필터링: expires_at 비교
      │  ├─ expires_at == None: 무기한 (색상: green)
      │  ├─ expires_at > now + 7일: 활성 (색상: green)
      │  ├─ expires_at > now and <= now + 7일: 임박 (색상: yellow)
      │  └─ expires_at <= now: 만료됨 (색상: red)
      ├─ 템플릿에 상태 전달
      └─ 정렬: 남은 일수 기준 (임박한 것부터)

2.3.2 app/templates/admin/ 새/수정 파일
      ├─ api_keys_list.html 또는 기존 수정
      │  ├─ 테이블 컬럼: 키명, 생성일, 만료일, 남은 일수, 상태
      │  ├─ 상태 배지: 색상 구분 (green/yellow/red)
      │  └─ 재생성/삭제 버튼
      └─ 스타일: admin.css 기존 클래스 재사용

2.3.3 app/routers/admin.py POST /admin/api-keys 수정 (선택)
      └─ API 키 생성 시 expires_at 입력 (7/30/90일 옵션)
```

**의존성**: 2.2 완료 후
**소요**: 1.5시간

---

### 2.4 테스트 (1시간)

```
2.4.1 단위 테스트 (test_api_key_expiry.py)
      ├─ 유효한 키 (expires_at 미래): 통과
      ├─ 무기한 키 (expires_at=None): 통과
      ├─ 만료된 키: 401 "API key expired"
      ├─ 존재하지 않는 키: 401 "Invalid API key"
      └─ 만료 임박 (7일내): UI 경고

2.4.2 E2E 테스트 (Selenium/Playwright)
      ├─ 관리자 로그인
      ├─ API 키 생성 (7일 만료)
      ├─ 시간 경과 시뮬레이션 (시스템 시간 변경)
      ├─ 만료된 키로 API 호출 → 401
      └─ Admin UI: 만료 상태 확인

2.4.3 수동 테스트
      ├─ 기존 API 키들의 expires_at=NULL 확인
      ├─ 새 키 생성 후 만료일 설정
      └─ /auth/me 엔드포인트로 검증
```

**의존성**: 2.3 완료 후
**소요**: 1시간

---

## 3. CORS/CSRF 방어 강화 (7시간)

### 3.1 CORS 설정 정리 (1.5시간)

```
3.1.1 app/config.py 확인
      ├─ security.allowed_origins 구조 확인
      ├─ 와일드카드(*) 사용 여부 확인
      └─ 명시적 도메인 리스트 준비

3.1.2 app/main.py FastAPI 앱 설정 수정
      ├─ from fastapi.middleware.cors import CORSMiddleware
      ├─ 기존 CORS 설정 제거 (있으면)
      ├─ app.add_middleware(CORSMiddleware, ...)
      │  ├─ allow_origins = settings.security.allowed_origins (NOT "*")
      │  ├─ allow_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
      │  ├─ allow_headers = ["*"] 또는 ["Content-Type", "Authorization", "X-CSRF-Token"]
      │  ├─ expose_headers = ["X-CSRF-Token"]
      │  ├─ allow_credentials = True
      │  └─ max_age = 3600
      └─ OPTIONS 요청 처리 확인

3.1.3 테스트
      ├─ preflight 요청 (OPTIONS): 200 + CORS 헤더
      ├─ 허용된 origin: 200
      └─ 허용 안 된 origin: CORS 에러 (브라우저 차단)
```

**의존성**: 없음
**소요**: 1.5시간

---

### 3.2 CSRF 토큰 미들웨어 구현 (2시간)

```
3.2.1 app/middleware/ 디렉토리 생성
      └─ csrf.py (신규 파일)
         ├─ from datetime import datetime, timedelta
         ├─ import secrets
         ├─ import redis (또는 메모리 dict)
         └─ class CSRFMiddleware(BaseHTTPMiddleware)

3.2.2 CSRF 토큰 저장소 선택
      옵션 A (Redis): 빠름, 확장성 좋음
      ├─ Redis 연결: redis.Redis(host=..., port=...)
      ├─ 키 형식: csrf_token:{session_id}:{token_hash}
      └─ TTL: 1시간
      옵션 B (메모리): 간단, 단일 프로세스
      ├─ 전역 dict: _csrf_tokens = {}
      └─ 정기 정리: TTL 초과 토큰 삭제

3.2.3 CSRF 토큰 생성/검증
      ├─ def generate_csrf_token(session_id: str) -> str
      │  ├─ token = secrets.token_urlsafe(32)
      │  ├─ 저장: redis["csrf_token:{session_id}"] = token
      │  └─ return token
      ├─ def validate_csrf_token(request: Request) -> bool
      │  ├─ X-CSRF-Token 헤더 읽음
      │  ├─ 세션 ID (쿠키 또는 헤더) 추출
      │  ├─ Redis 조회: redis["csrf_token:{session_id}"] == token?
      │  ├─ True: 토큰 삭제 후 통과
      │  └─ False: 403 Forbidden
      └─ app.middleware("http"): POST/PUT/DELETE 요청마다 검증

3.2.4 미들웨어 등록
      └─ app.add_middleware(CSRFMiddleware)
         ├─ GET, OPTIONS: 스킵
         ├─ POST, PUT, DELETE /admin/*: 검증
         └─ /mcp/* 또는 /api/*: 스킵 (API 클라이언트용)
```

**의존성**: 3.1 완료 후
**소요**: 2시간

---

### 3.3 템플릿 CSRF 토큰 주입 (1시간)

```
3.3.1 app/templates/admin/base.html 수정
      ├─ {% csrf_token %} 매크로 정의 또는 호출
      └─ 모든 POST/PUT/DELETE 폼에서 호출

3.3.2 Jinja2 매크로 (app/main.py 또는 별도 파일)
      ├─ @app.context_processor
      ├─ def inject_csrf_token():
      │  ├─ token = generate_csrf_token(session_id)
      │  └─ return {"csrf_token": token}
      └─ 템플릿: <input type="hidden" name="csrf_token" value="{{ csrf_token }}">

3.3.3 hidden field 자동 주입
      ├─ 모든 POST 폼: <form method="post">
      │  ├─ {% csrf_token %}
      │  └─ 나머지 입력 필드
      └─ JavaScript fetch: headers: {"X-CSRF-Token": token}
```

**의존성**: 3.2 완료 후
**소요**: 1시간

---

### 3.4 쿠키 SameSite/Secure 설정 (1.5시간)

```
3.4.1 app/auth/dependencies.py 및 라우터 확인
      ├─ JWT 쿠키 설정 부분 찾기
      │  └─ response.set_cookie("mcper_token", ...)
      ├─ 기존 설정 정리
      └─ 신규 설정 적용

3.4.2 쿠키 설정 표준화
      ├─ def set_auth_cookie(response, token: str, max_age: int = 3600)
      │  ├─ response.set_cookie(
      │  │    key="mcper_token",
      │  │    value=token,
      │  │    max_age=max_age,
      │  │    httponly=True,
      │  │    samesite="Strict",  # 또는 "Lax"
      │  │    secure=settings.server.https_only,  # 프로덕션: True
      │  │    domain=settings.server.cookie_domain  # 선택
      │  │  )
      │  └─ 모든 로그인/토큰 발급 엔드포인트에서 호출
      └─ config.py 에 https_only, cookie_domain 추가

3.4.3 개발 환경 설정 (docker-compose.override.yml)
      └─ MCPER_SERVER_HTTPS_ONLY=false (개발)
         MCPER_SERVER_HTTPS_ONLY=true (프로덕션)

3.4.4 테스트
      ├─ 쿠키 속성 확인: HttpOnly, SameSite=Strict, Secure
      └─ 크로스 도메인: 쿠키 전송 불가 확인
```

**의존성**: 3.3 완료 후
**소요**: 1.5시간

---

### 3.5 테스트 (1.5시간)

```
3.5.1 단위 테스트 (test_cors_csrf.py)
      ├─ CORS preflight (OPTIONS)
      │  ├─ 허용된 origin: 200 + CORS 헤더
      │  └─ 허용 안 된 origin: 403 또는 CORS 에러
      ├─ CSRF 토큰 생성: 200 + 토큰
      ├─ POST without token: 403 Forbidden
      ├─ POST with token: 200 OK
      └─ 쿠키 속성: SameSite, Secure, HttpOnly

3.5.2 E2E 테스트
      ├─ Admin UI: 로그인 폼 접근
      ├─ CSRF 토큰 자동 주입 확인
      ├─ 로그인 폼 제출 (토큰 포함)
      ├─ 규칙 편집 (POST): CSRF 토큰 필수
      └─ 정책 기반 공격 시뮬레이션 (브라우저 보안 정책)

3.5.3 보안 감사 체크리스트
      ├─ OWASP CWE-352 (CSRF)
      ├─ OWASP CWE-1275 (CORS)
      └─ 외부 감사자 검수 (선택)
```

**의존성**: 3.4 완료 후
**소요**: 1.5시간

---

## 4. admin.py 모듈 분리 (10.5시간)

### 4.1 현재 admin.py 분석 (2시간)

```
4.1.1 기록관 요청 (@archivist)
      ├─ 파일: app/routers/admin.py (1293줄)
      ├─ 작업: 엔드포인트별 분류 + 메모 작성
      └─ 산출: .claude/archivist_notes/admin_endpoints_map.md

4.1.2 수동 분석 (기록관 없으면)
      ├─ 엔드포인트 목록: GET /admin, GET /admin/X, POST /admin/X, ...
      ├─ 임포트 분석: 의존성 확인
      ├─ 공통 함수: 유틸, 헬퍼
      └─ 템플릿 의존성: 어떤 HTML 파일을 렌더링하는지

4.1.3 분할 계획 수립
      ├─ admin.py (대시보드 + 라우터 등록): ~150줄
      ├─ admin_rules.py (규칙): ~300줄
      ├─ admin_specs.py (스펙): ~350줄
      ├─ admin_tools.py (도구): ~150줄
      └─ admin_utils.py (공통): ~200줄
```

**의존성**: 없음
**소요**: 2시간 (기록관 활용 권장)

---

### 4.2 공통 유틸 추출 (1시간)

```
4.2.1 app/routers/admin_utils.py (신규 파일)
      ├─ from app.auth.dependencies import require_admin_user (재export)
      ├─ from app.db.database import get_db (재export)
      ├─ def spec_display_title(row: Spec) -> str
      ├─ def content_looks_like_vector_or_blob(content) -> bool
      ├─ def paginate_results(query, page: int, per_page: int = 20)
      └─ 기타 공통 함수

4.2.2 app/routers/ 구조
      ├─ admin.py (기존, 정리됨)
      ├─ admin_utils.py (신규)
      ├─ admin_rules.py (신규)
      ├─ admin_specs.py (신규)
      ├─ admin_tools.py (신규)
      └─ __init__.py (라우터 임포트)

4.2.3 임포트 정리
      └─ 각 모듈: from app.routers.admin_utils import ...
```

**의존성**: 4.1 완료 후
**소요**: 1시간

---

### 4.3 규칙 라우터 추출 (2시간)

```
4.3.1 app/routers/admin_rules.py (신규 파일)
      ├─ from fastapi import APIRouter, Depends, ...
      ├─ router = APIRouter(prefix="/admin", tags=["rules"])
      └─ 엔드포인트:
         ├─ GET /admin/global-rules (뷰어)
         ├─ POST /admin/global-rules (발행)
         ├─ GET /admin/app-rules (앱 카드)
         ├─ GET /admin/app-rules/{app} (에디터)
         ├─ POST /admin/app-rules/{app} (발행)
         ├─ POST /admin/app-rules/{app}/append (추가)
         ├─ GET /admin/repo-rules (레포 카드)
         └─ POST /admin/repo-rules (발행)

4.3.2 기존 admin.py 에서 추출
      ├─ 함수 복사
      ├─ 임포트 정리
      └─ 템플릿 렌더링 경로 확인

4.3.3 테스트
      ├─ 각 엔드포인트 접근 가능 확인
      ├─ 규칙 발행 작동 확인
      └─ 템플릿 렌더링 확인
```

**의존성**: 4.2 완료 후
**소요**: 2시간

---

### 4.4 스펙 라우터 추출 (2시간)

```
4.4.1 app/routers/admin_specs.py (신규 파일)
      ├─ router = APIRouter(prefix="/admin", tags=["specs"])
      └─ 엔드포인트:
         ├─ GET /admin/specs (검색/필터)
         ├─ POST /admin/specs (단일 업로드)
         ├─ GET /admin/specs/{app} (앱별 목록)
         ├─ GET /admin/plan/{id} (상세)
         ├─ PUT /admin/plan/{id} (수정)
         ├─ DEL /admin/plan/{id} (삭제)
         ├─ GET /admin/plans/bulk-upload (폼)
         └─ POST /admin/plans/bulk-upload (다중 업로드)

4.4.2 기존 admin.py 에서 추출
      ├─ 함수 복사
      ├─ 파일 업로드 로직 확인
      ├─ Celery 큐잉 로직 확인
      └─ 템플릿 경로 확인

4.4.3 테스트
      ├─ 스펙 업로드 (단일): 201 Created
      ├─ 스펙 업로드 (다중): 200 OK
      ├─ 스펙 검색: 검색 결과 표시
      └─ 스펙 삭제: 204 No Content
```

**의존성**: 4.2 완료 후
**소요**: 2시간

---

### 4.5 도구 라우터 추출 (1시간)

```
4.5.1 app/routers/admin_tools.py (신규 파일)
      ├─ router = APIRouter(prefix="/admin", tags=["tools"])
      └─ 엔드포인트:
         ├─ GET /admin/tools (카탈로그)
         ├─ GET /admin/health (기본)
         └─ GET /admin/health/rag (RAG)

4.5.2 도구 메타데이터 로드
      ├─ from app.mcp_tools_docs import get_tools_docs
      └─ 템플릿에 전달: tools_list, call_stats

4.5.3 테스트
      ├─ /admin/tools: 10+ 도구 목록
      └─ /admin/health/rag: 메트릭 표시
```

**의존성**: 4.2 완료 후
**소요**: 1시간

---

### 4.6 기존 admin.py 정리 (1.5시간)

```
4.6.1 app/routers/admin.py (정리됨)
      ├─ 라우터 임포트 추가
      │  ├─ from app.routers.admin_rules import router as rules_router
      │  ├─ from app.routers.admin_specs import router as specs_router
      │  ├─ from app.routers.admin_tools import router as tools_router
      │  └─ from app.routers.admin_utils import require_admin_user, ...
      ├─ 대시보드 엔드포인트만 유지
      │  └─ GET /admin (기본 대시보드)
      └─ 라우터 등록 함수
         └─ def register_admin_routes(app):
            ├─ app.include_router(admin_router)
            ├─ app.include_router(rules_router)
            ├─ app.include_router(specs_router)
            └─ app.include_router(tools_router)

4.6.2 app/main.py 수정
      └─ 기존: app.include_router(admin_router)
         신규: register_admin_routes(app)

4.6.3 라인 수 확인
      └─ admin.py: <300줄 (목표)
```

**의존성**: 4.3, 4.4, 4.5 완료 후
**소요**: 1.5시간

---

### 4.7 통합 테스트 (1시간)

```
4.7.1 라우터 임포트 + 등록 확인
      ├─ uvicorn main:app --reload
      └─ 모든 엔드포인트 접근 가능 확인

4.7.2 엔드포인트별 테스트
      ├─ 대시보드: /admin
      ├─ 규칙: /admin/global-rules, /admin/app-rules/*
      ├─ 스펙: /admin/specs, /admin/plan/*
      └─ 도구: /admin/tools, /admin/health/rag

4.7.3 URL 경로 유지 확인
      ├─ 모든 기존 엔드포인트 동일 경로
      └─ 외부 링크 깨지지 않음

4.7.4 순환 임포트 확인
      └─ import graph: 순환 참조 없음
```

**의존성**: 4.6 완료 후
**소요**: 1시간

---

## 5. CodeNode 자동 인덱싱 파서 (9시간)

### 5.1 파서 프로토콜 및 인터페이스 정의 (1시간)

```
5.1.1 app/services/code_parsers/ 디렉토리 생성
      └─ __init__.py

5.1.2 app/services/code_parsers/interfaces.py (신규)
      ├─ from typing import Protocol, Any
      ├─ class CodeSymbol(TypedDict):
      │  ├─ kind: str  # "function", "class", "method"
      │  ├─ symbol_name: str
      │  ├─ lineno_start: int
      │  ├─ lineno_end: int
      │  ├─ signature: str
      │  └─ docstring: str | None
      ├─ class CodeParser(Protocol):
      │  └─ def parse(file_path: str, content: str) -> list[CodeSymbol]
      └─ 추상 클래스 구현

5.1.3 타입 정의
      └─ CodeNode 생성을 위한 데이터 구조
```

**의존성**: 없음
**소요**: 1시간

---

### 5.2 Python AST 파서 구현 (3시간)

```
5.2.1 app/services/code_parsers/python_parser.py (신규)
      ├─ import ast
      ├─ from typing import Any
      └─ class PythonCodeParser

5.2.2 함수별 구현
      ├─ def parse(self, file_path: str, content: str) -> list[CodeSymbol]
      │  ├─ ast.parse(content) 호출
      │  ├─ SyntaxError 처리: 로그만 기록, 계속
      │  └─ ast.walk() 순회
      ├─ def _extract_function(node: ast.FunctionDef) -> CodeSymbol
      │  ├─ kind = "function"
      │  ├─ symbol_name = node.name
      │  ├─ lineno_start/end = node.lineno/end_lineno
      │  ├─ signature = ast.get_source_segment() 또는 생성
      │  └─ docstring = ast.get_docstring(node)
      ├─ def _extract_class(node: ast.ClassDef) -> CodeSymbol
      │  ├─ kind = "class"
      │  └─ 메서드도 추출 (중첩)
      └─ def _extract_method(...): (선택)

5.2.3 메타데이터 추출
      ├─ 데코레이터: @property, @staticmethod, @classmethod
      ├─ 시그니처: 함수의 매개변수 목록
      ├─ Docstring: 주석/설명
      └─ 라인 범위: 함수가 차지하는 코드 라인

5.2.4 에러 처리
      ├─ SyntaxError: 로그 + skip
      ├─ UnicodeDecodeError: 로그 + skip
      └─ 타임아웃: 파일 크기 제한 (>10MB skip)

5.2.5 테스트 (단위)
      ├─ 샘플 Python 파일 파싱
      ├─ 함수 추출 확인
      ├─ 클래스 + 메서드 추출
      └─ docstring 추출 확인
```

**의존성**: 5.1 완료 후
**소요**: 3시간

---

### 5.3 CodeNode/CodeEdge 삽입 로직 (2시간)

```
5.3.1 app/services/spec_indexing.py 또는 신규 파일
      ├─ def insert_code_nodes(db, app_target, file_path, symbols)
      │  ├─ 각 symbol 에 대해 CodeNode 생성
      │  ├─ stable_id = f"{app_target}:{file_path}:{symbol_name}"
      │  ├─ embedding 계산: embed_texts([symbol_signature, docstring])
      │  ├─ upsert: (app_target, stable_id) 기준
      │  └─ 벌크 INSERT (성능)
      └─ def insert_code_edges(db, app_target, edges)
         ├─ EdgeOf 관계 추출 (import 분석)
         ├─ upsert: (app_target, source_id, target_id, relation) 기준
         ├─ ON CONFLICT DO NOTHING (중복 허용)
         └─ 벌크 INSERT

5.3.2 Celery 작업 통합
      └─ app/worker/tasks.py index_code_batch_task
         ├─ 기존: nodes, edges 받아서 삽입
         ├─ 신규: 파일 목록 → 파서 → CodeNode 생성 → 삽입
         └─ 재시도: max_retries=3

5.3.3 데이터베이스 스키마 확인
      ├─ app/db/rag_models.py CodeNode, CodeEdge 테이블
      ├─ embedding 필드: Vector(dim)
      └─ unique_constraint: (app_target, stable_id)

5.3.4 테스트
      ├─ 샘플 Python 파일 → CodeNode 생성
      ├─ 임베딩 벡터 계산 확인
      └─ 데이터베이스 삽입 확인
```

**의존성**: 5.2 완료 후
**소요**: 2시간

---

### 5.4 MCP 도구 확장 (1시간)

```
5.4.1 app/tools/rag_tools.py push_code_index_impl() 확인
      ├─ 기존: nodes, edges 수동 입력
      ├─ 신규: file_paths 입력 → 자동 파싱
      └─ 호출:
         ├─ 각 파일 읽기: open(file_path).read()
         ├─ 파서 선택: python_parser.parse(file_path, content)
         ├─ CodeNode/Edge 삽입
         └─ JSON 응답: {"ok": True, "nodes": N, "edges": M}

5.4.2 라우터 또는 Celery 태스크로 호출
      ├─ 옵션 A: MCP 도구 직접 호출 (동기)
      ├─ 옵션 B: Celery 태스크 (비동기)
      └─ 추천: 옵션 B (대용량 파일)

5.4.3 테스트
      ├─ MCP 도구 호출
      └─ CodeNode 자동 생성 확인
```

**의존성**: 5.3 완료 후
**소요**: 1시간

---

### 5.5 실제 레포 테스트 (1시간)

```
5.5.1 샘플 레포 준비
      ├─ MCPER 프로젝트 자신 또는 오픈소스 파이썬 프로젝트
      ├─ 크기: 최소 50개 파일, 1000+ 함수/클래스
      └─ 다양성: 클래스, 함수, 메서드, docstring 포함

5.5.2 파싱 실행
      ├─ 모든 .py 파일 수집
      ├─ 각 파일 파싱
      ├─ CodeNode 생성
      └─ 데이터베이스 삽입

5.5.3 검증
      ├─ 생성된 CodeNode 수: >100개
      ├─ 주요 심볼(main, __init__, etc) 포함 확인
      ├─ 임베딩 벡터 차원: 정확한 dim
      └─ 메타데이터: signature, docstring 포함

5.5.4 성능 테스트
      ├─ 파싱 시간: <5초 (100 파일)
      ├─ 메모리 사용: <500MB
      └─ 데이터베이스 삽입: <10초
```

**의존성**: 5.4 완료 후
**소요**: 1시간

---

## 6. Celery 모니터링 강화 (6시간)

### 6.1 TaskFailure DB 모델 추가 (1시간)

```
6.1.1 app/db/celery_models.py (신규 파일)
      ├─ from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
      ├─ from app.db.database import Base
      └─ class TaskFailure(Base)
         ├─ __tablename__ = "celery_task_failures"
         ├─ task_id: str (unique, indexed)
         ├─ spec_id: int (FK → specs.id)
         ├─ task_name: str (index_spec, index_code_batch)
         ├─ error_type: str (Exception 클래스)
         ├─ error_message: str (전체 메시지)
         ├─ retry_count: int (default 0)
         ├─ created_at: datetime
         └─ failed_at: datetime

6.1.2 마이그레이션 적용
      ├─ app/db/database.py _apply_lightweight_migrations()
      ├─ TaskFailure 테이블 생성 SQL 추가
      └─ ALTER TABLE IF NOT EXISTS ...

6.1.3 테스트
      └─ 테이블 생성 확인: SELECT * FROM celery_task_failures
```

**의존성**: 없음
**소요**: 1시간

---

### 6.2 Celery 작업 에러 핸들러 (1.5시간)

```
6.2.1 app/worker/tasks.py 기존 작업 수정
      ├─ @celery_app.task(name="index_spec", bind=True)
      └─ def index_spec_task(self, spec_id: int):
         ├─ try:
         │  ├─ 기존 로직
         │  └─ 성공 시: return {"ok": True, "spec_id": ..., "chunks": ...}
         └─ except Exception as e:
            ├─ db = SessionLocal()
            ├─ try:
            │  ├─ failure = TaskFailure(
            │  │    task_id=self.request.id,
            │  │    spec_id=spec_id,
            │  │    task_name="index_spec",
            │  │    error_type=type(e).__name__,
            │  │    error_message=str(e)
            │  │  )
            │  ├─ db.add(failure)
            │  └─ db.commit()
            └─ finally:
               ├─ db.close()
               └─ self.retry(exc=e, countdown=10) if retries < 3

6.2.2 index_code_batch_task 도 동일 적용
      └─ 동일 에러 핸들링

6.2.3 테스트
      ├─ 작업 강제 실패 시뮬레이션
      └─ TaskFailure 레코드 생성 확인
```

**의존성**: 6.1 완료 후
**소요**: 1.5시간

---

### 6.3 Admin UI 대시보드 추가 (2시간)

```
6.3.1 app/routers/admin_celery.py (신규 파일)
      ├─ router = APIRouter(prefix="/admin", tags=["celery"])
      └─ 엔드포인트:
         ├─ GET /admin/celery/failed-specs
         │  ├─ TaskFailure 테이블에서 조회
         │  ├─ spec_id 별로 최신 레코드
         │  ├─ 템플릿: celery_failed_specs.html
         │  └─ 정렬: failed_at desc (최근 실패)
         ├─ GET /admin/celery/task/{task_id}
         │  ├─ 단일 작업 상세
         │  ├─ Celery Inspect API로 상태 조회
         │  └─ 재시도 버튼 표시
         └─ POST /admin/celery/retry/{task_id}
            ├─ TaskFailure 조회
            ├─ Celery 작업 재발행
            ├─ retry_count 증가
            └─ 응답: {"ok": True, "retried": True, "retry_count": ...}

6.3.2 app/templates/admin/ 새 파일
      ├─ celery_failed_specs.html
      │  ├─ base.html 상속
      │  ├─ 테이블: 스펙 ID, 파일명, 실패 이유, 시간, 재시도 버튼
      │  └─ 페이지네이션: 최근 50개
      └─ celery_task_detail.html (선택)

6.3.3 base.html 사이드바에 링크 추가
      └─ <a href="/admin/celery/failed-specs">실패 작업</a>
```

**의존성**: 6.2 완료 후
**소요**: 2시간

---

### 6.4 /health/rag 엔드포인트 확장 (1시간)

```
6.4.1 app/main.py 기존 /health/rag 엔드포인트 확인
      └─ GET /health/rag (기본)
         ├─ 응답: {"ok": True, ...}

6.4.2 응답 필드 추가
      ├─ specs:
      │  ├─ total: 전체 스펙 수
      │  ├─ indexed: 인덱싱된 스펙 수 (SpecChunk 있는 것)
      │  └─ coverage: indexed / total
      ├─ celery:
      │  ├─ broker_ok: Redis 연결 상태
      │  ├─ active_tasks: 현재 실행 중 작업 수
      │  ├─ pending_tasks: 대기 중 작업 수
      │  └─ queue_depth: active + pending
      └─ failures_24h: 지난 24시간 실패 건수

6.4.3 구현
      ├─ from celery.app.control import Inspect
      ├─ inspect = celery_app.control.inspect()
      ├─ active_tasks = len(inspect.active() or {})
      ├─ failures_24h = db.query(TaskFailure).filter(...).count()
      └─ JSON 응답

6.4.4 테스트
      ├─ /health/rag 접근 → 200 OK
      └─ 응답 필드 확인
```

**의존성**: 6.3 완료 후
**소요**: 1시간

---

## 📊 WBS 요약

| Phase | 항목 | 태스크 수 | 예상 시간 |
|-------|------|---------|---------|
| 1 | Admin 패스워드 | 4 | 4시간 |
| 1 | API 토큰 만료 | 4 | 4.5시간 |
| 1 | CORS/CSRF | 5 | 7시간 |
| **Phase 1 합계** | | 13 | **15.5시간** |
| 2 | admin.py 분리 | 7 | 10.5시간 |
| 2 | CodeNode 파서 | 5 | 9시간 |
| 2 | Celery 모니터링 | 4 | 6시간 |
| **Phase 2 합계** | | 16 | **25.5시간** |
| **전체** | | **29** | **41시간** |

---

## 🔀 병렬 작업 타임라인

```
Week 1 (Phase 1: 보안)
Mon-Tue: 항목 1 (4시간) + 항목 2 병렬 시작
Tue-Wed: 항목 2 마무리 + 항목 3 시작
Wed-Thu: 항목 3 완료 + 통합 테스트
Thu: 검수 및 배포 준비

Week 2-3 (Phase 2: 구조)
Thu-Fri: 항목 4 (admin.py 분리) + 항목 5 (CodeNode) 병렬
Fri-Mon: 항목 4, 5, 6 (Celery) 병렬 진행
Mon-Tue: 통합 테스트 + 최종 검수
Tue: 배포
```

---

**WBS 작성 완료**

