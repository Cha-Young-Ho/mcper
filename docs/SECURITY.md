# docs/SECURITY.md — 보안 정책

---

## 위협 모델

| 위협 | 현재 대응 | 상태 |
|------|----------|------|
| 비인가 접근 | HTTP Basic (어드민), Host/Origin 검증 (MCP), JWT (선택) | ✅ |
| SQL Injection | SQLAlchemy ORM 파라미터화 + Pydantic 검증 | ✅ |
| CSRF | CSRF 미들웨어 (POST/PUT/DELETE), X-CSRF-Token | ✅ |
| 비밀번호 약점 | 첫 기동 시 강제 변경, 12자+특수문자 정책, bcrypt | ✅ |
| API 토큰 탈취 | JWT expires_at 검증, ExpiredSignatureError 분리 | ✅ |
| 데이터 유출 | Host/Origin 검증, TLS 필수, 저장소 암호화 미구현 | ⚠️ |

---

## 보안 설정

### 필수 환경 변수

```bash
ADMIN_PASSWORD="$(openssl rand -base64 16)"     # 기본값 "changeme" 금지
AUTH_SECRET_KEY="$(openssl rand -base64 32)"    # JWT 시크릿
MCP_ALLOWED_HOSTS="my-alb.example.com:443"      # Host 화이트리스트
MCP_BYPASS_TRANSPORT_GATE=0                     # 0=검증 활성화
DATABASE_URL="postgresql://user:pass@db/mcpdb"  # 강한 암호 필수
```

### HTTP 보안 헤더

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Strict-Transport-Security: max-age=31536000
Content-Security-Policy: default-src 'self'
CORS: allow_origins=["https://cursor.sh"] (프로덕션)
```

---

## 인증 계층

| 방식 | 대상 | 활성화 |
|------|------|--------|
| HTTP Basic | 어드민 UI | 항상 |
| JWT 토큰 | API | `MCPER_AUTH_ENABLED=true` |
| OAuth2 | Google/GitHub | 클라이언트 ID 설정 시 |

### MCP Host 검증

```
클라이언트 → POST /mcp (Host: x)
  → mcp_host_gate 미들웨어
  → DB mcp_allowed_hosts 조회
  → 발견 ✅ 도구 실행 / 미발견 ❌ 421
```

등록: env `MCP_ALLOWED_HOSTS` (시작 시) 또는 DB INSERT (런타임)

---

## 암호화

- **비밀번호**: bcrypt (rounds=12, ~200ms/hash)
- **API 토큰**: `secrets.token_urlsafe(32)`
- **전송**: TLS/HTTPS (ALB 또는 nginx)
- **저장소**: 미구현 (향후 과제)

---

## 감시 & 로깅

보안 이벤트 로깅 대상: `admin_login_attempt`, `csrf_token_invalid`, `mcp_host_rejected`

```
로그 보존: 로컬 30일, CloudWatch 90일, S3 1년
민감정보 마스킹: ADMIN_PASSWORD, AUTH_SECRET_KEY, OPENAI_API_KEY → "***"
```

---

## 배포 체크리스트

**배포 전**: `ADMIN_PASSWORD` 변경, `AUTH_SECRET_KEY` 생성, `MCP_ALLOWED_HOSTS` 설정, HTTPS 인증서, DB 백업

**배포 후**: `/health` 확인, `/admin` 로그인, MCP 호출 성공, 로그에 민감정보 없음

**월 1회**: 의존성 보안 업데이트, 로그 분석, 접근 로그 검토, 백업 복구 테스트

---

## 관련 문서

- **docs/RELIABILITY.md** — 배포 체크리스트
- **ARCHITECTURE.md** — 기술 구조
