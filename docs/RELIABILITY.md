# docs/RELIABILITY.md — 배포 및 신뢰성 체크리스트

프로덕션 배포, 성능 모니터링, 장애 대응 가이드.

---

## 배포 전 체크리스트

### 보안

- [ ] **Admin 패스워드 변경**
  ```bash
  export ADMIN_PASSWORD="$(openssl rand -base64 16)"
  # docker compose up 또는 env 업데이트
  ```

- [ ] **JWT Secret 설정** (인증 활성화 시)
  ```bash
  export AUTH_SECRET_KEY="$(openssl rand -base64 32)"
  ```

- [ ] **MCP Host 허용 목록 설정**
  ```
  env: MCP_ALLOWED_HOSTS=my-alb.region.elb.amazonaws.com:443
  또는 DB: INSERT INTO mcp_allowed_hosts (host) VALUES (...)
  ```

- [ ] **HTTPS 활성화**
  - ALB: HTTPS 리스너 + 자체 서명 인증서 → ACM
  - nginx: `ssl_certificate`, `ssl_protocols TLSv1.2+`

- [ ] **환경 변수 확인**
  ```bash
  # 필수
  DATABASE_URL (Postgres)
  ADMIN_USER / ADMIN_PASSWORD

  # 선택
  CELERY_BROKER_URL (Redis)
  LOCAL_EMBEDDING_MODEL (또는 OpenAI API)
  ```

### 데이터베이스

- [ ] **Postgres 버전 확인**
  ```bash
  psql $DATABASE_URL -c "SELECT version();"
  # 권장: PostgreSQL 14+
  ```

- [ ] **pgvector 확장 설치**
  ```bash
  psql $DATABASE_URL -c "CREATE EXTENSION IF NOT EXISTS vector;"
  ```

- [ ] **스키마 마이그레이션 완료**
  ```bash
  # 앱 기동 시 init_db() 자동 실행
  docker compose up web  # 또는 uvicorn main:app
  ```

- [ ] **백업 정책 설정**
  ```bash
  # AWS RDS: 자동 스냅샷 (최소 7일)
  # 온프레미스: pg_dump 일일 백업
  ```

- [ ] **Connection Pool 설정**
  ```ini
  [database]
  pool_size: 20
  max_overflow: 10
  pool_recycle: 3600
  ```

### 캐시 & 큐

- [ ] **Redis 접근성 확인**
  ```bash
  redis-cli -h redis_host PING
  # 응답: PONG
  ```

- [ ] **Celery 워커 실행**
  ```bash
  celery -A app.worker.celery_app worker -l info --concurrency=4
  ```

- [ ] **큐 깊이 모니터링**
  ```bash
  GET /health/rag
  # 응답: {"queue_depth": 5, "processing": 2}
  ```

### 임베딩

- [ ] **임베딩 백엔드 선택**
  - 로컬: `LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2`
  - OpenAI: `OPENAI_API_KEY=sk-...`
  - Bedrock: AWS IAM 역할

- [ ] **차원 일치 확인**
  ```
  모델 출력 차원 == EMBEDDING_DIM

  # MiniLM: 384
  # text-embedding-3-small: 1536
  ```

- [ ] **시드 데이터 색인**
  ```bash
  # 첫 기동
  docker compose up web
  # → 예시 기획서 1개 자동 색인
  ```

### 모니터링

- [ ] **헬스체크 엔드포인트 설정**
  ```bash
  GET /health
  # 응답: {"status": "ok", "db": true, "redis": true}
  ```

- [ ] **로깅 수준 설정**
  ```
  LOGLEVEL=info (프로덕션)
  LOGLEVEL=debug (스테이징)
  ```

- [ ] **구조화 로깅 활성화**
  ```python
  # 자동: JSON 형식 (에이전트·모니터링)
  logger.info("event", extra={"task_id": "...", "duration_ms": 150})
  ```

---

## 성능 기준선

### 응답 시간 (p95)

| 엔드포인트 | 목표 | 예시 |
|-----------|------|------|
| `GET /health` | < 50ms | 데이터베이스 ping |
| `POST /mcp` (검색) | < 500ms | 100K 벡터, FTS |
| `GET /api/specs/{id}` | < 100ms | 메타데이터 조회 |
| `POST /admin/rules` | < 200ms | 규칙 발행 |

### 리소스 사용률

| 메트릭 | 경고 | 심각 |
|--------|------|------|
| CPU (web) | > 70% | > 90% |
| Memory (web) | > 1.5GB | > 2GB |
| DB 연결 | > 15/20 | > 18/20 |
| 큐 깊이 | > 100 | > 1000 |
| 디스크 사용률 | > 80% | > 95% |

---

## 모니터링 설정

### CloudWatch (AWS)

```yaml
# app/logging_config.py (자동)
handlers:
  cloudwatch:
    class: watchtower.CloudWatchLogHandler
    log_group: /aws/ecs/spec-mcp
    stream_name: web  # 또는 worker
```

메트릭:
```
- ErrorCount (5분 >= 5개)
- Latency p95 (> 1000ms)
- CPUUtilization (> 80%)
```

### Prometheus (온프레미스)

```yaml
# docker-compose에 추가
prometheus:
  image: prom/prometheus
  volumes:
    - ./infra/prometheus.yml:/etc/prometheus/prometheus.yml
  ports: ["9090:9090"]
```

쿼리:
```promql
rate(mcper_mcp_tool_calls_total[5m])
histogram_quantile(0.95, mcper_http_request_duration_seconds)
```

### 대시보드

- **Datadog**: Real-time 모니터링
- **Grafana**: 온프레미스 시계열
- **CloudWatch Insights**: 쿼리 기반 분석

---

## 장애 대응

### 증상별 대응

#### 1. MCP "Invalid Host" (421)

```
증상: Cursor에서 /mcp 요청 시 421 응답

원인:
- mcp_allowed_hosts에 클라이언트 Host 미등록
- MCP_ALLOWED_HOSTS env 수정 후 재기동 미완료

해결:
1. 클라이언트 Host 확인
   curl -i -H "Host: ???" http://localhost:8001/health
2. DB 확인
   SELECT * FROM mcp_allowed_hosts
3. env 또는 DB 갱신 후 재기동
   export MCP_ALLOWED_HOSTS="203.0.113.7:8001"
   docker compose up web  # 또는 재기동
```

#### 2. 큐 깊이 증가

```
증상: /health/rag에서 queue_depth > 1000

원인:
- Celery 워커 다운
- 임베딩 모델 느림
- 대량 업로드

해결:
1. 워커 상태 확인
   docker ps | grep worker
   docker logs <worker_id>
2. 워커 재시작
   docker compose restart worker
3. 워커 병렬도 증가
   CELERY_CONCURRENCY=8 docker compose up worker
4. 큐 플러시 (마지막 수단)
   redis-cli FLUSHDB  # 주의: 데이터 손실!
```

#### 3. 데이터베이스 연결 풀 고갈

```
증상: "too many connections" 에러

원인:
- 연결 누수 (finally/context manager 누락)
- 동시 요청 급증

해결:
1. 활성 연결 확인
   psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity;"
2. 유휴 연결 종료
   SELECT pg_terminate_backend(pid)
   WHERE state = 'idle' AND query_start < now() - interval '10 min';
3. 풀 크기 증가
   DATABASE_POOL_SIZE=30 docker compose up web
```

#### 4. OOM (Out of Memory)

```
증상: 컨테이너 재시작, 대시보드 접속 불가

원인:
- 대량 벡터 로드 (메모리 부족)
- 메모리 누수

해결:
1. 메모리 제한 확인
   docker stats <container_id>
2. 컨테이너 메모리 증가 (docker-compose.yml)
   services:
     web:
       mem_limit: 4g  # 기본 1g
3. 재시작
   docker compose up --force-recreate web
```

#### 5. 임베딩 모델 로드 실패

```
증상: 시작 시 "CUDA out of memory" 또는 "model not found"

원인:
- GPU 메모리 부족 (로컬 모델)
- 모델 다운로드 중단

해결:
1. CPU 강제 사용
   LOCAL_EMBEDDING_DEVICE=cpu docker compose up web
2. 더 작은 모델로 변경
   LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
3. 모델 캐시 초기화
   rm -rf ~/.cache/huggingface/
   docker compose up web  # 재다운로드
```

---

## 스케일링 가이드

### 수직 확장 (단일 인스턴스)

```
Stage 1: 기본 설정 (현재)
├─ web: 1 인스턴스 (t3.medium, 2GB)
├─ worker: 1 인스턴스 (t3.medium)
└─ DB: t3.small (1GB, 20 IOPS)

Stage 2: CPU 부하 증가 (트래픽 2배)
├─ web: 1 인스턴스 (t3.large, 4GB) + ALB
├─ worker: 2 인스턴스 (t3.medium) 병렬
└─ DB: t3.medium (4GB, 100 IOPS)

Stage 3: I/O 병목 (벡터 500만+)
├─ web: 2 인스턴스 (t3.large)
├─ worker: 4 인스턴스 (c6i.xlarge, CPU 최적)
└─ DB: r6i.xlarge (32GB, 1000 IOPS, 읽기 복제본)
```

### 수평 확장 (다중 인스턴스)

```yaml
# ECS Fargate + ALB
ecs_service:
  task_definition: spec-mcp-web
  desired_count: 2  # 초기
  auto_scaling:
    min_capacity: 2
    max_capacity: 10
    target_cpu_utilization: 70
    scale_out_cool_down: 300s
    scale_in_cool_down: 600s

# Celery 워커
worker_service:
  desired_count: 4
  auto_scaling:
    # 큐 깊이 기반 (custom metric)
    metric: celery_queue_depth
    target_value: 50
```

---

## 백업 & 복구

### 자동 백업 (RDS)

```
설정: AWS RDS → Automated Backups
- Backup Retention: 30일
- Backup Window: 03:00-04:00 UTC
- 다중 AZ: 활성화 (프로덕션)
```

### 수동 백업

```bash
# PostgreSQL 전체 덤프
pg_dump $DATABASE_URL | gzip > backup_$(date +%Y%m%d).sql.gz

# 복구
gunzip backup_20260330.sql.gz | psql $DATABASE_URL

# 테이블만 백업
pg_dump $DATABASE_URL --table specs > specs_backup.sql
```

### 복구 테스트 (월 1회)

```bash
# 테스트 DB 생성
CREATE DATABASE test_restore;

# 복구 수행
psql test_restore < backup.sql

# 검증
SELECT count(*) FROM specs;  # 행 수 확인
SELECT count(*) FROM spec_chunks;  # 벡터 확인
```

---

## 버전 및 의존성

### Python 버전 (고정)

```
현재: 3.13
호환 범위: 3.13 - 3.14
```

### 주요 의존성

| 패키지 | 용도 | 버전 | 업데이트 |
|--------|------|------|---------|
| fastapi | 웹 프레임워크 | 0.100+ | 부 버전 OK |
| sqlalchemy | ORM | 2.0+ | 마이너 OK |
| pydantic | 검증 | 2.0+ | 마이너 OK |
| celery | 비동기 작업 | 5.3+ | 마이너 주의 |
| psycopg | PostgreSQL 드라이버 | 3.1+ | 패치만 |

### 의존성 업데이트 절차

```bash
# 1. 스테이징에서 테스트
pip install --upgrade fastapi==0.105.0
docker compose up web  # 로그 확인

# 2. 핵심 엔드포인트 테스트
curl http://localhost:8001/health
curl http://localhost:8001/mcp -d '...'

# 3. requirements.txt 갱신
pip freeze > requirements.txt

# 4. 프로덕션 배포
git commit -m "chore: bump fastapi to 0.105.0"
```

---

## 관련 문서

- **ARCHITECTURE.md** — 기술 세부사항
- **docs/SECURITY.md** — 보안 정책
- **docs/DESIGN.md** — 설계 결정
