# docs/PLANS.md — 현재 진행 중인 계획 요약\n\n**최종 업데이트**: 2026-03-30\n\n---\n\n## 활성 계획\n\n### 📋 진행 중: 보안 및 리팩토링 Phase 1\n\n**상태**: 기획 완료 → 구현 시작 예정\n\n**담당**: @coder, @tester, @infra\n\n**기간**: 2주 (2026-03-30 ~ 2026-04-13)\n\n**목표**: CRITICAL 3개 보안 항목 완료\n\n#### 항목 1: Admin 패스워드 강제 변경\n\n**설명**: 기본 패스워드 \"changeme\" → 강제 변경\n\n**상세**:\n- Lifespan 훅에서 패스워드 변경 여부 확인\n- 미변경 시 설정 페이지로 리다이렉트\n- 패스워드 정책: 12자 이상, 특수문자 포함\n\n**파일**:\n- `app/main.py` (lifespan)\n- `app/routers/admin.py` (/admin/settings)\n- `app/auth/service.py` (validate_password)\n\n**예상 시간**: 4시간\n\n**의존성**: 없음\n\n---\n\n#### 항목 2: API 토큰 만료 검증\n\n**설명**: JWT 토큰의 `expires_at` 필드 검증 추가\n\n**상세**:\n- 토큰 생성 시 만료 시간 포함\n- 모든 보호된 엔드포인트에서 검증\n- 만료된 토큰: 401 응답\n\n**파일**:\n- `app/auth/dependencies.py` (verify_token)\n- `app/auth/service.py` (issue_token)\n- `tests/test_auth_token_expiry.py` (테스트)\n\n**예상 시간**: 4.5시간\n\n**의존성**: 없음\n\n---\n\n#### 항목 3: CORS/CSRF 강화\n\n**설명**: CORS 정책 강화 + CSRF 토큰 검증\n\n**상세**:\n- CORS: Cursor, localhost만 허용\n- CSRF: POST/PUT/DELETE에 토큰 필수\n- 미들웨어: `app/asgi/csrf_middleware.py`\n\n**파일**:\n- `app/main.py` (CORSMiddleware)\n- `app/asgi/csrf_middleware.py` (신규)\n- `app/routers/admin.py` (/admin/csrf-token)\n- `tests/test_csrf.py` (테스트)\n\n**예상 시간**: 7시간\n\n**의존성**: 항목 1, 2 이후\n\n---\n\n### 📋 계획 중: Phase 2 (구조 개선)\n\n**상태**: 기획 완료\n\n**기간**: 3주 (2026-04-14 ~ 2026-04-30)\n\n**목표**: HIGH 3개 항목 완료\n\n#### 항목 4: admin.py 모듈 분리\n\n**설명**: 1293줄 단일 파일 → 4개 라우터로 분리\n\n**분리 방식**:\n```\nadmin.py (삭제)\n├─ admin_base.py       (인증, 기본 설정)\n├─ admin_dashboard.py  (대시보드, 통계)\n├─ admin_specs.py      (기획서 CRUD)\n├─ admin_rules.py      (규칙 발행)\n└─ admin_tools.py      (도구 통계)\n```\n\n**예상 시간**: 10.5시간\n\n**의존성**: Phase 1 이후\n\n---\n\n#### 항목 5: CodeNode 파서 개발\n\n**설명**: Python/JavaScript AST 크롤러로 코드 노드 자동 생성\n\n**상세**:\n- Python: `ast` 모듈 + 함수/클래스 추출\n- JavaScript: `@babel/parser` + 노드 변환\n- Celery 태스크로 비동기 처리\n\n**파일**:\n- `app/services/code_parser.py` (기본 인터페이스)\n- `app/services/code_parser_python.py` (Python 구현)\n- `app/services/code_parser_javascript.py` (JS 구현)\n- `app/worker/tasks.py` (index_code_batch)\n\n**예상 시간**: 9시간\n\n**의존성**: 없음 (병렬 가능)\n\n---\n\n#### 항목 6: Celery 모니터링 대시보드\n\n**설명**: 큐 깊이, 처리 시간, 실패 추적\n\n**상세**:\n- 대시보드: `/admin/celery`\n- 메트릭: 큐 길이, 작업 시간, 에러율\n- 실시간 갱신 (SSE 또는 polling)\n\n**파일**:\n- `app/services/celery_monitoring.py` (신규)\n- `app/routers/admin_celery.py` (신규)\n- `app/templates/admin/celery.html` (신규)\n\n**예상 시간**: 6시간\n\n**의존성**: 없음 (병렬 가능)\n\n---\n\n## 백로그 (장기)\n\n### P1: 테스트 강화\n\n- [ ] 단위 테스트: 50+ (현재 10)\n- [ ] 통합 테스트: 20+ (현재 0)\n- [ ] E2E 테스트: 5+ (현재 0)\n- **예상 시간**: 30시간\n\n### P2: 모니터링 인프라\n\n- [ ] Grafana 대시보드\n- [ ] CloudWatch Alarms\n- [ ] 구조화 로깅 (Datadog)\n- **예상 시간**: 12시간\n\n### P3: 권한 관리\n\n- [ ] Role-Based Access Control (RBAC)\n- [ ] 조직별 격리\n- [ ] 감사 로그\n- **예상 시간**: 15시간\n\n---\n\n## 마일스톤\n\n| 날짜 | 마일스톤 | 상태 |\n|------|----------|------|\n| 2026-04-13 | Phase 1 완료 (보안 3개) | 계획 중 |\n| 2026-04-30 | Phase 2 완료 (구조 3개) | 계획 중 |\n| 2026-05-31 | 프로덕션 배포 가능 | 계획 중 |\n| 2026-06-30 | 엔터프라이즈 기능 (RBAC) | 계획 중 |\n\n---\n\n## 의존성 그래프\n\n```\n┌─────────────────────────────────────────────┐\n│ Phase 1 (보안 강화)                          │\n├─────────────────────────────────────────────┤\n│ 1. Admin 패스워드 강제 변경 ───┐             │\n│ 2. API 토큰 만료 검증 ────────┤─┐           │\n│ 3. CORS/CSRF 강화 ────────────┤─├─ 완료    │\n└─────────────────────────────────────────────┘\n                 │\n                 ▼\n┌─────────────────────────────────────────────┐\n│ Phase 2 (구조 개선)                          │\n├─────────────────────────────────────────────┤\n│ 4. admin.py 분리 ◄─ (의존성)                 │\n│ 5. CodeNode 파서 (병렬)                     │\n│ 6. Celery 모니터링 (병렬)                   │\n└─────────────────────────────────────────────┘\n```\n\n---\n\n## 리스크 및 대응\n\n### R1: 패스워드 강제 변경 UX\n\n**리스크**: 사용자가 \"나중에\" 클릭해 우회\n\n**대응**: 로그인 페이지를 설정 페이지로 리다이렉트 (우회 불가)\n\n### R2: 토큰 만료로 인한 재로그인\n\n**리스크**: UX 저하 (30분마다 로그인)\n\n**대응**: Refresh 토큰 구현 (TTL 7일)\n\n### R3: CodeNode 파서 성능\n\n**리스크**: 대형 저장소 파싱에 시간 오래 걸림\n\n**대응**: 증분 색인 + Celery 병렬화\n\n---\n\n## 성공 기준\n\n### Phase 1\n\n- ✅ CRITICAL 3개 취약점 해결\n- ✅ 테스트 커버리지 >= 20%\n- ✅ 배포 가이드 완성\n\n### Phase 2\n\n- ✅ admin.py < 300줄 (각 라우터)\n- ✅ CodeNode 100+ 자동 생성\n- ✅ Celery 모니터링 UI 가동\n\n---\n\n## 관련 문서\n\n- **AGENTS.md** — 팀 구조\n- **docs/dev_log.md** — 작업 이력\n- **docs/planning_security_and_refactor.md** — 상세 기획\n"
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
