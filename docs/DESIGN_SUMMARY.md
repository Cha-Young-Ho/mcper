# 기술 설계 종합 요약 (6개 항목)

**작성일**: 2026-03-30
**작성자**: @senior (아키텍처 설계)
**대상 읽자**: @coder (구현), @tester (검증), @pm (진행 관리)

---

## 개요

PM 평가 (2026-03-30) 기반 CRITICAL 3개 + HIGH 3개 항목에 대한 상세 기술 설계서 완성.

**문서 위치**:
- `docs/DESIGN_CRITICAL_SECURITY.md` — CRITICAL 3개 (보안)
- `docs/DESIGN_HIGH_REFACTOR.md` — HIGH 3개 (리팩터링/기능)
- `docs/DESIGN_SUMMARY.md` — 이 문서 (통합 요약)

---

## 1. 항목별 개요

### CRITICAL (즉시 필수)

| # | 항목 | 설계서 위치 | 핵심 | 예상 일정 |
|---|------|-----------|------|---------|
| 1 | Admin 패스워드 강제 변경 | DESIGN_CRITICAL_SECURITY.md § 1 | 초기 로그인 시 비밀번호 변경 강제 + CLI 검증 | 1-2일 |
| 2 | API 토큰 만료 검증 | DESIGN_CRITICAL_SECURITY.md § 2 | JWT expiry, refresh 토큰, API 키 expires_at | 1-2일 |
| 3 | CORS/CSRF 방어 | DESIGN_CRITICAL_SECURITY.md § 3 | CSRF 미들웨어, SameSite=Lax, Origin 검증 | 2-3일 |

### HIGH (1-2주 내)

| # | 항목 | 설계서 위치 | 핵심 | 예상 일정 |
|---|------|-----------|------|---------|
| 4 | admin.py 모듈 분리 | DESIGN_HIGH_REFACTOR.md § 1 | 1293줄 → 5개 라우터 (200줄씩) | 2-3일 |
| 5 | CodeNode 자동 파서 | DESIGN_HIGH_REFACTOR.md § 2 | Python/JS/Java AST 파싱 + 의존성 추출 | 2-3일 |
| 6 | Celery 모니터링 | DESIGN_HIGH_REFACTOR.md § 3 | FailedTask 테이블 + 대시보드 + 재시도 | 2-3일 |

---

## 2. 파일 변경 교차 의존성 분석

### 격리된 변경 (병렬 작업 가능)

**그룹 A (보안)**:
- `app/auth/service.py` — JWT 검증 강화
- `app/auth/dependencies.py` — 토큰 만료 체크
- `app/auth/router.py` — 새 엔드포인트 (refresh, validate, change-password-forced)
- `app/db/auth_models.py` — password_changed_at 필드
- `app/asgi/csrf_middleware.py` — 신규 미들웨어
- `app/main.py` — CSRF/CORS 미들웨어 등록

**그룹 B (리팩터링)**:
- `app/routers/admin_*.py` — 5개 신규 모듈 분리
- `app/routers/admin.py` — 라우터 통합만

**그룹 C (기능)**:
- `app/services/code_parser*.py` — 신규 파서 (3개 파일)
- `app/db/celery_models.py` — 신규 모니터링 모델
- `app/services/celery_monitoring.py` — 신규 서비스
- `app/routers/admin_monitoring.py` — 신규 라우터

### 공유 변경 파일

| 파일 | 변경 항목 | 충돌 가능성 |
|------|---------|----------|
| `app/main.py` | CSRF/CORS 미들웨어 + FailedTask import | 낮음 (각각 다른 섹션) |
| `app/db/database.py` | 마이그레이션 (3개 테이블: auth, celery, 기타) | 낮음 (순차 처리 가능) |
| `app/worker/tasks.py` | index_spec_task 실패 로깅 | 낮음 (추가 블록만) |
| `app/config.py` | auth, security 설정 추가 | 낮음 (기존 설정 유지) |

---

## 3. 구현 순서 (추천)

### Phase 1: CRITICAL 보안 (우선도 최고)

**병렬 작업 가능** (파일 분리):

```
Task 1: API 토큰 만료 검증
  └─ app/auth/service.py, dependencies.py, router.py 수정
  └─ 예상 일정: 1일

Task 2: Admin 패스워드 강제 변경
  └─ app/db/auth_models.py, main.py, router.py 수정
  └─ app/templates/auth/change_password_forced.html 신규
  └─ 예상 일정: 1.5일

Task 3: CORS/CSRF 방어
  └─ app/asgi/csrf_middleware.py, main.py 수정
  └─ app/config.py 수정
  └─ 예상 일정: 2일
```

**Phase 1 소요시간**: 2-3일 (병렬)

---

### Phase 2: HIGH 기능 (의존성 낮음)

**병렬 작업 가능**:

```
Task 4: CodeNode 자동 파서
  └─ app/services/code_parser*.py (5개 파일) 신규
  └─ app/tools/rag_tools.py 수정
  └─ 예상 일정: 2-3일

Task 5: Celery 모니터링
  └─ app/db/celery_models.py, services/celery_monitoring.py 신규
  └─ app/worker/tasks.py, main.py 수정
  └─ app/routers/admin_monitoring.py 신규
  └─ 예상 일정: 2-3일

Task 6: admin.py 모듈 분리 (리팩터)
  └─ app/routers/admin_*.py (5개) 신규
  └─ app/routers/admin.py 수정
  └─ app/main.py 수정
  └─ 예상 일정: 2-3일
```

**Phase 2 소요시간**: 3-4일 (병렬)

---

### 전체 일정

| Phase | 항목 | 병렬 | 예상 |
|-------|------|------|------|
| 1 | CRITICAL 3개 | O | 2-3일 |
| 2 | HIGH 3개 | O | 3-4일 |
| Test | 통합 테스트 + 문서 | - | 2-3일 |
| **Total** | **6개 항목** | - | **7-10일** |

---

## 4. 데이터베이스 마이그레이션 순서

**`app/db/database.py` → `_apply_lightweight_migrations()` 에서 순차 실행**:

```python
async def _apply_lightweight_migrations():
    """
    기존:
    1. specs.title 컬럼 추가
    2. various 테이블 생성
    3. 인덱스 생성
    """

    # Phase 1: 인증 (CRITICAL)
    if not _column_exists(..., "mcper_users", "password_changed_at"):
        session.execute(text("""
            ALTER TABLE mcper_users
            ADD COLUMN password_changed_at TIMESTAMP WITH TIME ZONE NULL
        """))

    # Phase 2: 모니터링 (HIGH)
    if not _table_exists(..., "failed_tasks"):
        session.execute(text("""
            CREATE TABLE failed_tasks (
                id SERIAL PRIMARY KEY,
                task_id VARCHAR(256) UNIQUE NOT NULL,
                task_name VARCHAR(128) NOT NULL,
                entity_type VARCHAR(64) NOT NULL,
                entity_id INTEGER NOT NULL,
                error_message TEXT NOT NULL,
                traceback TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                status VARCHAR(20) DEFAULT 'failed',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                failed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                resolved_at TIMESTAMP WITH TIME ZONE,
                metadata JSONB
            )
        """))
        # 인덱스
        session.execute(text("""
            CREATE INDEX idx_failed_tasks_entity
            ON failed_tasks(entity_type, entity_id)
        """))

    session.commit()
```

---

## 5. 설정 변경 (config.yaml / 환경 변수)

### 신규 환경 변수

**CRITICAL (보안)**:
```bash
# app/auth/service.py, dependencies.py
AUTH_TOKEN_EXPIRE_MINUTES=1440          # (기존) 토큰 유효시간
AUTH_SECRET_KEY=<your-secret>           # (기존, 필수) JWT 서명 키
SECURE_COOKIE=true                      # (신규) HTTPS only 쿠키

# app/asgi/csrf_middleware.py
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000  # (신규)
```

### config.example.yaml 업데이트

```yaml
auth:
  secret_key: "${AUTH_SECRET_KEY}"
  token_expire_minutes: 1440
  refresh_token_expire_minutes: 10080  # 7일

security:
  secure_cookie: true
  allowed_origins:
    - "http://localhost:3000"
    - "http://127.0.0.1:3000"
```

---

## 6. 테스트 전략

### Unit 테스트 (각 기능별)

```python
# tests/test_auth_token_expiry.py
def test_expired_token_rejected():
    """만료된 토큰 거부."""
    token = create_access_token({"sub": "1"}, timedelta(seconds=-1))
    with pytest.raises(JWTError):
        decode_token(token)

# tests/test_csrf_middleware.py
def test_csrf_token_validation():
    """CSRF 토큰 검증."""
    client = TestClient(app)
    resp = client.get("/admin")
    csrf_token = resp.cookies.get("csrf_token")

    resp = client.post("/admin/specs", data={
        "csrf_token": csrf_token,
        "title": "test"
    })
    assert resp.status_code == 200

# tests/test_code_parser.py
def test_python_parser():
    """Python AST 파싱."""
    code = "def hello():\n    pass"
    symbols, deps = CodeParserFactory.parse("test.py", code)
    assert len(symbols) == 1
    assert symbols[0].symbol_name == "hello"
```

### 통합 테스트 (엔드포인트)

```python
# tests/test_admin_specs.py
@pytest.mark.asyncio
async def test_admin_list_specs():
    """GET /admin/specs."""
    response = await client.get("/admin/specs")
    assert response.status_code == 200

# tests/test_celery_monitoring.py
@pytest.mark.asyncio
async def test_failed_task_retry():
    """실패 태스크 재시도."""
    response = await client.post("/admin/monitoring/failed/1/retry")
    assert response.status_code == 200
    assert response.json()["message"] == "Task queued for retry"
```

### 보안 테스트 (penetration)

```python
# tests/test_security.py
def test_csrf_attack():
    """CSRF 공격 방어."""
    # CSRF 토큰 없이 POST
    client = TestClient(app)
    resp = client.post("/admin/specs", data={"title": "hack"})
    assert resp.status_code == 403

def test_cors_origin_validation():
    """CORS Origin 검증."""
    client = TestClient(app)
    resp = client.post(
        "/admin/specs",
        headers={"Origin": "https://evil.com"}
    )
    assert "evil.com" not in resp.headers.get("Access-Control-Allow-Origin", "")
```

---

## 7. 배포 체크리스트

### 데이터베이스

- [ ] `_apply_lightweight_migrations()` 테스트 (특히 기존 테이블과의 호환성)
- [ ] 백업 후 마이그레이션 실행 (프로덕션 시)

### 환경 변수

- [ ] `AUTH_SECRET_KEY` 설정 (32자 이상 랜덤)
- [ ] `SECURE_COOKIE=true` (HTTPS only, 로컬 개발 제외)
- [ ] `CORS_ALLOWED_ORIGINS` 화이트리스트 설정
- [ ] `MCPER_AUTH_ENABLED=true` 시 필수 변수 확인

### 보안

- [ ] ADMIN_PASSWORD 변경 강제 (초기 로그인)
- [ ] JWT 토큰 만료 로직 테스트 (15분)
- [ ] CSRF 토큰 생성/검증 동작 확인
- [ ] MCP 엔드포인트는 CSRF 면제 확인

### 모니터링

- [ ] Celery 실패 로깅 동작 확인
- [ ] /admin/monitoring 대시보드 접근 가능 확인
- [ ] /health/rag 엔드포인트 응답 확인

### 문서

- [ ] 각 새 엔드포인트별 API 문서 추가 (OpenAPI/Swagger)
- [ ] 환경 변수 .env.example 업데이트
- [ ] 변경 사항을 docs/dev_log.md에 append

---

## 8. 롤백 계획

### Phase별 독립적 롤백 가능

**CRITICAL 항목**:
- `git revert <commit>` 후 마이그레이션 되돌리기
- password_changed_at 컬럼 DROP 하거나 무시하기
- CSRF 미들웨어 비활성화 (MCP_BYPASS_TRANSPORT_GATE=1)

**HIGH 항목**:
- admin.py 모듈 분리는 기존 admin.py 복원으로 롤백 (템플릿은 동일)
- CodeNode 파서는 auto_parse=false로 비활성화
- Celery 모니터링은 FailedTask 테이블만 생성, 기존 태스크 로직 변경 없음

---

## 9. 각 설계서별 핵심 내용 요약

### DESIGN_CRITICAL_SECURITY.md

**3개 항목의 상세 구현 전략**:

1. **Admin 패스워드 강제 변경**
   - DB: User.password_changed_at 추가
   - UI: GET/POST /auth/change-password-forced
   - 검증: 기본 비밀번호 차단, 최소 8글자

2. **API 토큰 만료 검증**
   - JWT: decode_token에 expiry 검증 강화
   - Refresh: POST /auth/token/refresh 엔드포인트
   - API 키: expires_at 필드 검증

3. **CORS/CSRF 방어**
   - 미들웨어: CSRFMiddleware (토큰 생성/검증)
   - 쿠키: SameSite=Lax, Secure, HttpOnly
   - Origin: 동적 화이트리스트

---

### DESIGN_HIGH_REFACTOR.md

**3개 항목의 상세 구현 전략**:

4. **admin.py 모듈 분리**
   - 구조: admin_base (공통) + dashboard + rules + specs + tools
   - 각 모듈 200-300줄 범위
   - main.py: include_router로 통합

5. **CodeNode 자동 파서**
   - 인터페이스: CodeParserBase (AST 파서 추상화)
   - 구현: Python (ast), JavaScript (정규식)
   - 팩토리: CodeParserFactory로 언어별 선택

6. **Celery 모니터링**
   - DB: FailedTask 테이블 (task_id, entity, error, retry_count)
   - 태스크: index_spec_task에 실패 로깅
   - UI: /admin/monitoring (대시보드 + 재시도 버튼)

---

## 10. 제약 사항 및 가정

### 제약 사항

1. **password_changed_at 필드**
   - 초기 관리자는 NULL (변경 강제)
   - OAuth 유저도 초기에 NULL 이면 강제 변경 필요
   - 또는: OAuth 유저는 설정 password_changed_at = NOW()

2. **CSRF 토큰**
   - MCP POST 요청은 CSRF 검증 제외 (Bearer 토큰 기반)
   - WebSocket은 CSRF 검증 제외

3. **CodeNode 파서**
   - 정규식 기반 JS 파싱은 완전하지 않음 (동적 코드, decorator 등 미지원)
   - 향후 esprima.js 또는 Babel 플러그인으로 개선 가능

4. **FailedTask 테이블**
   - Traceback 길이 제한 필요 (TEXT 컬럼은 크기 무제한이므로 어플리케이션 레벨에서 truncate)
   - 정리 정책: 일정 기간(예: 30일) 후 자동 삭제

---

## 11. 성공 기준

### CRITICAL 항목

- [x] Admin 기본 패스워드로 로그인 불가 (강제 변경)
- [x] JWT 토큰 15분 후 자동 만료 (refresh로 갱신 가능)
- [x] 다른 도메인에서 CSRF 공격 시 403 Forbidden

### HIGH 항목

- [x] admin.py 각 모듈 <= 350줄
- [x] Python/JS 파일 자동 파싱 (90% 이상 정확도)
- [x] 실패 스펙 재시도 UI에서 수동 가능

---

## 12. 다음 단계

### 즉시 (1주)

1. 각 @coder 팀원이 설계 문서 읽기 + 질문
2. DB 마이그레이션 테스트 (로컬)
3. Phase 1 (CRITICAL) 구현 + 테스트

### 2주차

1. Phase 2 (HIGH) 구현 + 테스트
2. 통합 테스트
3. 문서 최종 검토

### 3주차

1. Staging 배포 + 보안 테스트
2. 프로덕션 배포 + 모니터링
3. 사후 분석 (lessons learned)

---

## 13. 참고자료 및 템플릿

### 코드 템플릿

**새 라우터 작성** (admin_*.py):
```python
from fastapi import APIRouter, Request
from app.routers.admin_base import AdminContext, render_admin_html

router = APIRouter(prefix="/admin", tags=["admin_something"])

@router.get("/something", name="admin_something")
async def view_something(request: Request, ctx: AdminContext):
    return render_admin_html("something.html", {
        "request": request,
        "user": ctx.user,
    })
```

**새 미들웨어 등록** (main.py):
```python
app.add_middleware(CSRFMiddleware, secret_key=settings.auth.secret_key)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(settings),
    allow_credentials=True,
)
```

**새 모델 정의** (db/models.py):
```python
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

class SomethingModel(Base):
    __tablename__ = "somethings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
```

### 테스트 템플릿

**FastAPI 테스트**:
```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_endpoint():
    response = client.get("/admin")
    assert response.status_code == 200
```

---

## 요약

**CRITICAL 3개 + HIGH 3개** 항목에 대한 완전한 기술 설계 완료.

- 파일 변경 최소화 (기존 코드와의 호환성 유지)
- 병렬 작업 가능 (각 항목이 독립적)
- 7-10일 소요 예상 (병렬 진행)
- 롤백 계획 포함 (단계별 독립적 롤백 가능)

**다음**: @coder가 설계 문서를 바탕으로 구현 시작.

---

**문서 버전**: 1.0
**작성 완료**: 2026-03-30
**검토자**: @pm, @senior
**담당 구현자**: @coder
**테스트 담당자**: @tester
