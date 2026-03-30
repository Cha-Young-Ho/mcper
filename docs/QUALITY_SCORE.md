# docs/QUALITY_SCORE.md — 품질 메트릭

현재 프로젝트의 코드 품질·아키텍처·운영 성숙도 평가.

---

## 종합 점수: 6.8 / 10

| 영역 | 점수 | 평가 | 비고 |
|------|------|------|------|
| 아키텍처 | 8/10 | 우수 | MCP 중심, 잘 분리됨 |
| 코드 품질 | 7/10 | 양호 | Type hints 완전, 테스트 부족 |
| 보안 | 4/10 | 약함 | 기본 패스워드, 토큰 검증 미완료 |
| 테스트 | 3/10 | 매우 약함 | 5개 테스트만 (단위 테스트 거의 없음) |
| 문서 | 8/10 | 우수 | 기술 가이드 충실 (이 문서들) |
| 운영 준비도 | 5/10 | 미흡 | 모니터링, 장애 복구 미완성 |

---

## 영역별 상세 평가

### 1. 아키텍처 (8/10)

**강점**:
- ✅ MCP 기반 에이전트 협업 (명확)
- ✅ 모듈 분리 (db, services, routers, tools, worker)
- ✅ 비동기 작업 (Celery)
- ✅ 다중 임베딩 프로바이더 (abstraction)
- ✅ Append-only 규칙 시스템 (감시 추적)

**약점**:
- ⚠️ admin.py 모놀리식 (1293줄, 분리 필요)
- ⚠️ 코드 파서 미완성 (CodeNode 자동 생성 X)
- ⚠️ 권한 관리 (ACL 미구현)

**개선**:
```
우선: admin.py 분리 (4개 라우터, 각 <300줄)
중순: CodeNode 파서 개발 (Python/JS AST)
장순: Role-Based Access Control (RBAC)
```

---

### 2. 코드 품질 (7/10)

**강점**:
- ✅ Type hints (모든 함수)
- ✅ Pydantic V2 검증 (입력/출력)
- ✅ 명확한 네이밍 (함수, 변수)
- ✅ 에러 핸들링 (대부분)

**약점**:
- ⚠️ 긴 함수 (spec_admin.py::create_spec 50줄)
- ⚠️ 복잡한 쿼리 (search_hybrid.py RRF 로직)
- ⚠️ 매직 넘버 (32 [RRF offset], 0.5 [벡터 임계])

**개선**:
```python
# 매직 넘버 → 상수
RRF_OFFSET = 32  # Reciprocal Rank Fusion offset
VECTOR_SIMILARITY_THRESHOLD = 0.5

# 긴 함수 → 헬퍼
def _parse_spec_chunks(content: str) -> list[str]:
    """기획서를 청크로 분할."""
    ...

def _embed_batch(chunks: list[str]) -> list[list[float]]:
    """배치 임베딩."""
    ...
```

---

### 3. 보안 (4/10) ⚠️ CRITICAL

**위반**:
- ❌ Admin 기본 패스워드 "changeme" (경고만, 강제 X)
- ❌ API 토큰 만료 검증 미완료
- ⚠️ CORS: Cursor만 허용하지 않음 (모든 origin?)
- ⚠️ 레이트 제한: 없음

**필수 개선** (CRITICAL):
1. [ ] Admin 패스워드 강제 변경 (첫 기동 시)
2. [ ] API 토큰 expires_at 검증
3. [ ] CORS 정책 강화
4. [ ] 레이트 제한 추가 (sliding window)

**스케줄**: Phase 1 (1주일, 15.5시간)

---

### 4. 테스트 (3/10) ❌ 부족

**현황**:
- 총 5개 테스트 파일
- 단위 테스트: ~10개
- 통합 테스트: 0개
- E2E 테스트: 0개

**부재한 테스트**:
- MCP 도구 (upload_spec, search, rules)
- 임베딩 백엔드 (로컬, OpenAI, Bedrock)
- 하이브리드 검색 (벡터 + FTS)
- 규칙 버전 관리 (append-only)
- Celery 태스크 (색인, 청크)
- 인증 (HTTP Basic, JWT, OAuth)
- 에러 케이스 (네트워크, DB 오류)

**개선 계획**:

```
Phase 1 (보안 테스트):
├─ test_auth_http_basic.py (로그인 실패, 성공)
├─ test_auth_csrf.py (토큰 검증)
└─ test_mcp_host_gate.py (화이트리스트)
→ 시간: 8시간, 커버리지 +15%

Phase 2 (RAG 테스트):
├─ test_spec_upload.py (CRUD)
├─ test_search_hybrid.py (벡터+FTS+RRF)
└─ test_celery_indexing.py (비동기 색인)
→ 시간: 12시간, 커버리지 +25%

Phase 3 (통합 테스트):
├─ test_mcp_tools_e2e.py (전체 흐름)
└─ test_admin_dashboard_e2e.py
→ 시간: 10시간, 커버리지 +20%
```

---

### 5. 문서 (8/10)

**강점**:
- ✅ README.md (충실한 설정 가이드)
- ✅ ARCHITECTURE_MASTER.md (온보딩)
- ✅ MCP 도구 설명 (명확)
- ✅ 이제: AGENTS.md, ARCHITECTURE.md, DESIGN.md, SECURITY.md, RELIABILITY.md

**약점**:
- ⚠️ API 문서: OpenAPI/Swagger 없음
- ⚠️ 코드 주석: 최소한만
- ⚠️ 문제 해결: 트러블슈팅 가이드 부족

**개선**:
```python
# FastAPI 자동 문서
app = FastAPI(
    title="Spec MCP API",
    description="MCP 도구 + RESTful API",
    version="1.0.0",
)
# → /docs (Swagger UI)
# → /redoc (ReDoc)
```

---

### 6. 운영 준비도 (5/10) ⚠️ 미흡

**갖춘 것**:
- ✅ 헬스체크 엔드포인트 (/health, /health/rag)
- ✅ 구조화 로깅 (JSON)
- ✅ 설정 병합 (YAML + env)

**부족한 것**:
- ❌ 모니터링 대시보드 (Grafana, DataDog)
- ❌ 경고 정책 (Slack, PagerDuty)
- ❌ 자동 확장 (ASG, HPA)
- ❌ 순환 복구 (failover)

**배포 체크리스트**: docs/RELIABILITY.md (작성 완료)

**모니터링 구현** (HIGH 우선):
```
1주일: CloudWatch 메트릭 + Alarm
- ErrorCount >= 5/5분 → 경고
- Latency p95 > 1000ms → 경고
- CPU > 80%, Memory > 1.5GB → 확장

2주: Grafana 대시보드
- MCP 도구 호출 분포
- 검색 응답 시간 (p50, p95, p99)
- Celery 큐 깊이 + 처리 시간
```

---

## 코드 복잡도

### 순환 복잡도 (Cyclomatic Complexity)

| 파일 | 함수 | 복잡도 | 평가 |
|------|------|--------|------|
| admin.py | create_rule | 8 | ⚠️ 높음 |
| search_hybrid.py | hybrid_search | 12 | ❌ 매우 높음 |
| versioned_rules.py | fetch_rules | 6 | 보통 |
| celery_app.py | index_spec | 4 | 낮음 |

**개선**:
- 함수 분할 (복잡도 10 이상 → 리팩토링)
- 조건 단순화 (if-elif-elif → dict lookup)

---

## 기술 부채

| 항목 | 우선 | 예상 시간 | 상태 |
|------|------|---------|------|
| Admin 기본 패스워드 강제 | CRITICAL | 4h | 계획 중 |
| API 토큰 만료 검증 | CRITICAL | 4.5h | 계획 중 |
| CORS/CSRF 강화 | CRITICAL | 7h | 계획 중 |
| admin.py 분리 | HIGH | 10.5h | 계획 중 |
| CodeNode 파서 | HIGH | 9h | 계획 중 |
| Celery 모니터링 | HIGH | 6h | 계획 중 |
| 단위 테스트 | HIGH | 30h | 계획 중 |
| 통합 테스트 | MEDIUM | 20h | 계획 중 |
| 레이트 제한 | MEDIUM | 8h | 백로그 |
| 권한 관리 (RBAC) | MEDIUM | 15h | 백로그 |

**총 부채**: ~114시간 = 3주 (2명 개발)

---

## 성능 프로파일링

### 병목 지점

| 구간 | 시간 | 원인 | 개선 |
|------|------|------|------|
| 벡터 임베딩 | 500ms-2s | 모델 크기 | 작은 모델 또는 API |
| FTS 검색 | 50-100ms | 전문 색인 | 이미 최적 |
| RRF 병합 | 10-20ms | Python 루프 | SQL로 이동 |
| spec_chunks INSERT | 100ms (1000행) | 배치 크기 | 5000행으로 증가 |

---

## 이전 버전 호환성

| 기능 | v1.0 | 호환성 |
|------|------|--------|
| Spec 기획서 | ✅ | 안정 (스키마 고정) |
| Rule 규칙 | ✅ | 안정 (append-only) |
| Embedding | ✅ | 부분 (모델 변경 시 재임베딩) |
| Celery | ✅ | 안정 (task 이름 고정) |

**마이그레이션**:
- 규칙: 버전 비교로 무조건 안전
- 기획서: `specs.title` 컬럼 추가 마이그레이션 (done)
- 임베딩: 모델 변경 시 전체 재색인 (scripts/seed_specs.py)

---

## 개선 로드맵

### Q2 2026 (이번)

- [ ] 보안 강화 (CRITICAL 3개)
- [ ] admin.py 분리
- [ ] CodeNode 파서
- [ ] Celery 모니터링
- 예상: 7주, 4명

### Q3 2026

- [ ] 테스트 커버리지 50% 이상
- [ ] Grafana 대시보드
- [ ] 레이트 제한
- 예상: 4주, 2명

### Q4 2026

- [ ] 권한 관리 (RBAC)
- [ ] 자동 확장 (K8s)
- [ ] 벡터 DB 마이그레이션 (필요시)
- 예상: 6주, 3명

---

## 관련 문서

- **RELIABILITY.md** — 배포 체크리스트
- **SECURITY.md** — 보안 정책
- **docs/dev_log.md** — 작업 이력
