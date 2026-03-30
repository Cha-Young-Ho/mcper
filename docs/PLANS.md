# docs/PLANS.md — 현재 진행 중인 계획 요약

**최종 업데이트**: 2026-03-31

---

## 활성 계획

### ✅ 완료: 보안 강화 Phase 1

**상태**: 완료 (2026-03-30)

**담당**: @coder, @tester

**목표**: CRITICAL 3개 보안 항목 완료

- ✅ 항목 1: Admin 패스워드 강제 변경 — `validate_password()` 추가, 12자+특수문자 정책
- ✅ 항목 2: API 토큰 만료 검증 — `ExpiredSignatureError` 분리, 만료 토큰 401 응답
- ✅ 항목 3: CORS/CSRF 강화 — 와일드카드 차단, CSRF 미들웨어, `/admin/csrf-token` 추가

**상세 기획**: `docs/planning_security_and_refactor.md`

---

### 📋 진행 예정: 구조 개선 Phase 2

**상태**: 기획 완료, 구현 대기

**기간**: 2026-04-14 ~ 2026-04-30

**목표**: HIGH 3개 항목 완료

#### 항목 4: admin.py 모듈 분리

**설명**: 1293줄 단일 파일 → 4개 라우터로 분리

```
admin.py (삭제)
├─ admin_base.py       (인증, 기본 설정)
├─ admin_dashboard.py  (대시보드, 통계)
├─ admin_specs.py      (기획서 CRUD)
├─ admin_rules.py      (규칙 발행)
└─ admin_tools.py      (도구 통계)
```

**예상 시간**: 10.5시간 | **의존성**: Phase 1 완료 (충족)

---

#### 항목 5: CodeNode 파서 개발

**설명**: Python/JavaScript AST 크롤러로 코드 노드 자동 생성

**파일**: `app/services/code_parser.py`, `code_parser_python.py`, `code_parser_javascript.py`, `app/worker/tasks.py`

**예상 시간**: 9시간 | **의존성**: 없음 (병렬 가능)

---

#### 항목 6: Celery 모니터링 대시보드

**설명**: 큐 깊이, 처리 시간, 실패 추적 (`/admin/celery`)

**파일**: `app/services/celery_monitoring.py`, `app/routers/admin_celery.py`, `app/templates/admin/celery.html`

**예상 시간**: 6시간 | **의존성**: 없음 (병렬 가능)

---

## 백로그 (장기)

| 항목 | 예상 시간 |
|------|----------|
| P1: 테스트 강화 (단위 50+, 통합 20+, E2E 5+) | 30시간 |
| P2: 모니터링 인프라 (Grafana, CloudWatch, Datadog) | 12시간 |
| P3: 권한 관리 (RBAC, 조직 격리, 감사 로그) | 15시간 |

---

## 마일스톤

| 날짜 | 마일스톤 | 상태 |
|------|----------|------|
| 2026-04-13 | Phase 1 완료 (보안 3개) | ✅ 완료 |
| 2026-04-30 | Phase 2 완료 (구조 3개) | 진행 예정 |
| 2026-05-31 | 프로덕션 배포 가능 | 계획 중 |
| 2026-06-30 | 엔터프라이즈 기능 (RBAC) | 계획 중 |

---

## 관련 문서

- **AGENTS.md** — 팀 구조
- **docs/dev_log.md** — 작업 이력
- **docs/planning_security_and_refactor.md** — Phase 1/2 상세 기획

---

## 주기적 검증 (Harness Engineering)

**매주 금요일 15:00 — @senior 담당**

### 체크리스트

- [ ] **문서 링크**: 깨진 링크 없음
- [ ] **코드-설계 동기화**: ARCHITECTURE.md와 실제 코드 일치
- [ ] **설계 원칙**: core-beliefs.md 13개 위반 없음
- [ ] **계층 검증**: `python scripts/validate_architecture.py` 통과
- [ ] **스키마 동기화**: `docs/generated/db-schema.md` 최신 상태

### 실행 명령

```bash
python scripts/validate_architecture.py
```

### 보고

위반사항 발견 시 `docs/dev_log.md` 맨 위에:

```markdown
## [날짜]: @senior 주기적 검증

### 발견 사항
- [위반 사항]

### 결과
⚠️ 수정 필요 / ✅ 통과
```
