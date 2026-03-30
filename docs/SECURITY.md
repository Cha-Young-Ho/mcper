# docs/SECURITY.md — 보안 정책

---

## 위협 모델

### 1. **비인가 접근** (Unauthorized Access)

**위험**: 클라이언트가 다른 사용자의 기획서·규칙 수정

**현재 대어드민**:
- HTTP Basic 인증 (어드민 UI만)
- MCP: Host/Origin 검증 (네트워크 기반)

**개선 계획** (CRITICAL):
- JWT 토큰 (선택적 활성화)
- OAuth2 (Google, GitHub)

---

### 2. **SQL Injection**

**위험**: 악의적 쿼리로 데이터 누출 또는 손상

**대어드민**:
- ✅ SQLAlchemy ORM (파라미터화 쿼리)
- ✅ Pydantic 검증 (입력 타입)

**코드 패턴**:
```python
# ❌ 위험
SELECT * FROM specs WHERE title = '{}' ... .format(user_input)

# ✅ 안전 (우리는 이렇게 함)
from sqlalchemy import select
stmt = select(Spec).where(Spec.title == user_input)
session.execute(stmt)
```

---

### 3. **Cross-Site Request Forgery (CSRF)**

**위험**: 다른 사이트에서 사용자의 브라우저로 악의적 요청 전송

**대어드민**:
- ✅ CSRF 미들웨어 (POST/PUT/DELETE)
- ✅ `Content-Type: application/json` 검증

**구현**:
```python
# app/asgi/csrf_middleware.py
@middleware
async def csrf_middleware(request, call_next):
    if request.method in ("POST", "PUT", "DELETE"):
        token = request.headers.get("X-CSRF-Token")
        if not verify_csrf_token(token):
            return 403
    return await call_next(request)
```

---

### 4. **비밀번호 약점**

**위험**: 기본 패스워드 "changeme" 노출

**현재**:
- ⚠️ 기본값 경고만 (강제 없음)

**CRITICAL 개선**:
- [ ] 첫 기동 시 강제 변경
- [ ] 비밀번호 정책 (최소 12자, 특수문자)
- [ ] 해시: bcrypt (rounds=12)

---

### 5. **API 토큰 만료**

**위험**: 탈취된 토큰이 무기한 유효

**현재**:
- ⚠️ expires_at 검증 미완료

**개선**:
```python
# app/auth/service.py
def is_token_valid(token: str) -> bool:
    payload = jwt.decode(token, SECRET_KEY)
    if datetime.utcnow() > payload.get("expires_at"):
        return False  # 만료됨
    return True
```

---

### 6. **데이터 유출**

**위험**: 기획서 콘텐츠, 규칙, 코드 노드 노출

**보호**:
- ✅ Host/Origin 검증 (MCP)
- ✅ HTTP Basic (어드민)
- ⚠️ 암호화 전송 (TLS/HTTPS) — 배포 필수
- ❌ 저장소 암호화 (미구현)

---

## 보안 설정

### 환경 변수

```bash
# 필수
ADMIN_PASSWORD="$(openssl rand -base64 16)"          # 기본값 금지
AUTH_SECRET_KEY="$(openssl rand -base64 32)"         # JWT 시크릿

# MCP 네트워크
MCP_ALLOWED_HOSTS="my-alb.example.com:443"           # 화이트리스트
MCP_BYPASS_TRANSPORT_GATE=0                          # 기본값 (검증 O)

# 데이터베이스
DATABASE_URL="postgresql://user:pass@db:5432/mcpdb"  # 강한 암호
DATABASE_SSL=require                                 # SSL 강제

# 외부 API
OPENAI_API_KEY="sk-..."                              # 절대 로그에 기록 X
```

### HTTP 헤더

```python
# app/main.py
app.add_middleware(CORSMiddleware,
    allow_origins=["https://cursor.sh"],  # Cursor만
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

# 추가 헤더
response.headers["X-Content-Type-Options"] = "nosniff"      # MIME 스니핑 방지
response.headers["X-Frame-Options"] = "DENY"                # Clickjacking 방지
response.headers["Strict-Transport-Security"] = "max-age=31536000"  # HSTS
response.headers["Content-Security-Policy"] = "default-src 'self'"   # CSP
```

### 파일 권한

```bash
# 설정 파일
chmod 600 config.yaml                    # rw-------
chmod 600 .env                           # rw-------

# 키 파일
chmod 600 /var/lib/mcper/key.pem         # rw-------

# 로그
chmod 640 /var/log/mcper/app.log         # rw-r-----
```

---

## 인증 & 인가

### 1. HTTP Basic (어드민 UI)

**활성화**: 항상

**검증**:
```python
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

@app.get("/admin")
def admin(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != ADMIN_USER:
        raise HTTPException(401, "Invalid username")
    if not verify_password(credentials.password, ADMIN_PASSWORD_HASH):
        raise HTTPException(401, "Invalid password")
    return admin_dashboard()
```

**기본값**:
- 사용자: `admin`
- 암호: `changeme` (⚠️ 반드시 변경)

### 2. JWT 토큰 (선택)

**활성화**: `MCPER_AUTH_ENABLED=true`

**발급**:
```python
from datetime import datetime, timedelta
import jwt

payload = {
    "sub": user.id,
    "exp": datetime.utcnow() + timedelta(minutes=30),
    "iat": datetime.utcnow(),
}
token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
```

**검증**:
```python
from fastapi.security import HTTPBearer

bearer = HTTPBearer()

@app.get("/api/protected")
def protected(credentials = Depends(bearer)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if datetime.fromtimestamp(payload["exp"]) < datetime.utcnow():
            raise HTTPException(401, "Token expired")
        return {"message": "OK"}
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
```

### 3. OAuth2 (선택)

**지원**: Google, GitHub

**클라이언트 등록**:
1. Google Cloud Console: OAuth 2.0 클라이언트 ID 생성
2. GitHub Settings: OAuth App 등록
3. 환경변수 설정:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GITHUB_CLIENT_ID=...
   GITHUB_CLIENT_SECRET=...
   ```

**흐름**:
```
사용자 → "Sign in with Google"
  ↓ (리다이렉트)
Google 로그인 페이지
  ↓ (인증 완료)
app/auth/oauth.py (callback)
  ↓ (JWT 토큰 발급)
클라이언트 ← 토큰 + 쿠키
```

---

## MCP Host 검증

### 화이트리스트 설정

**환경변수 (시작 시)**:
```bash
export MCP_ALLOWED_HOSTS="mcp.example.com:443,203.0.113.7:8001"
```

**데이터베이스 (런타임)**:
```sql
INSERT INTO mcp_allowed_hosts (host, added_by, added_at)
VALUES ('mcp.example.com:443', 'admin', now());
```

**자동 등록 (EC2)**:
```python
# app/services/mcp_auto_hosts.py
if MCP_AUTO_EC2_PUBLIC_IP:
    public_ip = get_ec2_public_ip()  # IMDS
    public_host = f"{public_ip}:{MCP_EXTERNAL_PORT}"
    db.insert(public_host)  # mcp_allowed_hosts
```

### 검증 흐름

```
클라이언트 → POST /mcp (Host: mcp.example.com:443)
  ↓
mcp_host_gate 미들웨어
  ↓
SELECT * FROM mcp_allowed_hosts WHERE host = 'mcp.example.com:443'
  ├─ 발견됨 ✅ → 도구 실행
  └─ 미발견 ❌ → 421 Invalid Host
```

---

## 암호화

### 저장소 암호화

**비밀번호**:
```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)
```

설정:
```python
# rounds=12 (기본)
# cost = 2^12 = 4096 반복
# 시간: ~200ms/비밀번호 (해킹 어렵게)
```

**API 토큰**:
```python
token = secrets.token_urlsafe(32)  # 암호로 안전한 난수
```

### 전송 암호화

**TLS/HTTPS** (필수):
```
어드민 UI, API, MCP 모두
└─ ALB (HTTPS 리스너) → 자체 서명 인증서
└─ 또는 nginx (ssl_certificate, ssl_protocols TLSv1.3)
```

**사내 네트워크**:
```
MCP_BYPASS_TRANSPORT_GATE=0 (기본)
└─ Host 검증만
└─ 네트워크는 VPN/SG로 보호
```

---

## 감시 & 로깅

### 보안 이벤트 로깅

```python
logger.info("admin_login_attempt",
    extra={
        "user": username,
        "ip": request.client.host,
        "result": "success" | "failure",
        "timestamp": datetime.utcnow().isoformat(),
    }
)

logger.warning("csrf_token_invalid",
    extra={
        "endpoint": request.url.path,
        "method": request.method,
        "ip": request.client.host,
    }
)

logger.critical("mcp_host_rejected",
    extra={
        "host": request.headers.get("host"),
        "origin": request.headers.get("origin"),
        "allowed_hosts": list(db.get_mcp_hosts()),
    }
)
```

### 로그 보존

```
- 로컬 파일: 30일 (rotate daily)
- CloudWatch: 90일
- S3 아카이브: 1년 (Athena 쿼리)
```

### 로그 마스킹

```python
# 민감정보 마스킹
def mask_sensitive(data):
    data["ADMIN_PASSWORD"] = "***"
    data["AUTH_SECRET_KEY"] = "***"
    data["OPENAI_API_KEY"] = "sk-***"
    return data

logger.info("config_loaded", extra=mask_sensitive(config.dict()))
```

---

## 배포 체크리스트

### 배포 전

- [ ] `ADMIN_PASSWORD` 변경 (기본값 ≠ "changeme")
- [ ] `AUTH_SECRET_KEY` 생성 (32바이트 무작위)
- [ ] `MCP_ALLOWED_HOSTS` 화이트리스트 설정
- [ ] HTTPS 인증서 설치 (자체 서명 → ACM)
- [ ] 데이터베이스 백업 테스트
- [ ] 보안 그룹/방화벽 규칙 검토
  - 포트 8000: 내부만
  - 포트 5432: 내부만
  - 포트 6379: 내부만

### 배포 후

- [ ] `/health` 헬스체크 확인
- [ ] `/admin` 로그인 성공
- [ ] MCP 도구 호출 성공
- [ ] 로그에 민감정보 없음 확인
- [ ] TLS 인증서 만료 날짜 확인

### 정기 점검 (월 1회)

- [ ] 의존성 보안 업데이트 확인
  ```bash
  pip list --outdated
  pip install -U -r requirements.txt
  ```
- [ ] 로그 분석 (에러, 경고)
- [ ] 접근 로그 검토 (비정상 접근)
- [ ] 백업 복구 테스트

---

## 관련 문서

- **RELIABILITY.md** — 배포 체크리스트
- **ARCHITECTURE.md** — 기술 세부사항
- **docs/DESIGN.md** — 설계 결정
