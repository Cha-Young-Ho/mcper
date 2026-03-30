# CRITICAL 보안 3개 항목 기술 설계서

**작성일**: 2026-03-30
**작성자**: @senior (아키텍처 설계)
**범위**: Admin 패스워드 강제 변경, API 토큰 만료 검증, CORS/CSRF 방어

---

## 1. Admin 패스워드 강제 변경 (초기 로그인 시)

### 1.1 문제 정의 (Why)

**현재 상태**:
- `ADMIN_PASSWORD=changeme` (기본값)
- 경고만 표시하고 강제하지 않음
- 보안 취약점: 기본 크레덴셜로 어드민 패널 접근 가능

**요구사항**:
- 초기 로그인 시 패스워드 변경 강제
- 변경 완료 전까지 다른 페이지 접근 금지 (302 redirect)
- CLI 검증: 기본 패스워드 사용 중이면 시작 시 경고 + 메시지

---

### 1.2 솔루션 아키텍처

#### 1.2.1 DB 스키마 (User 테이블 확장)

**신규 필드 추가** (`app/db/auth_models.py`):
```python
class User(Base):
    __tablename__ = "mcper_users"
    # ... 기존 필드
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # NULL = 기본 패스워드 상태 (초기 관리자 유저만)
```

**마이그레이션** (`app/db/database.py` → `_apply_lightweight_migrations`):
```python
# seed 이후 실행
if not _column_exists(session, "mcper_users", "password_changed_at"):
    session.execute(text("""
        ALTER TABLE mcper_users
        ADD COLUMN password_changed_at TIMESTAMP WITH TIME ZONE NULL
    """))
```

#### 1.2.2 로그인 흐름 변경

**require_admin_user 의존성** (`app/auth/dependencies.py`):
```python
async def require_admin_user(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    basic_credentials: HTTPBasicCredentials | None = Depends(basic_scheme),
) -> str:
    if not _auth_enabled:
        return _check_basic_auth(basic_credentials)

    if user is None:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/auth/login", status_code=303)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, ...)

    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, ...)

    # ✨ 신규: 패스워드 미변경 체크
    if user.password_changed_at is None:
        # 이미 /auth/change-password-forced인지 확인
        if not request.url.path.startswith("/auth/change-password-forced"):
            return RedirectResponse(url="/auth/change-password-forced", status_code=303)

    return user.username
```

#### 1.2.3 신규 엔드포인트

**`app/routers/auth.py` (또는 `app/auth/router.py` 신규)** 에 추가:

```python
@router.get("/auth/change-password-forced")
async def change_password_forced_form(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    """기본 패스워드 변경 강제 폼 (패스워드_changed_at is NULL일 때만)."""
    if not _auth_enabled or user is None:
        raise RedirectResponse(url="/auth/login", status_code=303)

    if user.password_changed_at is not None:
        # 이미 변경함 → 대시보드로
        return RedirectResponse(url="/admin", status_code=303)

    # is_admin=True 확인
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    return templates.TemplateResponse(
        "auth/change_password_forced.html",
        {"request": request, "username": user.username}
    )

@router.post("/auth/change-password-forced")
async def change_password_forced_submit(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """패스워드 변경 제출."""
    if not _auth_enabled or user is None:
        raise RedirectResponse(url="/auth/login", status_code=303)

    if user.password_changed_at is not None:
        return RedirectResponse(url="/admin", status_code=303)

    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    form = await request.form()
    password = form.get("password", "").strip()
    password_confirm = form.get("password_confirm", "").strip()

    # 검증
    if not password or len(password) < 8:
        return templates.TemplateResponse(
            "auth/change_password_forced.html",
            {
                "request": request,
                "username": user.username,
                "error": "Password must be at least 8 characters",
            },
            status_code=400,
        )

    if password != password_confirm:
        return templates.TemplateResponse(
            "auth/change_password_forced.html",
            {
                "request": request,
                "username": user.username,
                "error": "Passwords do not match",
            },
            status_code=400,
        )

    # 기본 패스워드와 동일하지 않은지 확인
    default_password = os.environ.get("ADMIN_PASSWORD", "changeme")
    if secrets.compare_digest(password, default_password):
        return templates.TemplateResponse(
            "auth/change_password_forced.html",
            {
                "request": request,
                "username": user.username,
                "error": "Password cannot be the default password",
            },
            status_code=400,
        )

    # 업데이트
    user.hashed_password = hash_password(password)
    user.password_changed_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()

    return RedirectResponse(url="/admin", status_code=303)
```

#### 1.2.4 CLI 검증 (main.py 시작 시)

**`app/main.py`** (lifespan → startup):

```python
async def _validate_admin_password():
    """기본 패스워드 사용 경고."""
    admin_password = os.environ.get("ADMIN_PASSWORD", "changeme")
    if admin_password == "changeme":
        logger.warning(
            "⚠️  ADMIN_PASSWORD is still 'changeme' (default). "
            "Please change it immediately via /auth/change-password-forced"
        )
        if os.environ.get("MCPER_AUTH_ENABLED", "").lower() in ("1", "true"):
            # CRITICAL: AUTH 활성화 + 기본 패스워드
            logger.error(
                "🛑 CRITICAL: MCPER_AUTH_ENABLED=true with default ADMIN_PASSWORD. "
                "Set new ADMIN_PASSWORD in environment or change via web UI."
            )

# lifespan에 호출 추가 (configure_logging 직후)
_validate_admin_password()
```

---

### 1.3 신규/수정 파일

| 파일 | 작업 | 설명 |
|------|------|------|
| `app/db/auth_models.py` | 수정 | User.password_changed_at 필드 추가 |
| `app/db/database.py` | 수정 | _apply_lightweight_migrations에 컬럼 추가 |
| `app/auth/dependencies.py` | 수정 | require_admin_user에 강제 변경 리다이렉트 로직 |
| `app/auth/router.py` | 신규 | GET/POST /auth/change-password-forced 엔드포인트 |
| `app/templates/auth/change_password_forced.html` | 신규 | 강제 변경 폼 |
| `app/main.py` | 수정 | _validate_admin_password() 호출 |

---

### 1.4 API 스펙

#### GET /auth/change-password-forced
**응답 (200 OK)**:
```html
<form method="POST">
  <input name="password" type="password" required>
  <input name="password_confirm" type="password" required>
  <button type="submit">Change Password</button>
</form>
```

#### POST /auth/change-password-forced
**요청**:
```
Content-Type: application/x-www-form-urlencoded
password=newpass&password_confirm=newpass
```

**응답 (303 See Other)**: `Location: /admin`

**에러 (400 Bad Request)**:
```html
<div class="error">Password must be at least 8 characters</div>
```

---

### 1.5 구현 체크리스트

- [ ] User 모델에 password_changed_at 필드 추가
- [ ] 데이터베이스 마이그레이션 로직 구현
- [ ] require_admin_user에 리다이렉트 로직 추가
- [ ] /auth/change-password-forced GET 엔드포인트 구현
- [ ] /auth/change-password-forced POST 엔드포인트 구현
- [ ] change_password_forced.html 템플릿 작성
- [ ] app/main.py에 _validate_admin_password 호출 추가
- [ ] 초기 관리자 생성 시 password_changed_at=NULL 설정 확인 (seed_defaults.py)

---

### 1.6 테스트 시나리오

#### 정상 케이스
1. 초기 관리자 로그인 (password_changed_at=NULL)
   - 예상: /auth/change-password-forced로 자동 리다이렉트
2. 새 패스워드 입력 및 제출
   - 예상: 데이터베이스 password_changed_at 업데이트, /admin으로 리다이렉트
3. 패스워드 변경 후 다시 로그인
   - 예상: /admin에 직접 접근 가능 (리다이렉트 없음)

#### 엣지 케이스
1. 기본 패스워드와 동일한 새 패스워드 입력
   - 예상: 에러 메시지 표시, 폼 다시 렌더링
2. 패스워드 길이 < 8 글자
   - 예상: 에러 메시지 ("must be at least 8 characters")
3. 비밀번호 확인 불일치
   - 예상: 에러 메시지 ("Passwords do not match")

#### 실패 케이스
1. 로그인 없이 /auth/change-password-forced 접근
   - 예상: 302 → /auth/login
2. 이미 패스워드 변경한 유저가 /auth/change-password-forced 접근
   - 예상: 303 → /admin

---

### 1.7 위험 및 완화 전략

| 위험 | 완화 방법 |
|------|----------|
| 초기 관리자 생성 후 password_changed_at 설정 누락 | seed_defaults.py 명시적으로 NULL 설정 |
| 기존 관리자 유저가 password_changed_at가 NULL인 상태 | DB 마이그레이션 시 기존 해시 패스워드 있으면 현재 시간 설정 |
| MCPER_AUTH_ENABLED=false 상태에서 혼동 | require_admin_user에서 조건문으로 분기 |

---

---

## 2. API 토큰 만료 검증 (JWT expiry + Refresh 토큰)

### 2.1 문제 정의 (Why)

**현재 상태**:
- JWT 토큰에 exp 클레임 설정됨 (create_access_token)
- 하지만 decode 시 만료 검증을 명시적으로 수행하지 않음 (jose 라이브러리의 기본 동작)
- API 키 (ApiKey 테이블)의 expires_at는 선언만 되고 검증 없음
- 토큰 갱신(refresh) 엔드포인트 없음

**요구사항**:
- JWT 토큰 만료 시 명시적 거부 (401)
- API 키 expires_at 검증
- 토큰 갱신 엔드포인트 (short-lived access + refresh 패턴)
- 토큰 검증 결과 명확한 에러 메시지

---

### 2.2 솔루션 아키텍처

#### 2.2.1 JWT 만료 검증 강화

**`app/auth/service.py`** 수정:

```python
from datetime import datetime, timezone
from jose import JWTError, jwt, ExpiredSignatureError

def decode_token(token: str, allow_expired: bool = False) -> dict:
    """
    JWT 검증. 만료 시 기본적으로 JWTError 발생.
    allow_expired=True → 만료된 토큰도 payload 반환 (refresh 토큰 갱신용).
    """
    try:
        return jwt.decode(
            token,
            settings.auth.secret_key,
            algorithms=["HS256"],
            options={"verify_exp": not allow_expired}  # False면 exp 체크 안 함
        )
    except ExpiredSignatureError:
        if allow_expired:
            # 만료된 토큰의 payload 반환 (refresh 토큰에서 유저ID 추출용)
            return jwt.decode(
                token,
                settings.auth.secret_key,
                algorithms=["HS256"],
                options={"verify_exp": False}
            )
        raise JWTError("Token has expired")

def verify_token_not_expired(token: str) -> bool:
    """토큰 만료 여부만 확인. True = 유효."""
    try:
        jwt.decode(
            token,
            settings.auth.secret_key,
            algorithms=["HS256"],
        )
        return True
    except ExpiredSignatureError:
        return False
    except JWTError:
        return False
```

#### 2.2.2 API 키 만료 검증

**`app/auth/dependencies.py`** 수정:

```python
async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """JWT 쿠키 → Bearer 헤더 → API 키 순."""
    if not _auth_enabled:
        return None

    token = request.cookies.get("mcper_token")
    if not token and credentials:
        token = credentials.credentials

    if not token:
        return None

    # 1) JWT 검증 (만료도 체크)
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if user_id is not None:
            user = db.get(User, int(user_id))
            if user and user.is_active:
                return user
    except JWTError:
        pass

    # 2) API 키 검증
    if credentials and credentials.credentials:
        key_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        api_key = db.scalar(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        if api_key:
            # ✨ 만료 검증
            if api_key.expires_at is not None:
                now = datetime.now(timezone.utc)
                if api_key.expires_at < now:
                    logger.warning(f"Expired API key used: {api_key.id}")
                    return None  # 만료됨

            # 마지막 사용 시간 업데이트
            api_key.last_used_at = datetime.now(timezone.utc)
            db.add(api_key)
            # commit 생략 (요청 컨텍스트 후 커밋)

            user = db.get(User, api_key.user_id)
            if user and user.is_active:
                return user

    return None
```

#### 2.2.3 Refresh 토큰 패턴

**새 엔드포인트** (`app/auth/router.py`):

```python
@router.post("/auth/token/refresh")
async def refresh_access_token(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Refresh 토큰으로 새 Access 토큰 발급.
    Request: { "refresh_token": "..." }
    Response: { "access_token": "...", "token_type": "bearer" }
    """
    if not _auth_enabled:
        raise HTTPException(status_code=400, detail="Auth not enabled")

    try:
        data = await request.json()
        refresh_token = data.get("refresh_token", "").strip()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not refresh_token:
        raise HTTPException(status_code=400, detail="refresh_token required")

    # 만료된 토큰도 payload 추출 가능하게
    try:
        payload = decode_token(refresh_token, allow_expired=True)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = payload.get("sub")
    token_type = payload.get("type")

    # refresh 토큰만 수락
    if token_type != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user = db.get(User, int(user_id)) if user_id else None
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # 새 access 토큰 발급 (짧은 수명)
    access_token = create_access_token(
        {"sub": str(user.id), "type": "access"},
        expires_delta=timedelta(minutes=15)  # 15분 (config에서 읽을 수 있음)
    )

    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/auth/token/validate")
async def validate_token(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    """
    토큰 유효성 확인.
    Response: { "valid": true, "user_id": 1, "expires_at": "2026-03-31T12:00:00Z" }
    """
    if not _auth_enabled:
        raise HTTPException(status_code=400, detail="Auth not enabled")

    if user is None:
        raise HTTPException(status_code=401, detail="No valid token")

    # JWT 쿠키에서 exp 추출
    token = request.cookies.get("mcper_token")
    expires_at = None
    if token:
        try:
            payload = decode_token(token)
            if "exp" in payload:
                expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        except JWTError:
            pass

    return {
        "valid": True,
        "user_id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
```

#### 2.2.4 로그인 시 Refresh 토큰 발급

**`app/auth/router.py` → POST /auth/login** 수정:

```python
@router.post("/auth/login")
async def login_post(
    request: Request,
    db: Session = Depends(get_db),
):
    """로그인 폼 제출."""
    if not _auth_enabled:
        raise HTTPException(status_code=400, detail="Auth not enabled")

    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "").strip()

    # 검증 및 사용자 조회
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active or not verify_password(password, user.hashed_password or ""):
        # 실패
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Invalid credentials"},
            status_code=401,
        )

    # ✨ 수명이 다른 두 토큰 발급
    access_token = create_access_token(
        {"sub": str(user.id), "type": "access"},
        expires_delta=timedelta(minutes=15)  # 15분 (짧음)
    )
    refresh_token = create_access_token(
        {"sub": str(user.id), "type": "refresh"},
        expires_delta=timedelta(days=7)  # 7일 (길음)
    )

    # 응답에 access 토큰만 쿠키에, refresh는 secure 쿠키 또는 localStorage용으로
    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        "mcper_token",
        value=access_token,
        httponly=True,
        secure=settings.security.secure_cookie,
        samesite="lax",
        max_age=900,  # 15분
    )
    # refresh 토큰: secure 쿠키 (선택적) 또는 클라이언트가 localStorage 사용
    # 일단 쿠키로도 전달 (httponly 제거 시 JS에서 사용 가능)
    response.set_cookie(
        "mcper_refresh_token",
        value=refresh_token,
        httponly=False,  # JS에서 필요하면 접근 가능
        secure=settings.security.secure_cookie,
        samesite="lax",
        max_age=604800,  # 7일
    )

    user.last_login = datetime.now(timezone.utc)
    db.add(user)
    db.commit()

    return response
```

---

### 2.3 신규/수정 파일

| 파일 | 작업 | 설명 |
|------|------|------|
| `app/auth/service.py` | 수정 | decode_token에 allow_expired 파라미터, verify_token_not_expired 추가 |
| `app/auth/dependencies.py` | 수정 | API 키 expires_at 검증 로직 추가 |
| `app/auth/router.py` | 수정 | POST /auth/login에서 access/refresh 토큰 발급 |
| `app/auth/router.py` | 신규 | POST /auth/token/refresh, POST /auth/token/validate 엔드포인트 |

---

### 2.4 API 스펙

#### POST /auth/token/refresh
**요청**:
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**응답 (200 OK)**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

**에러 (401 Unauthorized)**:
```json
{
  "detail": "Invalid refresh token"
}
```

#### POST /auth/token/validate
**요청**: (JWT 쿠키 또는 Bearer 헤더)

**응답 (200 OK)**:
```json
{
  "valid": true,
  "user_id": 1,
  "username": "admin",
  "is_admin": true,
  "expires_at": "2026-03-30T12:15:00Z"
}
```

**에러 (401 Unauthorized)**:
```json
{
  "detail": "No valid token"
}
```

---

### 2.5 구현 체크리스트

- [ ] decode_token 함수에 allow_expired 파라미터 추가
- [ ] verify_token_not_expired 유틸 함수 추가
- [ ] get_current_user_optional에 ApiKey.expires_at 검증 로직 추가
- [ ] API 키 last_used_at 업데이트 로직 추가
- [ ] POST /auth/token/refresh 엔드포인트 구현
- [ ] POST /auth/token/validate 엔드포인트 구현
- [ ] POST /auth/login에서 access/refresh 토큰 발급 로직 수정
- [ ] config.py에 토큰 만료 시간 설정 추가 (선택)

---

### 2.6 테스트 시나리오

#### 정상 케이스
1. 로그인 후 access 토큰 획득
   - 예상: 쿠키 mcper_token 설정, 15분 유효
2. Access 토큰으로 API 호출
   - 예상: 200 OK
3. Access 토큰 만료 후 refresh 토큰으로 새 access 토큰 획득
   - 예상: 새 access 토큰 발급, 기존 데이터 유실 없음

#### 엣지 케이스
1. Refresh 토큰도 만료됨
   - 예상: 401 "Invalid refresh token"
2. 토큰 타입 확인 실패 (access 토큰으로 refresh 시도)
   - 예상: 401 "Invalid token type"
3. API 키의 expires_at 넘음
   - 예상: 401 또는 403

#### 실패 케이스
1. 만료된 토큰으로 API 호출
   - 예상: 401 "Token has expired"
2. 유효하지 않은 refresh 토큰
   - 예상: 401 "Invalid refresh token"
3. 삭제된 유저의 토큰 사용
   - 예상: 401

---

### 2.7 위험 및 완화 전략

| 위험 | 완화 방법 |
|------|----------|
| Refresh 토큰 탈취 | httponly 쿠키 + secure flag (HTTPS only) |
| Access 토큰 수명이 너무 길면 보안 위험 | 15분으로 제한, refresh로 갱신 |
| API 키 expires_at 검증 누락 | get_current_user_optional에서 명시적 체크 |
| 클라이언트가 토큰 갱신을 잊을 가능성 | POST /auth/token/validate로 주기적 확인 권장 |

---

---

## 3. CORS/CSRF 방어 강화

### 3.1 문제 정의 (Why)

**현재 상태**:
- SameSite=Lax 쿠키 설정 없음 (또는 기본값)
- CSRF 토큰 미들웨어 부재
- CORS 정책이 다소 너무 열려있을 가능성
- Cross-origin 스크립트 공격 방어 미흡

**요구사항**:
- POST/PUT/DELETE 엔드포인트에 CSRF 토큰 검증
- SameSite=Lax (또는 Strict) 쿠키
- CORS 동적 화이트리스트 적용
- Origin 헤더 검증 강화

---

### 3.2 솔루션 아키텍처

#### 3.2.1 CSRF 토큰 미들웨어

**신규 파일** `app/asgi/csrf_middleware.py`:

```python
"""CSRF 토큰 생성 및 검증 미들웨어."""

import secrets
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi import HTTPException, status
import logging

logger = logging.getLogger(__name__)

CSRF_TOKEN_LENGTH = 32
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_FORM_NAME = "csrf_token"

class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF 토큰 생성 및 검증.
    - GET: 토큰 생성 후 응답에 포함 (쿠키)
    - POST/PUT/DELETE: 토큰 검증 (header 또는 form)
    """

    def __init__(self, app, secret_key: str):
        super().__init__(app)
        self.secret_key = secret_key

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # CSRF 토큰 생성/검증 (MCP, WebSocket 제외)
        if request.url.path.startswith("/mcp") or request.url.path == "/ws":
            return await call_next(request)

        # GET/HEAD/OPTIONS: 토큰 생성
        if request.method in SAFE_METHODS:
            response = await call_next(request)
            # 응답에 CSRF 토큰 쿠키 추가
            token = secrets.token_hex(CSRF_TOKEN_LENGTH // 2)
            response.set_cookie(
                "csrf_token",
                value=token,
                httponly=False,  # JS에서 X-CSRF-Token 헤더로 읽을 수 있게
                secure=True,  # HTTPS only
                samesite="lax",
                max_age=86400,  # 24시간
            )
            return response

        # POST/PUT/DELETE/PATCH: 토큰 검증
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            # 토큰 추출 (header 우선, 그 다음 form)
            token_from_header = request.headers.get(CSRF_HEADER_NAME, "").strip()

            token_from_form = None
            if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
                try:
                    form = await request.form()
                    token_from_form = form.get(CSRF_FORM_NAME, "").strip()
                except Exception:
                    pass

            token_from_request = token_from_header or token_from_form

            # 쿠키에서 토큰 추출
            token_from_cookie = request.cookies.get("csrf_token", "").strip()

            # 검증
            if not token_from_cookie or not token_from_request:
                logger.warning(f"CSRF token missing: method={request.method}, path={request.url.path}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="CSRF token missing or invalid",
                )

            if not secrets.compare_digest(token_from_cookie, token_from_request):
                logger.warning(f"CSRF token mismatch: method={request.method}, path={request.url.path}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="CSRF token validation failed",
                )

        return await call_next(request)
```

#### 3.2.2 SameSite 쿠키 설정 강화

**`app/main.py`** — lifespan에서 쿠키 설정 명시:

```python
# 모든 set_cookie 호출에 다음 옵션 포함:
# - samesite="lax" (폼 제출은 허용, 크로스사이트 이미지 요청은 보내지 않음)
# - secure=True (HTTPS only, 로컬 개발은 False)
# - httponly=True (JS에서 접근 불가)
```

**`app/auth/router.py` → POST /auth/login**:

```python
response.set_cookie(
    "mcper_token",
    value=access_token,
    httponly=True,
    secure=settings.security.secure_cookie,  # config에서 읽음
    samesite="lax",
    max_age=900,
)
```

#### 3.2.3 CORS 정책 강화

**`app/main.py`** — FastAPI CORSMiddleware:

```python
from fastapi.middleware.cors import CORSMiddleware

# 신규: 동적 화이트리스트 생성
def _get_allowed_origins(app_settings) -> list[str]:
    """
    CORS 허용 Origin 목록 생성.
    1. config.security.allowed_origins (YAML)
    2. CORS_ALLOWED_ORIGINS 환경 변수 (쉼표 구분)
    3. 기본값: ["http://localhost:*", "http://127.0.0.1:*"]
    """
    origins = []

    # config.yaml 에서
    if app_settings.security.allowed_origins:
        origins.extend(app_settings.security.allowed_origins)

    # 환경 변수에서
    env_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if env_origins:
        origins.extend([o.strip() for o in env_origins.split(",")])

    # 기본값
    if not origins:
        origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

    return list(set(origins))  # 중복 제거

# app 초기화 시
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(settings),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-CSRF-Token",  # CSRF 토큰 헤더
        "X-Requested-With",
    ],
    expose_headers=["Content-Type"],
    max_age=86400,
)
```

#### 3.2.4 CSRF 토큰 폼/API 통합

**템플릿 (HTML)** — CSRF 토큰 자동 포함:

```html
<form method="POST" action="/admin/specs">
  {% csrf_token %}  <!-- Jinja2 custom tag -->
  <input name="title" type="text">
  <button type="submit">Upload</button>
</form>
```

**Jinja2 커스텀 필터** (`app/main.py`):

```python
def csrf_token_input(csrf_token: str) -> str:
    """Jinja2 필터: csrf_token이라는 쿠키에서 생성."""
    return f'<input type="hidden" name="csrf_token" value="{csrf_token}">'

templates.env.filters["csrf_token"] = csrf_token_input
```

또는 더 간단하게, 템플릿에서:

```html
<input type="hidden" name="csrf_token" value="{{ request.cookies.get('csrf_token', '') }}">
```

**API 클라이언트** (JS/Fetch):

```javascript
// CSRF 토큰 쿠키에서 읽기
const getCsrfToken = () => {
  const match = document.cookie.match(/csrf_token=([^;]+)/);
  return match ? match[1] : "";
};

// POST 요청
fetch("/admin/specs", {
  method: "POST",
  headers: {
    "X-CSRF-Token": getCsrfToken(),
    "Content-Type": "application/json",
  },
  body: JSON.stringify({title: "...", content: "..."})
});
```

#### 3.2.5 MCP 엔드포인트는 CSRF 면제

**`app/asgi/csrf_middleware.py`**:

```python
async def dispatch(self, request: Request, call_next: Callable) -> Response:
    # MCP, WebSocket 경로는 CSRF 검증 생략
    if request.url.path.startswith("/mcp") or request.url.path == "/ws":
        return await call_next(request)

    # (나머지 로직)
```

이유: MCP는 Bearer 토큰 기반 인증이므로 CSRF 취약점 없음.

---

### 3.3 신규/수정 파일

| 파일 | 작업 | 설명 |
|------|------|------|
| `app/asgi/csrf_middleware.py` | 신규 | CSRF 토큰 생성/검증 미들웨어 |
| `app/main.py` | 수정 | CSRFMiddleware 추가, CORSMiddleware 설정, _get_allowed_origins 함수 |
| `app/config.py` | 수정 | security.secure_cookie, security.allowed_origins 설정 추가 |
| `app/auth/router.py` | 수정 | set_cookie에 samesite="lax", secure=True 추가 |
| `config.example.yaml` | 수정 | CORS_ALLOWED_ORIGINS 예시 추가 |

---

### 3.4 API 스펙

#### CSRF 토큰 생성 (자동)

**GET /admin** (또는 모든 GET 요청):
- 응답 헤더: `Set-Cookie: csrf_token=<토큰>; HttpOnly=False; SameSite=Lax; ...`

#### CSRF 토큰 검증

**POST /admin/specs** (또는 다른 변경 메서드):
- 요청 헤더 (방법 1): `X-CSRF-Token: <토큰>`
- 요청 바디 (방법 2, form): `csrf_token=<토큰>`
- 쿠키: `csrf_token=<토큰>` (자동 검증)

**응답 (403 Forbidden)** — CSRF 토큰 누락/불일치:
```json
{
  "detail": "CSRF token missing or invalid"
}
```

---

### 3.5 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `CORS_ALLOWED_ORIGINS` | (선택) | 쉼표 구분 CORS 허용 origins |
| `SECURE_COOKIE` | `true` | HTTPS only 쿠키 (로컬 개발: false) |

---

### 3.6 구현 체크리스트

- [ ] csrf_middleware.py 구현 (토큰 생성/검증)
- [ ] CSRFMiddleware를 main.py에 등록 (CORSMiddleware 이전)
- [ ] _get_allowed_origins 함수 구현
- [ ] CORSMiddleware 설정 업데이트
- [ ] app/config.py에 secure_cookie, allowed_origins 설정 추가
- [ ] 모든 set_cookie 호출에 samesite="lax" 추가
- [ ] 템플릿에서 CSRF 토큰 입력 필드 추가 (또는 커스텀 태그)
- [ ] 프론트엔드 JS에서 X-CSRF-Token 헤더 자동 포함 로직 추가
- [ ] MCP 경로 CSRF 면제 확인
- [ ] config.example.yaml에 CORS 예시 추가

---

### 3.7 테스트 시나리오

#### 정상 케이스
1. GET /admin → CSRF 토큰 쿠키 생성
   - 예상: Set-Cookie: csrf_token=...
2. POST /admin/specs (valid CSRF token) → 성공
   - 예상: 200 OK, 리소스 생성
3. 다른 도메인에서 폼 제출 시도
   - 예상: 403 Forbidden (CSRF 토큰 불일치)

#### 엣지 케이스
1. CSRF 토큰 없이 POST 요청
   - 예상: 403 "CSRF token missing"
2. 만료된 CSRF 토큰으로 POST
   - 예상: 403 "CSRF token validation failed"
3. MCP POST 요청 (Bearer 토큰 기반)
   - 예상: 200 OK (CSRF 검증 우회)

#### 실패 케이스
1. 다른 탭에서 CSRF 토큰 재사용 (정상)
   - 예상: 200 OK (같은 쿠키이므로 유효)
2. 자동으로 생성된 토큰 vs 폼 입력 값 불일치
   - 예상: 403 Forbidden

---

### 3.8 위험 및 완화 전략

| 위험 | 완화 방법 |
|------|----------|
| CSRF 토큰 탈취 | HttpOnly=False (하지만 XSS 방지로 보호) |
| 토큰 만료 시간이 너무 길면 노출 시간 증가 | 24시간으로 제한, GET 요청시마다 갱신 |
| SameSite=Lax는 top-level navigation 허용 | Lax = 폼 제출 허용, Strict 옵션으로 더 강화 가능 |
| CORS 화이트리스트가 너무 넓으면 효과 감소 | 환경별로 명시적 설정, 와일드카드 금지 |

---

---

## 종합 우선순위 및 구현 순서

**순서**:
1. **API 토큰 만료 검증** (기술적으로 가장 간단, 의존성 최소)
2. **Admin 패스워드 강제 변경** (DB 스키마 + UI)
3. **CORS/CSRF 방어** (미들웨어 추가, 템플릿 수정)

**병렬 작업 가능**: 각 항목의 파일 변경이 겹치지 않으므로 @coder가 3개를 동시에 진행 가능.

---

**문서 작성일**: 2026-03-30
**담당자**: @senior (설계), @coder (구현), @tester (검증)
