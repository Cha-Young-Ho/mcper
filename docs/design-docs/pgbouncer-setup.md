# PgBouncer 도입 설계 (L06)

> 근거 — `docs/audit_2026-04-29.md` L06
> 상태 — 설계 초안 (실 배포는 별도 PR)

---

## 1. 현 상태

### 1.1 구현

- **SQLAlchemy 엔진** — `app/db/database.py:44-49`
  ```python
  engine: Engine = create_engine(
      DATABASE_URL,
      pool_pre_ping=True,
      pool_size=5,
      max_overflow=10,
  )
  ```
- **드라이버** — `psycopg2-binary==2.9.11` (`requirements.txt:18`). 동기 드라이버.
- **ORM 버전** — `sqlalchemy==2.0.48` (`requirements.txt:17`). 2.x 계열.
- **prepared statement 사용** — `grep -rn "prepare_threshold|prepared_statement|compiled_cache" app/`
  → 빈 결과. 앱 코드에서 명시적 prepared statement 사용 없음. SQLAlchemy
  core/ORM 레벨의 컴파일 캐시에만 의존.

### 1.2 문제

- 웹 프로세스 1개 = 커넥션 최대 15 (`pool_size=5 + max_overflow=10`).
- 웹 N 개 + Celery worker (`concurrency=2`) 까지 고려하면 N=3 인 경우
  이미 45+ → 기본 `max_connections=100` 에 근접.
- N=5 이상으로 스케일아웃하면 DB 거부 (`FATAL: too many clients already`) 현실화.
- 현재 `docker-compose.yml` 기준 인스턴스 1개이므로 **아직 문제 없음**. 스케일아웃
  직전 선제 도입이 안전.

---

## 2. PgBouncer 풀링 모드 3가지

| 모드 | 특성 | mcper 적합도 |
|------|------|--------------|
| **session** | 클라이언트 연결 수명 동안 DB 커넥션 점유. prepared statement·`SET LOCAL` 등 모든 세션 상태 안전. 효율 낮음. | 시작 단계 안전 (롤백 쉬움) |
| **transaction** | 트랜잭션 경계로 DB 커넥션 반납. 고효율. 세션 상태(prepared statement, `SET`, temp table) 사용 시 주의. | 목표 모드 |
| **statement** | 문장 단위 반납. 다중 문장 트랜잭션 불가. | **부적합** — 앱이 트랜잭션 사용 |

---

## 3. SQLAlchemy + transaction pooling 호환성

### 3.1 알려진 함정

- `psycopg2` 는 server-side prepared statement 를 기본 비활성이라 `psycopg3` 보다
  transaction pool 친화적이다. 우리는 `psycopg2-binary` 이므로 상대적으로 안전.
- `psycopg3` + server-side prepared statement 기본 on 이면 transaction pool 에서
  오류가 난다 (PgBouncer 가 다음 트랜잭션에서 다른 DB 커넥션으로 돌릴 때
  prepared name 불일치). 우리는 해당 사항 없지만, 향후 드라이버 교체 시 주의.
- SQLAlchemy 컴파일 캐시(compiled_cache) 는 클라이언트 측이라 PgBouncer 와 무관.

### 3.2 옵션 플래그

- `create_engine(..., connect_args={"prepare_threshold": None})` — psycopg3 전환
  시 prepared statement 비활성화 (현 스택에선 불필요).
- `execution_options(compiled_cache=None)` — 일반적으로 필요 없음. 성능 저하만
  유발. 예약만 해두고 평상시 끔.
- `pool_pre_ping=True` 유지 — PgBouncer 앞단에서도 stale 커넥션 감지에 유효.

### 3.3 검증 포인트

- DDL 실행 경로 (`_apply_lightweight_migrations` / `_apply_rag_indexes` —
  `database.py:54-875`) 가 transaction 모드에서 정상 동작하는지.
- `SET LOCAL` / `WITH` 컨텍스트 사용 여부 (grep 결과 없음 — 안전).
- pgvector HNSW 쿼리 (`vector_cosine_ops`) 의 실행 계획이 PgBouncer 경유 전후로
  동일한지 (실행 계획은 서버 측이라 보통 동일, 레이턴시만 관측).

---

## 4. 구성 제안

### 4.1 docker-compose 예시

```yaml
services:
  pgbouncer:
    image: edoburu/pgbouncer:1.23.1
    environment:
      DB_HOST: db
      DB_PORT: 5432
      DB_USER: ${DB_USER:-user}
      DB_PASSWORD: ${DB_PASSWORD:-password}
      POOL_MODE: session          # 시작 단계 — 안전
      MAX_CLIENT_CONN: "200"
      DEFAULT_POOL_SIZE: "20"
      RESERVE_POOL_SIZE: "5"
      SERVER_RESET_QUERY: DISCARD ALL
      AUTH_TYPE: scram-sha-256
    ports:
      - "${MCPER_HOST_BIND:-127.0.0.1}:${PGB_PORT:-6432}:6432"
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "pg_isready", "-h", "localhost", "-p", "6432"]
      interval: 10s
      timeout: 5s
      retries: 5
```

### 4.2 애플리케이션 측 변경

- `DATABASE_URL` 을 Postgres 직결 → PgBouncer (포트 6432) 로 전환.
  기존 URL 은 `DATABASE_URL_DIRECT` 로 보존 (DDL·마이그레이션용).
- SQLAlchemy 풀 축소 — 실제 풀 관리는 PgBouncer 가 수행.
  ```python
  # app/db/database.py:44-49 예시 치환
  engine = create_engine(
      DATABASE_URL,
      pool_pre_ping=True,
      pool_size=2,
      max_overflow=3,
  )
  ```
- **DDL 경로만 예외** — `init_db()` 는 `DATABASE_URL_DIRECT` 로 직결 엔진을 별도
  생성해 사용. transaction 모드에서 advisory lock·`CREATE EXTENSION` 의 일부
  DDL 이 끊기는 것을 방지.

### 4.3 PgBouncer 튜닝 가이드

| 파라미터 | 제안 | 근거 |
|----------|------|------|
| `pool_mode` | `session` → `transaction` 단계 전환 | 위험 최소화 |
| `max_client_conn` | 200 | 웹 5 + worker 수를 고려해 여유 확보 |
| `default_pool_size` | 20 | Postgres `max_connections=100` 대비 안전 |
| `reserve_pool_size` | 5 | 버스트 대응 |
| `server_reset_query` | `DISCARD ALL` | 세션 상태 누수 차단 |
| `server_lifetime` | 3600 | idle 커넥션 수명 제한 |
| `server_idle_timeout` | 600 | idle 회수 |

---

## 5. 검증 체크리스트

- 통합 테스트 (`infra/docker/docker-compose.test.yml`) 전 구간 통과.
- `idle in transaction` 장기 점유 없는지 — `pg_stat_activity` 관측.
- prepared statement 관련 에러(`prepared statement "..." does not exist`) 로그
  0건.
- pgvector HNSW 쿼리 p95 전후 비교 — 레이턴시 허용 범위 (+/- 10 ms 이내 목표).
- Celery worker 장시간 실행에서 커넥션 leak 없는지 — `pool_size` 축소 후 특히 주의.
- DDL 마이그레이션 (`init_db`) 직결 경로 정상 동작.

---

## 6. 마이그레이션 단계

1. **세션 모드 도입** — PgBouncer 컨테이너 추가, `DATABASE_URL` 만 6432 로 전환.
   SQLAlchemy 풀 설정은 그대로. 최소 변경, 최대 안전.
2. **관측 1~2일** — `pg_stat_activity`, 앱 로그, 에러율 관측.
3. **transaction 모드 전환** — `POOL_MODE=transaction` 한 줄 변경 + 재시작.
   SQLAlchemy 풀 축소 (`pool_size=2, max_overflow=3`).
4. **문제 발생 시 롤백** — 세션 모드로 1줄 되돌림.

---

## 7. 롤백

- `DATABASE_URL` 을 Postgres 직결 (5432) 로 복귀.
- `app/db/database.py:44-49` 풀 파라미터 원복 (`pool_size=5, max_overflow=10`).
- PgBouncer 컨테이너 제거는 1단계 롤백 확인 후.

---

## 8. 작업 견적

| 항목 | 공수 |
|------|------|
| 기본 구성 + 세션 모드 도입 + 검증 | 0.5일 |
| transaction 모드 전환 + 관측 + 튜닝 | 0.5일 |
| **합계** | **1일** |

---

## 9. 오픈 질문

- 앱 코드에서 명시적 prepared statement 사용은 확인 결과 없음
  (grep `prepare_threshold|prepared_statement|compiled_cache` → 0건). 향후
  `psycopg3` 이관 시 재검토 필요.
- multi-statement long transaction 을 돌리는 경로 존재 여부 — Celery 대량 배치
  (임베딩 백필 등) 에서 단일 트랜잭션이 수 분 지속하면 transaction 모드에서 DB
  커넥션을 그만큼 점유하므로 풀 사이즈 재산정 필요.
- pgvector HNSW `CREATE INDEX` 같은 장시간 DDL 은 직결 경로로 실행할 것.

---

## 실구현 완료 (2026-04-29)

- `infra/docker/docker-compose.yml` 에 `pgbouncer` 서비스 추가
  (profile: `pgbouncer` — 기본 기동에서 제외)
- 이미지는 `edoburu/pgbouncer:v1.23.1-p3` (태그 `1.23.1` 이 registry 에
  없어 p3 패치 태그로 고정. 환경변수 스킴은 설계 문서와 동일).
- 기본 `pool_mode=session` (안전). transaction 은 향후.
- `app/db/database.py` 의 `pool_size` / `max_overflow` 를 `DB_POOL_SIZE` /
  `DB_MAX_OVERFLOW` 환경변수화 (기본값은 기존과 동일: 5/10).
- `infra/docker/.env.example` 에 PgBouncer 및 풀 파라미터 토글 문서화.

### 활성화 순서

1. `docker compose --profile pgbouncer up -d pgbouncer`
2. `.env.local` 에서 `DATABASE_URL` 을 pgbouncer 로 전환:
   `DATABASE_URL=postgresql://user:password@pgbouncer:5432/mcpdb`
3. 선택: `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=3` 으로 앱 풀 축소.
4. `docker compose up -d --force-recreate web worker`

### 롤백

- `DATABASE_URL` 을 원래 `db:5432` 로 되돌림.
- `docker compose --profile pgbouncer down pgbouncer`
- 필요 시 `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` 도 원복.

### transaction 모드 전환 (향후)

- `PGBOUNCER_POOL_MODE=transaction` 으로 변경 후 pgbouncer 재기동.
- SQLAlchemy 컴파일 캐시·prepared statement 관련 이슈 모니터링
  (`prepared statement "..." does not exist` 로그 확인).
- 문제 발생 시 `PGBOUNCER_POOL_MODE=session` 으로 즉시 롤백.
- pgvector HNSW `CREATE INDEX` 등 장시간 DDL 은 pgbouncer 경유하지 말고
  Postgres 직결(5432) 로 실행.
