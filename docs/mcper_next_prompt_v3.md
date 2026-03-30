# mcper 리팩토링 전체 작업 지시서 v3
# (인프라 중립 + 로그인 기능 + 최신 버전 고정)

> **이 문서를 읽는 AI에게**
> - 전체를 읽기 전에 어떤 파일도 수정하지 말 것
> - 각 섹션은 우선순위 순서대로 진행, 완료마다 사용자 확인
> - 파일 수정 전 반드시 현재 파일을 먼저 읽고 변경 전/후를 보여줄 것
> - 이 프롬프트 자체가 곧 설계 문서이므로 코드 생성 전 한 번 더 검토할 것

---

## 0. 저장소 및 현재 상태

```
GitHub  : https://github.com/Cha-Young-Ho/mcper
브랜치  : fix/streamable_host
Python  : 3.13+
스택    : FastAPI + FastMCP + PostgreSQL(pgvector) + Redis + Celery
기준일  : 2026-03-29 (모든 버전은 이 날짜 기준 최신으로 고정)
```

---

## 1. 확정 라이브러리 버전 (2026-03-29 기준 최신)

### 1-A. requirements.txt — 전면 교체

```text
# ── Core Web Framework ─────────────────────────────────────────
fastapi==0.135.2
uvicorn[standard]==0.42.0
python-multipart==0.0.22
jinja2==3.1.6

# ── MCP ────────────────────────────────────────────────────────
# transport_security 파라미터 필수 (미만이면 원격 MCP 421 발생)
mcp==1.26.0

# ── Data / Validation ──────────────────────────────────────────
pydantic==2.12.5
pydantic-settings==2.13.1
pyyaml==6.0.3

# ── Database ───────────────────────────────────────────────────
sqlalchemy==2.0.48
psycopg2-binary==2.9.11
pgvector==0.4.2
alembic==1.18.4

# ── Task Queue ─────────────────────────────────────────────────
celery[redis]==5.6.3
redis==7.4.0

# ── Embedding ──────────────────────────────────────────────────
sentence-transformers==5.3.0
boto3==1.42.78          # Bedrock 백엔드 (opt-in)

# ── HTTP Client ────────────────────────────────────────────────
httpx==0.28.1

# ── Auth (MCPER_AUTH_ENABLED=true 시 사용) ─────────────────────
python-jose[cryptography]==3.5.0   # JWT
passlib[bcrypt]==1.7.4             # 패스워드 해싱
bcrypt==5.0.0
authlib==1.6.9                     # OAuth2 (Google, GitHub SSO)
itsdangerous==2.2.0                # 세션 서명

# ── Optional: Document Parsing (MCPER_DOC_PARSE_ENABLED=true) ──
# pdfminer.six==20221105   # PDF 파싱
# python-docx==1.1.2       # DOCX 파싱
# beautifulsoup4==4.13.4   # URL fetch 텍스트 추출
```

**주의사항:**
- `torch`는 Dockerfile에서 CPU 전용 인덱스로 먼저 설치 (CUDA 방지)
- `pdfminer.six`, `python-docx`, `beautifulsoup4`는 기본 미설치, 선택적 활성화
- `boto3`는 requirements에 포함하되, Bedrock provider 미사용 시 실행 비용 없음

### 1-B. Docker 이미지 버전 고정 (2026-03-29 기준)

```yaml
# 사용할 이미지 버전 (절대 latest 금지)
python       : python:3.13.2-slim
postgresql   : pgvector/pgvector:pg17      # pgvector 공식 이미지 (PostgreSQL 17 포함)
redis        : redis:7.4.2-alpine
uv           : ghcr.io/astral-sh/uv:0.10.12  # 현재 Dockerfile에 이미 있음
```

---

## 2. 인프라 중립 설계 원칙

### 2-A. 핵심 원칙

```
애플리케이션 코드(app/)는 배포 환경을 전혀 알지 못해야 한다.
EC2 단일 서버든, ECS든, Kubernetes든, Railway든 동일한 코드가 동작해야 한다.
배포 환경 전용 파일은 모두 infra/ 디렉터리에 격리한다.
```

### 2-B. infra/ 디렉터리 구조 (신규 생성)

```
infra/
  docker/                        ← Docker Compose 기반 배포
    docker-compose.yml           ← 프로덕션용 (볼륨 마운트, 핫리로드 없음)
    docker-compose.override.yml  ← 개발용 (볼륨 마운트 + 핫리로드 추가)
    .env.example                 ← 환경변수 템플릿
    README.md                    ← Docker 배포 가이드
  kubernetes/                    ← Kubernetes 기반 배포
    namespace.yaml
    configmap.yaml
    secret.yaml.example          ← 실제 secret은 .gitignore
    web-deployment.yaml          ← MCP Web Pod (MCPER_ADMIN_ENABLED=false)
    admin-deployment.yaml        ← Admin UI Pod (MCPER_ADMIN_ENABLED=true, replicas:1)
    worker-deployment.yaml       ← Celery Worker Pod
    service.yaml
    ingress.yaml
    hpa.yaml
    README.md                    ← Kubernetes 배포 가이드
  scripts/
    healthcheck.sh               ← 배포 환경 무관 헬스체크 스크립트
    migrate.sh                   ← DB 마이그레이션 실행 스크립트
```

**기존 `docker/` 디렉터리 처리:**
- `docker/Dockerfile` → 루트 레벨 `Dockerfile`로 이동 (환경 무관 빌드 파일)
- `docker/docker-compose.yml` → `infra/docker/docker-compose.yml`로 이동
- `docker/` 디렉터리 제거

### 2-C. 환경변수 설계 — 모든 배포 환경 공통

앱이 읽는 환경변수는 배포 환경과 무관하게 동일:

```bash
# ── 필수 ────────────────────────────────────────────
DATABASE_URL=postgresql://user:password@host:5432/mcpdb
ADMIN_USER=admin
ADMIN_PASSWORD=           # 반드시 설정. 미설정 시 startup에서 ERROR 로그 + 기동 계속

# ── 선택: Celery (없으면 동기 인덱싱으로 폴백) ──────
CELERY_BROKER_URL=redis://host:6379/0
CELERY_RESULT_BACKEND=redis://host:6379/0

# ── 선택: 임베딩 ────────────────────────────────────
EMBEDDING_PROVIDER=local              # local | openai | localhost | bedrock
EMBEDDING_DIM=384
LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
# OPENAI_API_KEY=
# BEDROCK_REGION=

# ── 기능 Enable/Disable ─────────────────────────────
MCPER_ADMIN_ENABLED=true              # true/false (기본 true)
MCPER_MCP_ENABLED=true                # true/false (기본 true)
MCPER_AUTH_ENABLED=false              # true/false (기본 false, 섹션 3 참조)
MCPER_DOC_PARSE_ENABLED=false         # true/false (기본 false, PDF/DOCX 파싱)

# ── MCP 보안 ────────────────────────────────────────
MCP_BYPASS_TRANSPORT_GATE=false       # true면 Host/Origin 검사 생략 (개발용)
MCP_ALLOWED_HOSTS=                    # 쉼표 구분 허용 Host 목록
MCP_AUTO_EC2_PUBLIC_IP=true           # EC2 IMDS 자동 등록

# ── 로그 ────────────────────────────────────────────
LOG_FORMAT=text                       # text | json
LOG_LEVEL=INFO

# ── 인증 (MCPER_AUTH_ENABLED=true 시 필수) ──────────
AUTH_SECRET_KEY=                      # JWT 서명 키 (랜덤 32바이트 이상)
AUTH_TOKEN_EXPIRE_MINUTES=1440        # 기본 24시간
# AUTH_GOOGLE_CLIENT_ID=              # Google OAuth (선택)
# AUTH_GOOGLE_CLIENT_SECRET=
# AUTH_GITHUB_CLIENT_ID=              # GitHub OAuth (선택)
# AUTH_GITHUB_CLIENT_SECRET=
```

---

## 3. 로그인 기능 (MCPER_AUTH_ENABLED)

### 3-A. 설계 원칙

```
MCPER_AUTH_ENABLED=false (기본값)
  → 현재와 동일. HTTP Basic Auth로만 어드민 접근.
  → MCP 엔드포인트 인증 없음.
  → 오픈소스 최초 설치자가 바로 쓸 수 있는 상태.

MCPER_AUTH_ENABLED=true
  → JWT 기반 세션 인증 활성화.
  → 어드민 UI: 로그인 페이지 → JWT 쿠키 → 이후 쿠키 검증.
  → MCP 엔드포인트: Bearer 토큰 또는 API 키 검증.
  → Google/GitHub OAuth는 추가 설정 시 활성화 (없으면 로컬 ID/PW만).
```

### 3-B. 신규 파일 목록

```
app/
  auth/                              ← 신규 디렉터리
    __init__.py
    config.py                        ← AuthSettings (MCPER_AUTH_ENABLED 등)
    models.py                        ← User ORM (auth_users 테이블)
    schemas.py                       ← LoginRequest, TokenResponse Pydantic 모델
    service.py                       ← 로그인, 토큰 발급, 검증 로직
    dependencies.py                  ← FastAPI Depends: get_current_user, require_auth
    router.py                        ← /auth/login, /auth/logout, /auth/me
    oauth.py                         ← Google/GitHub OAuth 콜백 (opt-in)
  db/
    auth_models.py                   ← User, ApiKey ORM 모델 (신규)
  templates/
    auth/
      login.html                     ← 로그인 페이지 (신규)
      login_oauth.html               ← OAuth 버튼 포함 (신규)
```

### 3-C. auth_models.py 스펙

```python
# app/db/auth_models.py

class User(Base):
    __tablename__ = "mcper_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(256), unique=True, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # OAuth 전용 유저는 hashed_password=None
    oauth_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    oauth_sub: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(Base):
    """MCP 클라이언트가 Bearer 토큰으로 사용하는 API 키."""
    __tablename__ = "mcper_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("mcper_users.id", ondelete="CASCADE"))
    key_hash: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)   # 키 이름 (예: "Cursor laptop")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

### 3-D. auth/service.py 핵심 로직

```python
# app/auth/service.py

from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=1440))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.auth.secret_key, algorithm="HS256")

def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.auth.secret_key, algorithms=["HS256"])
```

### 3-E. auth/dependencies.py — FastAPI Depends

```python
# app/auth/dependencies.py

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os

_auth_enabled = os.environ.get("MCPER_AUTH_ENABLED", "false").lower() in ("1", "true", "yes")

bearer_scheme = HTTPBearer(auto_error=False)

async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """
    MCPER_AUTH_ENABLED=false → 항상 None 반환 (인증 생략).
    MCPER_AUTH_ENABLED=true → JWT 또는 API 키 검증.
    """
    if not _auth_enabled:
        return None
    # JWT 쿠키 우선 확인
    token = request.cookies.get("mcper_token")
    # 없으면 Bearer 헤더
    if not token and credentials:
        token = credentials.credentials
    if not token:
        return None
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            return None
        return db.get(User, int(user_id))
    except JWTError:
        return None


async def require_admin_user(
    user: User | None = Depends(get_current_user_optional),
    # fallback: HTTP Basic (MCPER_AUTH_ENABLED=false일 때)
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str:
    """
    AUTH_ENABLED=false → 기존 HTTP Basic 방식.
    AUTH_ENABLED=true  → JWT 세션 방식, is_admin=True 필요.
    """
    if not _auth_enabled:
        # 기존 HTTP Basic 로직 그대로
        return _check_basic_auth(credentials)
    if user is None or not user.is_admin:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user.username
```

### 3-F. auth/router.py 엔드포인트

```python
# app/auth/router.py
router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/login")
def login_page(request: Request):
    """로그인 폼 페이지. MCPER_AUTH_ENABLED=false면 /admin으로 리다이렉트."""
    if not _auth_enabled:
        return RedirectResponse("/admin")
    # Google/GitHub OAuth 버튼은 설정된 경우만 표시
    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "google_enabled": bool(settings.auth.google_client_id),
        "github_enabled": bool(settings.auth.github_client_id),
    })

@router.post("/login")
def login_submit(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == username))
    if not user or not verify_password(password, user.hashed_password or ""):
        raise HTTPException(400, "Invalid credentials")
    token = create_access_token({"sub": str(user.id)})
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie("mcper_token", token, httponly=True, samesite="lax")
    return response

@router.get("/logout")
def logout():
    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie("mcper_token")
    return response

@router.get("/me")
def me(user: User = Depends(require_admin_user)):
    return {"username": user.username, "email": user.email, "is_admin": user.is_admin}

# API 키 관리 (어드민 전용)
@router.post("/api-keys")
def create_api_key(name: str = Form(...), user=Depends(require_admin_user), db=Depends(get_db)):
    """새 API 키 발급. 원본 키는 이 응답에서 한 번만 보여줌."""
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    db.add(ApiKey(user_id=user.id, key_hash=key_hash, name=name))
    db.commit()
    return {"key": raw_key, "name": name}  # raw_key: 한 번만 노출

@router.get("/api-keys")
def list_api_keys(user=Depends(require_admin_user), db=Depends(get_db)):
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id)).all()
    return [{"id": k.id, "name": k.name, "created_at": k.created_at} for k in keys]

@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: int, user=Depends(require_admin_user), db=Depends(get_db)):
    db.execute(delete(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id))
    db.commit()
    return {"ok": True}
```

### 3-G. OAuth 콜백 (opt-in, auth/oauth.py)

```python
# app/auth/oauth.py
# Google/GitHub OAuth는 AUTH_GOOGLE_CLIENT_ID가 설정된 경우에만 라우터 등록

@router.get("/oauth/google/callback")
async def google_callback(code: str, db: Session = Depends(get_db)):
    """
    Google OAuth 콜백.
    1. code → access_token (Google API)
    2. access_token → user info (email, sub)
    3. DB에 없으면 User 생성 (oauth_provider="google", hashed_password=None)
    4. JWT 발급 → 쿠키 설정 → /admin 리다이렉트
    """
    ...
```

### 3-H. MCP 엔드포인트 인증

```python
# app/asgi/mcp_host_gate.py 수정
# 기존 Host/Origin 검사에 Auth 검사 추가

async def _check_auth(scope, _auth_enabled: bool) -> tuple[bool, int, bytes]:
    if not _auth_enabled:
        return True, 0, b""
    # Authorization: Bearer <token> 헤더 확인
    auth_header = _header(scope, b"authorization")
    if not auth_header:
        return False, 401, b"Authorization required"
    if auth_header.startswith("Bearer "):
        token_or_key = auth_header[7:]
        # JWT 검증 시도
        try:
            decode_token(token_or_key)
            return True, 0, b""
        except JWTError:
            pass
        # API 키 검증 시도
        key_hash = hashlib.sha256(token_or_key.encode()).hexdigest()
        # DB에서 key_hash 조회 (cache 사용 권장)
        ...
    return False, 401, b"Invalid token"
```

### 3-I. 초기 관리자 계정 자동 생성

```python
# app/db/seed_defaults.py에 추가
def seed_admin_user_if_empty(session: Session) -> None:
    """
    MCPER_AUTH_ENABLED=true이고 mcper_users가 비어 있으면
    ADMIN_USER / ADMIN_PASSWORD 환경변수로 초기 관리자 계정 생성.
    """
    if not _auth_enabled:
        return
    count = session.scalar(select(func.count()).select_from(User)) or 0
    if count > 0:
        return
    username = os.environ.get("ADMIN_USER", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        logger.warning("MCPER_AUTH_ENABLED=true but ADMIN_PASSWORD is empty. Skipping admin seed.")
        return
    session.add(User(
        username=username,
        hashed_password=hash_password(password),
        is_admin=True,
        is_active=True,
    ))
    session.commit()
    logger.info("Initial admin user '%s' created.", username)
```

### 3-J. config.py에 AuthSettings 추가

```python
# app/config.py 추가

class AuthSettings(BaseModel):
    enabled: bool = False
    secret_key: str = ""
    token_expire_minutes: int = 1440
    # OAuth (optional)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None

class AppSettings(BaseModel):
    ...
    auth: AuthSettings = Field(default_factory=AuthSettings)
```

```yaml
# config.example.yaml에 추가
auth:
  enabled: false                    # true로 변경 시 JWT 인증 활성화
  secret_key: "${AUTH_SECRET_KEY}"  # 반드시 강력한 랜덤 값 설정
  token_expire_minutes: 1440
  # Google OAuth (선택)
  # google_client_id: "${AUTH_GOOGLE_CLIENT_ID}"
  # google_client_secret: "${AUTH_GOOGLE_CLIENT_SECRET}"
  # GitHub OAuth (선택)
  # github_client_id: "${AUTH_GITHUB_CLIENT_ID}"
  # github_client_secret: "${AUTH_GITHUB_CLIENT_SECRET}"
```

---

## 4. infra/docker/ 상세 스펙

### 4-A. Dockerfile (루트로 이동, 수정)

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.13.2-slim

WORKDIR /app
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

# PyTorch CPU 전용 (CUDA 수GB 방지)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

# 빌드 검증
RUN python -c "\
from mcp.server.fastmcp import FastMCP; \
from mcp.server.transport_security import TransportSecuritySettings; \
m=FastMCP('check', transport_security=TransportSecuritySettings(allowed_hosts=['build:1'])); \
assert m.settings.transport_security is not None; \
print('mcp transport_security OK')"

COPY . .

# 프로덕션 기본 CMD (개발 환경은 override.yml에서 --reload 추가)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 4-B. infra/docker/docker-compose.yml (프로덕션용)

```yaml
# infra/docker/docker-compose.yml
# 사용법: docker compose -f infra/docker/docker-compose.yml up -d
name: mcper

services:
  web:
    image: mcper:local
    build:
      context: ../..          # 저장소 루트
      dockerfile: Dockerfile
    ports:
      - "${MCPER_WEB_PORT:-8001}:8000"
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    env_file:
      - .env                  # infra/docker/.env (gitignore)
    environment:
      - MCPER_ADMIN_ENABLED=${MCPER_ADMIN_ENABLED:-true}
      - MCPER_MCP_ENABLED=true
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s

  worker:
    image: mcper:local
    command: celery -A app.worker.celery_app.celery_app worker --loglevel=info
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "celery -A app.worker.celery_app.celery_app inspect ping -d celery@$$HOSTNAME || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  db:
    image: pgvector/pgvector:pg17    # PostgreSQL 17 + pgvector (latest 금지)
    environment:
      POSTGRES_USER: ${DB_USER:-user}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-password}
      POSTGRES_DB: ${DB_NAME:-mcpdb}
    ports:
      - "${DB_PORT:-5433}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-user} -d ${DB_NAME:-mcpdb}"]
      interval: 2s
      timeout: 5s
      retries: 15
      start_period: 10s

  redis:
    image: redis:7.4.2-alpine        # latest 금지
    ports:
      - "${REDIS_PORT:-6380}:6379"
    volumes:
      - redisdata:/data
    restart: unless-stopped

  # Optional: 로컬 임베딩 실험용 (--profile local-embed)
  ollama:
    profiles:
      - local-embed
    image: ollama/ollama:0.6.5       # latest 금지
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama

volumes:
  pgdata:
  redisdata:
  ollama_data:
```

### 4-C. infra/docker/docker-compose.override.yml (개발용)

```yaml
# infra/docker/docker-compose.override.yml
# docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.override.yml up
# 또는: 이 파일을 infra/docker/에서 그냥 up하면 자동 병합

services:
  web:
    volumes:
      - ../..:/app               # 소스 코드 핫리로드용 마운트
    command: >
      uvicorn main:app
      --host 0.0.0.0
      --port 8000
      --reload
      --reload-dir /app
    environment:
      - WATCHFILES_FORCE_POLLING=1   # Docker Desktop 파일 감지용
      - MCPER_ADMIN_ENABLED=true
      - MCP_BYPASS_TRANSPORT_GATE=true
      - LOG_FORMAT=text
      - LOG_LEVEL=DEBUG

  worker:
    volumes:
      - ../..:/app
```

### 4-D. infra/docker/.env.example

```bash
# infra/docker/.env.example
# cp .env.example .env 후 값 변경

# ── Database ────────────────────────────────────
DATABASE_URL=postgresql://user:password@db:5432/mcpdb
DB_USER=user
DB_PASSWORD=password           # 반드시 변경
DB_NAME=mcpdb
DB_PORT=5433

# ── Redis / Celery ───────────────────────────────
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
REDIS_PORT=6380

# ── Admin ────────────────────────────────────────
ADMIN_USER=admin
ADMIN_PASSWORD=                # 반드시 설정 (비워두면 startup 경고)
MCPER_WEB_PORT=8001

# ── Embedding ────────────────────────────────────
EMBEDDING_DIM=384
EMBEDDING_PROVIDER=local
LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# ── Feature Flags ────────────────────────────────
MCPER_ADMIN_ENABLED=true
MCPER_AUTH_ENABLED=false
MCPER_DOC_PARSE_ENABLED=false

# ── Auth (MCPER_AUTH_ENABLED=true 시 필수) ────────
# AUTH_SECRET_KEY=your-random-secret-key-min-32-chars
# AUTH_TOKEN_EXPIRE_MINUTES=1440
# AUTH_GOOGLE_CLIENT_ID=
# AUTH_GOOGLE_CLIENT_SECRET=
# AUTH_GITHUB_CLIENT_ID=
# AUTH_GITHUB_CLIENT_SECRET=

# ── MCP ──────────────────────────────────────────
MCP_BYPASS_TRANSPORT_GATE=false
# MCP_ALLOWED_HOSTS=your-domain.com:443

# ── Logging ──────────────────────────────────────
LOG_FORMAT=text
LOG_LEVEL=INFO
```

---

## 5. infra/kubernetes/ 상세 스펙

### 5-A. configmap.yaml

```yaml
# infra/kubernetes/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcper-config
  namespace: mcper
data:
  EMBEDDING_DIM: "384"
  EMBEDDING_PROVIDER: "local"
  LOCAL_EMBEDDING_MODEL: "sentence-transformers/all-MiniLM-L6-v2"
  MCP_BYPASS_TRANSPORT_GATE: "false"
  MCP_AUTO_EC2_PUBLIC_IP: "false"   # K8s에서는 IMDS 불필요
  LOG_FORMAT: "json"                # K8s에서는 JSON 로그 권장
  LOG_LEVEL: "INFO"
  MCPER_DOC_PARSE_ENABLED: "false"
```

### 5-B. web-deployment.yaml

```yaml
# infra/kubernetes/web-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcper-web
  namespace: mcper
spec:
  replicas: 3
  selector:
    matchLabels:
      app: mcper-web
  template:
    metadata:
      labels:
        app: mcper-web
    spec:
      containers:
      - name: mcper-web
        image: your-registry/mcper:VERSION    # latest 금지, 태그 명시
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: mcper-config
        - secretRef:
            name: mcper-secret
        env:
        - name: MCPER_ADMIN_ENABLED
          value: "false"          # Web Pod: 어드민 OFF
        - name: MCPER_MCP_ENABLED
          value: "true"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 15
          periodSeconds: 10
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health/rag
            port: 8000
          initialDelaySeconds: 20
          periodSeconds: 15
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
```

### 5-C. admin-deployment.yaml

```yaml
# infra/kubernetes/admin-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcper-admin
  namespace: mcper
spec:
  replicas: 1                # 반드시 1
  strategy:
    type: Recreate           # RollingUpdate 아님
  selector:
    matchLabels:
      app: mcper-admin
  template:
    metadata:
      labels:
        app: mcper-admin
    spec:
      containers:
      - name: mcper-admin
        image: your-registry/mcper:VERSION    # web과 동일 이미지
        envFrom:
        - configMapRef:
            name: mcper-config
        - secretRef:
            name: mcper-secret
        env:
        - name: MCPER_ADMIN_ENABLED
          value: "true"
        - name: MCPER_MCP_ENABLED
          value: "false"    # 어드민 Pod에서 MCP 엔드포인트 불필요
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

### 5-D. hpa.yaml

```yaml
# infra/kubernetes/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: mcper-web-hpa
  namespace: mcper
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: mcper-web
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### 5-E. infra/kubernetes/README.md (가이드)

아래 내용 포함:
- 사전 준비 (kubectl, Helm 등)
- secret 생성 방법 (`kubectl create secret generic mcper-secret --from-env-file=.env`)
- 배포 순서 (namespace → configmap → secret → db → redis → worker → web → admin)
- 어드민 접근 방법 (port-forward 또는 Ingress)
- 롤링 업데이트 방법

---

## 6. app/main.py 수정 (인프라 중립 Feature Flag)

```python
# app/main.py 수정사항

import os
import logging

logger = logging.getLogger("mcper.startup")

# ── Feature Flags (환경변수, 어떤 배포 환경에서도 동일) ──────────
_ADMIN_ENABLED = os.environ.get("MCPER_ADMIN_ENABLED", "true").lower() not in ("0", "false", "no")
_MCP_ENABLED   = os.environ.get("MCPER_MCP_ENABLED",   "true").lower() not in ("0", "false", "no")
_AUTH_ENABLED  = os.environ.get("MCPER_AUTH_ENABLED",  "false").lower() in ("1", "true", "yes")


def _validate_startup_config():
    """중요 설정 누락 시 경고/에러 출력."""
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        logger.warning(
            "⚠️  ADMIN_PASSWORD is not set. "
            "Admin UI access requires ADMIN_PASSWORD to be configured."
        )
    elif password == "changeme":
        logger.warning(
            "⚠️  ADMIN_PASSWORD is set to default 'changeme'. "
            "Change this before exposing to any network."
        )
    if _AUTH_ENABLED and not os.environ.get("AUTH_SECRET_KEY", ""):
        logger.error(
            "❌  MCPER_AUTH_ENABLED=true but AUTH_SECRET_KEY is not set. "
            "JWT signing will fail. Please set AUTH_SECRET_KEY."
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _validate_startup_config()
    configure_embedding_backend(settings.embedding)
    configure_logging()          # 신규: LOG_FORMAT=json 지원
    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
        seed_repo_if_empty(db)
        seed_sample_document_if_empty(db)   # 영문 범용 예시
        if _AUTH_ENABLED:
            seed_admin_user_if_empty(db)    # 신규: AUTH 활성화 시 초기 유저
        sync_mcp_allowed_hosts(db, settings)
        mcp_dynamic_asgi.init(settings)
    finally:
        db.close()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="MCPER", description="MCP RAG Server", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# ── 조건부 라우터 등록 ──────────────────────────────────────────
if _ADMIN_ENABLED:
    app.include_router(admin_routes.router)
    logger.info("Admin UI enabled at /admin")

if _AUTH_ENABLED:
    app.include_router(auth_router)          # /auth/login, /auth/logout 등
    logger.info("Authentication enabled")

if _MCP_ENABLED:
    app.mount(MCP_MOUNT_PATH, mcp_dynamic_asgi)
    logger.info("MCP endpoint enabled at %s", MCP_MOUNT_PATH)

# ── Health Endpoints (항상 활성) ────────────────────────────────
@app.get("/health")
def health(): ...

@app.get("/health/rag")
def health_rag(): ...
```

---

## 7. 로깅 설정 신규 파일

```python
# app/logging_config.py (신규)
import logging
import json
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """K8s/CloudWatch/Datadog 친화적 JSON 로그."""
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        return json.dumps(log_data, ensure_ascii=False)


def configure_logging() -> None:
    """
    LOG_FORMAT=json  → JSON 구조화 로그 (K8s, CloudWatch 권장)
    LOG_FORMAT=text  → 기본 텍스트 로그 (개발 환경 기본값)
    LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
    """
    log_format = os.environ.get("LOG_FORMAT", "text").lower()
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        ))

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
```

---

## 8. 기존 v2 지시서에서 유지할 내용 요약

아래 항목들은 이 v3 프롬프트에서 변경 없이 그대로 유지:

**섹션 2 (초기 데이터 업로드)** — 전부 유지
- 어드민 UI 파일 업로드 (`.txt`, `.md`, `.pdf`, `.docx`)
- URL 일괄 등록
- `upload_documents_batch` MCP 툴
- Celery 없을 때 동기 인덱싱 자동 폴백
- `enqueue_or_index_sync()` 함수
- 인덱싱 상태 표시 (✅/⏳/❌)

**섹션 3 (룰 편의성)** — 전부 유지
- 마크다운 렌더링 뷰어 개선
- 버전 diff 뷰
- 롤백 버튼
- Import/Export
- `patch_global_rule` / `patch_app_rule` MCP 툴
- 룰 적용 현황 대시보드
- 룰 내용 검색

**섹션 5 (오픈소스화)** — 전부 유지
- 툴 이름 변경 (`upload_document`, `search_documents` 등) + deprecated alias
- DataSource 어댑터 레이어 (`interface.py`, `registry.py`, `backends/`)
- `get_data` MCP 툴
- 프롬프트 `en/ko` 분리 + `prompt_loader.py`
- 한국어 텍스트 제거 (`seed_documents.py`, `spec_admin.py`, `mcp_tools_docs.py`)

**섹션 6 (테스트)** — 전부 유지
- `tests/conftest.py` + unit/integration 구조
- GitHub Actions CI `.github/workflows/test.yml`
- 핵심 테스트 케이스 (RRF, chunking, document_parser, datasources, upload→search E2E)

**Race condition 수정** — 전부 유지
- `mcp_tool_call_stats` atomic upsert
- `seed_*` advisory lock
- `code_edges` 중복 INSERT 수정

---

## 9. 최종 디렉터리 구조 (목표)

```
mcper/                             (저장소 루트)
  Dockerfile                       ← 루트로 이동 (환경 무관)
  requirements.txt                 ← 버전 전면 고정
  config.example.yaml              ← auth, datasources 섹션 추가
  main.py                          ← uvicorn 진입점
  pyproject.toml
  .python-version                  ← 3.13

  app/
    main.py                        🔧 Feature Flag, logging_config 통합
    mcp_app.py                     🔧 영문 instructions
    config.py                      🔧 AuthSettings, DataSourceSettings 추가
    mcp_dynamic_mount.py           ✅ 유지
    mcp_tools_docs.py              🔧 영문으로 변경
    logging_config.py              🆕 JSON/text 로그 설정

    auth/                          🆕 신규
      __init__.py
      config.py
      models.py  (→ db/auth_models.py 참조)
      schemas.py
      service.py
      dependencies.py
      router.py
      oauth.py

    asgi/
      mcp_host_gate.py             🔧 Auth 검사 추가

    db/
      database.py                  ✅ 유지
      models.py                    ✅ 유지 (Spec)
      rag_models.py                ✅ 유지
      rule_models.py               ✅ 유지
      auth_models.py               🆕 User, ApiKey
      mcp_security.py              ✅ 유지
      mcp_tool_stats.py            🔧 atomic upsert
      seed_defaults.py             🔧 seed_admin_user_if_empty 추가
      seed_documents.py            🔧 영문 예시, locale 지원 (seed_specs.py 교체)

    tools/
      documents.py                 🔧 (specs.py 교체) 새 이름 + deprecated alias
      rag_tools.py                 🔧 새 이름 + deprecated alias
      global_rules.py              🔧 patch_* 툴 추가
      data_tools.py                🆕 get_data() MCP 툴

    services/
      search_hybrid.py             ✅ 유지
      chunking.py                  ✅ 유지
      spec_indexing.py             ✅ 유지
      spec_admin.py                🔧 영문 레이블
      celery_client.py             🔧 enqueue_or_index_sync 추가
      rag_health.py                ✅ 유지
      mcp_auto_hosts.py            ✅ 유지
      mcp_host_validate.py         ✅ 유지
      mcp_transport_config.py      ✅ 유지
      versioned_rules.py           🔧 patch_*, rollback_*, export_* 추가
      document_parser.py           🆕 parse_uploaded_file, fetch_url_as_text

      embeddings/                  ✅ 유지 (완성)
        interface.py, core.py, factory.py, backends/

      datasources/                 🆕 신규
        interface.py
        registry.py
        backends/
          postgres.py
          sheets.py
          notion.py

    prompts/
      prompt_loader.py             🆕 locale 기반 로더
      en/                          🆕 영문 기본값
        global_rule_bootstrap.md
        branch_context.md
        app_target_rule.md
      ko/                          🔧 기존 파일 이동
        global_rule_bootstrap.md
        branch_context.md
        app_target_rule.md

    routers/
      admin.py                     🔧 영문 레이블, 업로드 엔드포인트 추가

    worker/
      celery_app.py                ✅ 유지
      tasks.py                     🔧 code_edges 중복 INSERT 수정

    templates/
      admin/                       🔧 영문 레이블
      auth/                        🆕 login.html, login_oauth.html

    static/admin/                  ✅ 유지

  infra/                           🆕 신규 (기존 docker/ 대체)
    docker/
      docker-compose.yml           🔧 버전 고정, .env 참조
      docker-compose.override.yml  🆕 개발용 (핫리로드, DEBUG)
      .env.example                 🆕 전체 환경변수 템플릿
      README.md                    🆕 Docker 배포 가이드
    kubernetes/
      namespace.yaml
      configmap.yaml
      secret.yaml.example
      web-deployment.yaml
      admin-deployment.yaml
      worker-deployment.yaml
      service.yaml
      ingress.yaml
      hpa.yaml
      README.md

  tests/
    conftest.py
    unit/
      test_chunking.py
      test_rrf.py
      test_prompt_loader.py
      test_document_parser.py
      test_datasources.py
      test_config.py
      test_auth.py                 🆕 JWT, API 키, 인증 비활성화 테스트
    integration/
      test_search_hybrid.py
      test_upload_index.py
      test_rules.py
      test_admin_api.py

  .github/
    workflows/
      test.yml                     🆕 GitHub Actions CI

  docs/
    CONTRIBUTING.md                ✅ 유지
    ARCHITECTURE_MASTER.md         ✅ 유지
    LOCAL_EMBEDDING_FALLBACK.md    ✅ 유지
    integrations/
      google-sheets.md             🆕
      notion.md                    🆕
      custom-datasource.md         🆕
      authentication.md            🆕 Auth 설정 가이드
```

---

## 10. 작업 우선순위 (최종)

```
PRIORITY 1 — 버그/보안/즉시 (현재 코드 문제)
  ① mcp_tool_call_stats atomic upsert       app/services/mcp_tool_stats.py
  ② code_edges 중복 INSERT 수정             app/worker/tasks.py
  ③ seed race condition (advisory lock)      app/db/seed_documents.py
  ④ Startup validation warning              app/main.py

PRIORITY 2 — 인프라 중립화 (배포 환경 분리)
  ⑤ Dockerfile → 루트로 이동               Dockerfile
  ⑥ infra/docker/ 구성                     infra/docker/
  ⑦ infra/kubernetes/ 구성                 infra/kubernetes/
  ⑧ MCPER_ADMIN_ENABLED / MCPER_MCP_ENABLED app/main.py
  ⑨ 이미지 버전 전면 고정                   Dockerfile, infra/docker/

PRIORITY 3 — 오픈소스 공개 필수
  ⑩ requirements.txt 버전 전면 고정         requirements.txt
  ⑪ 툴 이름 변경 + deprecated alias         app/tools/documents.py
  ⑫ 한국어 텍스트 제거                      여러 파일
  ⑬ 프롬프트 en/ko 분리                     app/prompts/
  ⑭ logging_config.py 신규                  app/logging_config.py

PRIORITY 4 — 로그인 기능 (MCPER_AUTH_ENABLED)
  ⑮ AuthSettings, auth_models.py            app/config.py, app/db/auth_models.py
  ⑯ auth/service.py, auth/dependencies.py   app/auth/
  ⑰ auth/router.py (로컬 ID/PW)             app/auth/router.py
  ⑱ 로그인 UI 템플릿                         app/templates/auth/
  ⑲ seed_admin_user_if_empty                app/db/seed_defaults.py
  ⑳ OAuth (Google/GitHub, opt-in)           app/auth/oauth.py

PRIORITY 5 — 사용성 (데이터 업로드)
  ㉑ document_parser.py                      app/services/document_parser.py
  ㉒ 어드민 파일 업로드 엔드포인트            app/routers/admin.py
  ㉓ URL 일괄 등록                           app/routers/admin.py
  ㉔ enqueue_or_index_sync                   app/services/celery_client.py
  ㉕ upload_documents_batch MCP 툴           app/tools/documents.py

PRIORITY 6 — DataSource 어댑터
  ㉖ datasources/interface.py, registry.py   app/services/datasources/
  ㉗ backends/postgres.py                    app/services/datasources/backends/
  ㉘ get_data MCP 툴                         app/tools/data_tools.py
  ㉙ config.yaml datasources 섹션           config.example.yaml

PRIORITY 7 — 룰 편의성
  ㉚ 버전 diff 뷰                            app/routers/admin.py
  ㉛ 롤백 버튼                               app/routers/admin.py
  ㉜ Import/Export                           app/routers/admin.py
  ㉝ patch_global_rule / patch_app_rule      app/tools/global_rules.py

PRIORITY 8 — 테스트
  ㉞ conftest.py + unit tests                tests/
  ㉟ integration tests                       tests/integration/
  ㊱ test_auth.py                            tests/unit/
  ㊲ GitHub Actions CI                       .github/workflows/test.yml
```

---

## 11. 절대 하지 말 것

```
❌ app/ 코드에 K8s, Docker, EC2 등 배포 환경 가정 로직 추가
❌ infra/ 밖에 배포 전용 파일 생성
❌ latest 이미지 태그 사용 (Dockerfile, infra/ 모두)
❌ google-api-python-client 등 opt-in 라이브러리를 requirements.txt 필수로 추가
❌ AUTH_ENABLED=false 상태에서 인증 코드가 실행되는 분기 추가
❌ K8s replicas > 1 Deployment에 MCPER_ADMIN_ENABLED=true
❌ 파일 수정 전 현재 내용 확인 없이 덮어쓰기
❌ 여러 Priority 섹션 동시 수정 (하나씩 확인받으며 진행)
```

---

## 12. 건드리지 말 것 (잘 구현된 것)

```
✅ app/services/embeddings/           임베딩 어댑터 (local/openai/bedrock)
✅ app/services/search_hybrid.py      RRF Hybrid Search
✅ app/asgi/mcp_host_gate.py          Host/Origin 보안 레이어 (auth 추가 제외)
✅ app/services/mcp_transport_config.py  SDK 버전 대응
✅ app/services/versioned_rules.py    룰 버전 관리 (patch/export 추가 제외)
✅ app/db/rule_models.py              룰 ORM
✅ app/services/mcp_auto_hosts.py     EC2 IMDS 자동 등록
✅ app/services/spec_indexing.py      동기 인덱싱
✅ app/worker/tasks.py                Celery 태스크 (edge 중복 수정 제외)
```
