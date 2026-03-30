# MCPER — Docker Compose 배포 가이드

## 빠른 시작 (로컬 개발)

```bash
cd infra/docker
cp .env.example .env
# .env 수정 (최소: ADMIN_PASSWORD 변경)

# 첫 빌드
docker compose -f docker-compose.yml -f docker-compose.override.yml build

# 실행 (핫리로드 포함)
docker compose -f docker-compose.yml -f docker-compose.override.yml up
```

어드민 UI: http://localhost:8001/admin

---

## 사내(Private Network) 프로덕션 배포

### 1. 환경변수 설정

```bash
cp .env.example .env
```

`.env`에서 반드시 변경:

| 항목 | 설명 |
|------|------|
| `DB_PASSWORD` | PostgreSQL 강력한 비밀번호 |
| `ADMIN_PASSWORD` | Admin UI 접근 비밀번호 |
| `AUTH_SECRET_KEY` | 32바이트 이상 랜덤 문자열 (MCPER_AUTH_ENABLED=true 시) |
| `MCPER_HOST_BIND` | `127.0.0.1` (로컬호스트만 노출, Nginx 앞단 사용) |

비밀 키 생성:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. 빌드 및 실행

```bash
# 이미지 빌드
docker compose -f docker-compose.yml build

# 백그라운드 실행
docker compose -f docker-compose.yml up -d

# 로그 확인
docker compose -f docker-compose.yml logs -f web
```

### 3. 사내 Nginx 리버스 프록시 예시

```nginx
server {
    listen 80;
    server_name mcper.corp.internal;

    # 사내망에서만 접근 허용 (사내 IP 대역 예시)
    allow 10.0.0.0/8;
    allow 192.168.0.0/16;
    deny all;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # MCP SSE 연결 (스트리밍)
    location /mcp {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }
}
```

`MCP_ALLOWED_HOSTS=mcper.corp.internal` 환경변수를 .env에 추가.

### 4. 인증 활성화 (사내 권장)

`.env`에서:
```bash
MCPER_AUTH_ENABLED=true
AUTH_SECRET_KEY=<32자 이상 랜덤>
ADMIN_USER=admin
ADMIN_PASSWORD=<강력한 비밀번호>
```

최초 기동 시 `ADMIN_USER`/`ADMIN_PASSWORD`로 관리자 계정이 자동 생성됩니다.

---

## 이미지 업데이트

```bash
docker compose -f docker-compose.yml build --no-cache
docker compose -f docker-compose.yml up -d
```

## 데이터 백업

```bash
# PostgreSQL 덤프
docker compose -f docker-compose.yml exec db \
  pg_dump -U user mcpdb > backup_$(date +%Y%m%d).sql
```

## 로컬 임베딩 (Ollama)

```bash
docker compose -f docker-compose.yml --profile local-embed up -d
# .env에 EMBEDDING_PROVIDER=localhost, LOCALHOST_EMBEDDING_BASE_URL=http://ollama:11434
```
