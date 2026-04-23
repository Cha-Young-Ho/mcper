# docs/RELIABILITY.md — 배포 및 신뢰성

---

## 배포 전 체크리스트

### 보안

- [ ] `ADMIN_PASSWORD` 변경 (`openssl rand -base64 16`)
- [ ] `AUTH_SECRET_KEY` 설정 (`openssl rand -base64 32`)
- [ ] `MCP_ALLOWED_HOSTS` 화이트리스트 설정
- [ ] HTTPS 활성화 (ALB 또는 nginx)

### 데이터베이스

- [ ] PostgreSQL 14+ 확인
- [ ] `CREATE EXTENSION IF NOT EXISTS vector;`
- [ ] 백업 정책 (RDS 자동 스냅샷 7일+ 또는 pg_dump 일일)
- [ ] Connection Pool: `pool_size=20, max_overflow=10, pool_recycle=3600`

### 캐시 & 큐

- [ ] Redis PING 확인
- [ ] Celery 워커 실행 (`celery -A app.worker.celery_app worker -l info`)
- [ ] 큐 깊이 모니터링 (`GET /health/rag`)

### 임베딩

- [ ] 백엔드 선택: Local(`all-MiniLM-L6-v2`), OpenAI, 또는 Bedrock
- [ ] 차원 일치 확인 (MiniLM=384, text-embedding-3-small=1536)

### 모니터링

- [ ] `GET /health` 응답 확인
- [ ] 로깅 수준: `LOGLEVEL=info` (프로덕션)

---

## 성능 기준선

| 엔드포인트 | p95 목표 |
|-----------|---------|
| `GET /health` | < 50ms |
| `POST /mcp` (검색) | < 500ms |
| `GET /api/specs/{id}` | < 100ms |
| `POST /admin/rules` | < 200ms |

| 메트릭 | 경고 | 심각 |
|--------|------|------|
| CPU (web) | > 70% | > 90% |
| Memory (web) | > 1.5GB | > 2GB |
| DB 연결 | > 15/20 | > 18/20 |
| 큐 깊이 | > 100 | > 1000 |

---

## 장애 대응

| 증상 | 원인 | 해결 |
|------|------|------|
| MCP 421 "Invalid Host" | `mcp_allowed_hosts`에 미등록 | DB/env에 Host 추가 후 재기동 |
| 큐 깊이 > 1000 | 워커 다운 또는 임베딩 느림 | `docker compose restart worker`, concurrency 증가 |
| "too many connections" | 연결 누수 또는 급증 | `pg_terminate_backend(idle)`, pool_size 증가 |
| OOM 재시작 | 대량 벡터 로드 | `mem_limit: 4g` 설정 |
| 임베딩 로드 실패 | GPU 부족 또는 모델 누락 | `LOCAL_EMBEDDING_DEVICE=cpu` 또는 작은 모델 |

---

## 스케일링

```
Stage 1 (현재): web 1 (t3.medium) + worker 1 + DB t3.small
Stage 2 (2배):  web 1 (t3.large) + ALB + worker 2 + DB t3.medium
Stage 3 (500만+): web 2 (t3.large) + worker 4 (c6i.xlarge) + DB r6i.xlarge + 읽기 복제본
```

---

## 백업 & 복구

- **RDS**: 자동 스냅샷 30일, 다중 AZ (프로덕션)
- **수동**: `pg_dump $DATABASE_URL | gzip > backup_$(date +%Y%m%d).sql.gz`
- **복구 테스트**: 월 1회 (`CREATE DATABASE test_restore; psql test_restore < backup.sql`)

---

## 관련 문서

- **ARCHITECTURE.md** — 기술 세부사항
- **docs/SECURITY.md** — 보안 정책
