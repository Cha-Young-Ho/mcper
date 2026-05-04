# LB 뒤로 배치 (Caddy 제거)

LB(ALB / NLB / CloudFront + LB / Nginx LB 등) 가 TLS 종료를 대신하는 경우의
전환 가이드. **코드 수정 없이 env + compose 변경만으로 전환 가능**.

## 전제

- LB 에 ACM 인증서 또는 외부 TLS 인증서가 붙어 있어 **HTTPS → HTTP** 종료.
- LB 가 `X-Forwarded-Proto: https`, `X-Forwarded-For`, `X-Forwarded-Host`,
  `Host` 헤더를 백엔드로 전달.
- 백엔드 타깃 그룹이 `web` 컨테이너의 8000 포트를 가리킴.

## 전환 체크리스트

### 1) compose 에서 caddy 제거

```bash
cd infra/docker
# 기존 운영 모드
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d

# LB 모드 — caddy 없이 기본 compose 만
docker compose -f docker-compose.yml up -d --build
```

`web` 컨테이너의 8000 포트를 LB 타깃에 등록.

### 2) `.env.local` 수정

```env
# LB 의 공개 도메인
MCPER_PUBLIC_HOST=mcper.example.com
MCPER_PUBLIC_SCHEME=https

# LB Host 헤더 허용 (둘 중 하나 선택)
MCP_BYPASS_TRANSPORT_GATE=1                    # 간단: 앱 레벨 Host 검사 off (SG/LB 에서만 제어)
# 또는
MCP_ALLOWED_HOSTS=mcper.example.com            # 엄격: 허용 Host 화이트리스트

# CSRF 쿠키: HTTPS 통신이므로 Secure 유지
CSRF_COOKIE_SECURE=true

# OAuth redirect base (MCP OAuth 활성 시)
OAUTH_REDIRECT_BASE=https://mcper.example.com

# LB 다중 인스턴스 운용 시 MCP OAuth 세션을 Redis 에 저장
MCPER_SESSION_STORE=redis
REDIS_URL=redis://<redis-endpoint>:6379/0
```

### 3) uvicorn 은 이미 proxy-headers 활성

`Dockerfile` / `docker-compose.yml` 의 CMD 는 **이미**:

```
uvicorn main:app --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips=*
```

`X-Forwarded-Proto: https` 를 신뢰해 `request.url.scheme = "https"` 로 복구.
OAuth redirect · url_for · CSRF Secure 쿠키 모두 정상 동작.

**주의**: `--forwarded-allow-ips=*` 는 컨테이너가 **사설망(VPC/Docker
network)** 에서만 LB 와 통신한다는 전제. 공인 IP 직노출이면 LB 의 내부 IP
대역으로 좁혀야 함.

### 4) LB 설정 요구사항

- **헬스 체크**: `GET /health/live` (의존 없는 liveness, 항상 200)
- **Sticky session** (MCP OAuth 활성 시): `Mcp-Session-Id` 쿠키 기반. 또는
  `MCPER_SESSION_STORE=redis` 로 세션 공유.
- **Streamable HTTP**: SSE 롱 폴링 지원 위해 idle timeout 2분 이상 권장.
  ALB: `idle_timeout.timeout_seconds = 300` (기본 60 → 조정).
- **HTTP/1.1 keep-alive** 허용.

## 코드 수정 필요 여부 (정리)

| 영역 | 변경 필요? | 비고 |
|---|---|---|
| MCP OAuth URL 생성 | ❌ | `MCPER_PUBLIC_*` env 기반 |
| Host 게이트 | ❌ | `MCP_ALLOWED_HOSTS` / `MCP_BYPASS_TRANSPORT_GATE` env |
| `url_for` / 리다이렉트 | ❌ | uvicorn `--proxy-headers` 로 자동 처리 |
| CSRF Secure 쿠키 | ❌ | proxy-headers 적용되면 HTTPS 인식 |
| RBAC / 세션 | ❌ | `MCPER_SESSION_STORE=redis` 토글 |
| 헬스체크 | ❌ | `/health/live`, `/health/ready`, `/health/startup` K8s 표준 |

**결론: 전면 LB 전환 시 Caddy 서비스만 compose 에서 빼고 env 만 바꾸면 됨.**
