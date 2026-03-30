# MCPER 배포 체크리스트 (6개 항목 구현 완료 후)

**작성일**: 2026-03-30
**역할**: @infra (인프라 관리자)
**목표**: 6개 항목(CRITICAL 3 + HIGH 3) 구현 완료 후 단계별 배포 검수

---

## 1. 사전 검수 (개발 완료 후)

### 1.1 코드 품질 검사

- [ ] **단위 테스트 통과**
  ```bash
  pytest tests/ -v --cov=app --cov-report=term-missing
  ```
  - 목표: 커버리지 >= 80%
  - 주요 테스트: 인증, CSRF, 토큰 만료, 코드 파서, Celery 모니터링

- [ ] **타입 체크 통과** (선택)
  ```bash
  mypy app/ --ignore-missing-imports
  ```
  - 주요 모듈: auth, asgi, services

- [ ] **코드 스타일 통일**
  ```bash
  black app/ tests/
  isort app/ tests/
  pylint app/ --exit-zero  # 리포트만 수집
  ```

- [ ] **보안 취약점 스캔**
  ```bash
  bandit -r app/ -ll  # 낮음 수준 제외
  safety check        # 의존성 취약점
  ```

- [ ] **의존성 보안 업데이트**
  ```bash
  pip-audit --desc
  ```
  - requirements.txt 핀 버전 확인
  - 기존 버전과의 호환성 검증

### 1.2 데이터베이스 마이그레이션 검증

- [ ] **로컬 환경에서 마이그레이션 테스트**
  ```bash
  # 신규 테이블 생성 확인
  docker compose exec db psql -U mcper -d mcpdb -c "\dt"
  ```
  - 테이블: `mcper_users` (password_changed_at), `failed_tasks`

- [ ] **마이그레이션 이전 호환성 확인**
  ```bash
  # 기존 데이터와의 호환성
  docker compose exec db psql -U mcper -d mcpdb -c "SELECT column_name FROM information_schema.columns WHERE table_name='mcper_users';"
  ```

- [ ] **롤백 테스트** (스테이징)
  ```bash
  # 마이그레이션 이전으로 되돌릴 수 있는지 확인
  # DROP COLUMN, DROP TABLE 스크립트 준비
  ```

### 1.3 환경 변수 검증

- [ ] **신규 환경 변수 추가 확인**
  ```bash
  # .env.example 업데이트
  grep "AUTH_TOKEN_EXPIRE_MINUTES\|SECURE_COOKIE\|CORS_ALLOWED_ORIGINS" .env.example
  ```

- [ ] **민감 정보 확인**
  - [ ] `AUTH_SECRET_KEY` 설정 (32자 이상 랜덤)
  - [ ] `ADMIN_PASSWORD` 변경됨 (기본값 아님)
  - [ ] `infra/kubernetes/secret.yaml` 절대 커밋 금지

- [ ] **설정 병합 테스트**
  ```bash
  python -c "from app.config import settings; print(settings.auth.token_expire_minutes)"
  ```

---

## 2. 단계별 배포

### Phase 1: 로컬 개발 환경 (개발자 검증)

**소요시간**: 0.5일

- [ ] **Docker Compose 재구성**
  ```bash
  cd infra/docker
  docker compose down -v  # 기존 볼륨 삭제
  docker compose up -d    # 신규 마이그레이션 적용
  ```

- [ ] **기본 엔드포인트 테스트**
  ```bash
  curl -s http://localhost:8001/health | jq .
  curl -s http://localhost:8001/health/rag | jq .
  ```

- [ ] **보안 기능 테스트**
  ```bash
  # 1. Admin 기본 패스워드 변경 강제
  curl -X GET http://localhost:8001/auth/login

  # 2. CSRF 토큰 생성 확인
  curl -X GET http://localhost:8001/admin -c cookies.txt

  # 3. JWT 토큰 만료 검증
  curl -X POST http://localhost:8001/auth/token/refresh \
    -H "Authorization: Bearer <expired_token>"
  ```

- [ ] **Celery 모니터링 테스트**
  ```bash
  # 실패 태스크 생성
  # DB에 failed_tasks 레코드 확인
  docker compose exec db psql -U mcper -d mcpdb -c "SELECT * FROM failed_tasks LIMIT 5;"
  ```

### Phase 2: 스테이징 환경 (QA 검증)

**소요시간**: 1-2일

**전제**: 스테이징 클러스터 준비 (K8s 또는 Docker Compose)

- [ ] **신규 이미지 빌드 및 푸시**
  ```bash
  docker build -t mcper:staging . -f Dockerfile
  docker push <registry>/mcper:staging
  ```

- [ ] **K8s 배포** (마이그레이션 Job 먼저)
  ```bash
  # 1. 네임스페이스 생성
  kubectl create namespace mcper-staging

  # 2. ConfigMap/Secret 적용
  kubectl apply -f infra/kubernetes/configmap.yaml -n mcper-staging
  kubectl apply -f infra/kubernetes/secret.yaml -n mcper-staging

  # 3. 마이그레이션 Job 실행
  kubectl apply -f infra/kubernetes/migration-job.yaml -n mcper-staging
  kubectl wait --for=condition=complete job/mcper-migration -n mcper-staging --timeout=300s

  # 4. 앱 배포
  kubectl apply -f infra/kubernetes/ -n mcper-staging
  ```

- [ ] **통합 테스트 실행** (스테이징)
  ```bash
  pytest tests/integration/ -v --env=staging
  ```

- [ ] **부하 테스트** (선택)
  ```bash
  locust -f tests/load/locustfile.py -H http://staging.example.com
  ```

- [ ] **보안 테스트**
  ```bash
  # CSRF 공격 시뮬레이션
  # CORS Origin 검증
  # JWT 토큰 만료 확인
  ```

### Phase 3: 프로덕션 배포 (무중단)

**소요시간**: 1-2시간

**전제**: 프로덕션 클러스터, 백업 정책 확인

- [ ] **백업 실행**
  ```bash
  # PostgreSQL 백업
  pg_dump mcpdb > mcpdb.backup.$(date +%Y%m%d).sql

  # 또는 클라우드 스냅샷
  # AWS RDS: aws rds create-db-snapshot --db-instance-identifier mcpdb
  ```

- [ ] **마이그레이션 Job 실행** (프로덕션)
  ```bash
  kubectl apply -f infra/kubernetes/migration-job.yaml -n mcper
  kubectl logs -f job/mcper-migration -n mcper
  ```

- [ ] **카나리 배포** (rolling update)
  ```bash
  # 기존: replicas=3
  # 신규: 1개 pod에만 새 이미지 배포
  kubectl set image deployment/mcper-web mcper-web=<registry>/mcper:v1.2.0 --record -n mcper
  kubectl rollout status deployment/mcper-web -n mcper

  # 모니터링: 5-10분
  ```

- [ ] **전체 롤링 업데이트**
  ```bash
  # 나머지 2개 pod 업데이트
  kubectl rollout resume deployment/mcper-web -n mcper
  kubectl rollout status deployment/mcper-web -n mcper
  ```

- [ ] **Worker 배포**
  ```bash
  kubectl set image deployment/mcper-worker mcper-worker=<registry>/mcper:v1.2.0 --record -n mcper
  kubectl rollout status deployment/mcper-worker -n mcper
  ```

- [ ] **Admin UI 배포** (필요 시)
  ```bash
  kubectl set image deployment/mcper-admin mcper-admin=<registry>/mcper:v1.2.0 --record -n mcper
  # Recreate 전략이므로 짧은 다운타임 (< 30초)
  ```

---

## 3. 배포 후 검증 (1-2시간)

### 3.1 기본 헬스 체크

- [ ] **API 엔드포인트 응답 확인**
  ```bash
  curl -s https://api.example.com/health | jq .
  curl -s https://api.example.com/health/rag | jq .
  ```

- [ ] **어드민 UI 로드 확인**
  ```bash
  curl -s -I https://admin.example.com/admin | grep 200
  ```

- [ ] **MCP 엔드포인트 응답 확인**
  ```bash
  curl -X POST https://api.example.com/mcp/tools/search_spec_and_code \
    -H "Content-Type: application/json" \
    -d '{"query": "test", "app_target": "api"}'
  ```

### 3.2 보안 기능 검증

- [ ] **Admin 패스워드 강제 변경**
  - 초기 관리자 로그인 → 강제 변경 페이지
  - 새 패스워드 설정 → 로그아웃 → 새 패스워드로 로그인 성공

- [ ] **JWT 토큰 만료**
  - 토큰 발급 → 15분 대기 → 만료 토큰으로 요청 → 401 Unauthorized
  - Refresh 토큰 사용 → 새 토큰 발급 성공

- [ ] **CSRF 방어**
  ```bash
  # CSRF 토큰 없이 POST 요청 → 403 Forbidden
  curl -X POST https://admin.example.com/admin/specs \
    -d "title=test" \
    -H "Origin: https://evil.com"
  ```

- [ ] **CORS Origin 검증**
  ```bash
  # 허용되지 않은 Origin → 403
  curl -X OPTIONS https://api.example.com/health \
    -H "Origin: https://evil.com"
  ```

### 3.3 기능 검증

- [ ] **기획서 업로드 및 검색**
  - 새 기획서 업로드 → 청킹 성공 → 검색 가능

- [ ] **규칙 관리**
  - 글로벌 규칙 버전 확인 (GET /admin/global-rules)
  - 새 규칙 publish → 버전 증가

- [ ] **Celery 모니터링**
  - 실패 태스크 대시보드 접근 (GET /admin/monitoring)
  - 재시도 버튼 클릭 → 태스크 큐에 재추가

- [ ] **코드 노드 파서**
  - 새 코드 인덱싱 → 기호(symbols) 자동 파싱
  - CodeNode 테이블에 데이터 삽입 확인

### 3.4 성능 메트릭 확인

- [ ] **응답 시간** (p95 < 200ms)
  ```bash
  # 프로메테우스 또는 모니터링 도구
  # 또는 CloudWatch 메트릭
  ```

- [ ] **에러율** (< 0.1%)
  ```bash
  # Stackdriver 또는 CloudWatch 로그
  # ERROR 레벨 로그 개수 / 전체 요청 수
  ```

- [ ] **Celery 큐 깊이** (< 100)
  ```bash
  # Flower 또는 Redis 직접 확인
  redis-cli -n 0 LLEN celery
  ```

- [ ] **DB 커넥션 풀** (< 80% 사용)
  ```bash
  # PostgreSQL 활성 커넥션 확인
  SELECT count(*) FROM pg_stat_activity;
  ```

---

## 4. 배포 후 모니터링 (1주일)

### 4.1 일일 모니터링

- [ ] **에러 로그 확인** (매일)
  - 실시간 에러 알림 설정 (Slack)
  - 신규 에러 패턴 분석

- [ ] **성능 메트릭 추이** (매일)
  - API 응답 시간 추이
  - Celery 큐 깊이 변화
  - DB 쿼리 성능

- [ ] **사용자 피드백** (매일)
  - 문제 보고 확인
  - 새로운 기능 사용 현황

### 4.2 주간 리포트

- [ ] **배포 영향 분석**
  - 성공/실패 지표
  - 개선된 점 (보안, 성능)
  - 예상치 못한 문제

- [ ] **롤백 판단**
  - 에러율 급증 시 즉시 롤백
  - 신규 버그 발견 시 검토 후 롤백 또는 긴급 패치

---

## 5. 롤백 절차 (긴급)

### 5.1 즉시 롤백 (< 5분)

**상황**: 에러율 > 5%, 서비스 불가능 상태

```bash
# 1. 이전 이미지로 빠르게 복구
kubectl set image deployment/mcper-web mcper-web=<registry>/mcper:v1.1.0 --record -n mcper

# 2. 롤아웃 상태 확인
kubectl rollout status deployment/mcper-web -n mcper

# 3. 포드 재시작 (쿠키 캐시 제거)
kubectl rollout restart deployment/mcper-web -n mcper
```

### 5.2 데이터베이스 롤백 (마이그레이션 실패 시)

**상황**: 마이그레이션 중 오류 (예: 컬럼 생성 실패)

```bash
# 1. 백업 복구 (프로덕션 계획에 따라)
psql mcpdb < mcpdb.backup.20260330.sql

# 또는 AWS RDS 스냅샷 복구
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier mcpdb-restored \
  --db-snapshot-identifier mcpdb.20260330

# 2. 이전 앱 버전 배포
kubectl set image deployment/mcper-web mcper-web=<registry>/mcper:v1.1.0 -n mcper
```

### 5.3 부분 롤백 (특정 기능만)

**상황**: 특정 기능(예: Celery 모니터링)만 문제

```bash
# app/main.py 에서 FailedTask 초기화 제거
# 환경 변수: CELERY_MONITORING_ENABLED=false
# 배포 후 재시도
```

---

## 6. 환경별 설정 차이

### 로컬 개발 (docker-compose)

| 항목 | 값 |
|------|-----|
| `LOG_FORMAT` | `text` |
| `LOG_LEVEL` | `DEBUG` |
| `MCPER_AUTH_ENABLED` | `false` (또는 `true` 테스트용) |
| `SECURE_COOKIE` | `false` |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` |
| `MCP_BYPASS_TRANSPORT_GATE` | `true` (개발용) |

### 스테이징 (K8s)

| 항목 | 값 |
|------|-----|
| `LOG_FORMAT` | `text` 또는 `json` |
| `LOG_LEVEL` | `DEBUG` |
| `MCPER_AUTH_ENABLED` | `true` |
| `SECURE_COOKIE` | `true` |
| `CORS_ALLOWED_ORIGINS` | `https://staging.example.com` |
| `MCP_BYPASS_TRANSPORT_GATE` | `false` |

### 프로덕션 (K8s)

| 항목 | 값 |
|------|-----|
| `LOG_FORMAT` | `json` |
| `LOG_LEVEL` | `INFO` |
| `MCPER_AUTH_ENABLED` | `true` |
| `SECURE_COOKIE` | `true` |
| `CORS_ALLOWED_ORIGINS` | `https://api.example.com` |
| `MCP_BYPASS_TRANSPORT_GATE` | `false` |

---

## 7. 문서 및 커뮤니케이션

### 7.1 개발 로그 업데이트

```markdown
## 2026-03-30 배포 준비 완료

**작업자**: @infra
**범위**: 6개 항목 배포 체크리스트 및 롤백 계획 수립

**완료 항목**:
- DEPLOYMENT_CHECKLIST.md 작성
- ROLLBACK_PLAN.md 작성
- MONITORING.md 작성
- 환경 변수 매핑 완료

**다음 단계**:
1. 개발 팀 검수 완료 대기
2. 스테이징 환경 배포
3. 프로덕션 배포 (무중단)
```

### 7.2 팀 공지 (배포 전)

```
제목: MCPER v1.2.0 배포 공지 (2026-03-31)

안녕하세요,

다음과 같이 MCPER 신규 버전 배포를 진행합니다:

[변경 사항]
- Admin 패스워드 강제 변경 (초기 로그인 시)
- JWT 토큰 15분 만료 + Refresh 토큰 지원
- CSRF 방어 강화
- 코드 파일 자동 파싱 (Python/JS)
- Celery 실패 태스크 모니터링

[주의 사항]
- 초기 로그인 시 패스워드 변경 필수
- API 토큰 15분 후 갱신 필요 (refresh 엔드포인트)
- CSRF 토큰 폼 제출 시 필수

[일정]
- 스테이징: 2026-03-31 (금)
- 프로덕션: 2026-04-01 (월) 14:00 KST

[롤백 계획]
- 문제 발생 시 즉시 이전 버전으로 롤백 가능
- 다운타임 < 5분

연락처: infra-team@example.com
```

---

## 8. 성공 기준

### Phase별 완료 조건

| Phase | 완료 조건 |
|-------|---------|
| **로컬** | 모든 엔드포인트 정상 응답, 보안 기능 테스트 통과 |
| **스테이징** | 통합 테스트 통과, 성능 메트릭 확인, QA 검증 완료 |
| **프로덕션** | 무중단 배포 완료, 1주일 모니터링 통과, 에러율 < 0.1% |

### 기술 지표

| 지표 | 목표 | 기준 |
|------|------|------|
| API 응답 시간 (p95) | < 200ms | 건강 |
| 에러율 | < 0.1% | 건강 |
| Celery 큐 깊이 | < 100 | 건강 |
| DB 커넥션 풀 사용률 | < 80% | 건강 |
| 배포 다운타임 | < 5분 | 성공 |

---

## 9. 참고 자료

- `docs/DESIGN_SUMMARY.md` — 기술 설계 종합 요약
- `docs/DESIGN_CRITICAL_SECURITY.md` — CRITICAL 항목 상세 설계
- `docs/DESIGN_HIGH_REFACTOR.md` — HIGH 항목 상세 설계
- `docs/CLAUDE.md` — 기술 지침 및 인프라 규칙
- `infra/ROLLBACK_PLAN.md` — 롤백 상세 절차
- `infra/MONITORING.md` — 배포 후 모니터링 지표

---

**문서 버전**: 1.0
**작성일**: 2026-03-30
**역할**: @infra (인프라 관리자)
**상태**: 배포 준비 완료
