# docs/design-docs/core-beliefs.md — 핵심 설계 원칙

---

## 설계 철학 (Design Philosophy)

### 1. 에이전트 중심 (Agent-Centric)

**원칙**: 모든 기능은 **에이전트 도구 호출**을 중심으로 설계

**의미**:
- 에이전트가 독립적으로 기획서 검색, 규칙 조회, 코드 분석 가능
- 수동 개입 최소화
- 에이전트 학습 곡선 낮음

**구현 예**:
```python
# MCP 도구
async def search_spec_and_code(query: str, app_target: str) -> dict:
    \"\"\"기획서 + 코드 하이브리드 검색.\"\"\"
    # 에이전트가 호출 → 즉시 결과 반환
```

---

### 2. 단순함 (Simplicity)

**원칙**: 필요한 것만, 정확히

**의미**:
- 과도한 추상화 회피
- 명확한 인터페이스
- 문서로 명시된 제약

**반례** (피해야 할 것):
- 모든 경우를 대비한 범용 프레임워크
- 깊은 상속 (다형성)
- 암묵적 동작

---

### 3. 감시 추적 (Auditability)

**원칙**: 모든 변경을 기록하고 역추적 가능하게

**의미**:
- Append-only 규칙 (수정/삭제 금지)
- 타임스탬프 + 버전
- 감사 로그 (누가, 언제, 뭘 바꿈)

**구현 예**:
```sql
-- global_rule_versions
id | version | body | created_at
1  | 1       | \"global rule v1\" | 2026-03-01 10:00
2  | 2       | \"global rule v2\" | 2026-03-02 14:30
```

---

### 4. 인적 오류 방지 (Fail-Safe)

**원칙**: 사용자 실수를 자동으로 방지

**의미**:
- 확인 없이 위험한 작업 불가
- 기본값은 안전한 선택지
- 되돌리기 (undo) 가능성

**예**:
```python
# 규칙 삭제: 불가능 (append-only)
DELETE FROM global_rule_versions
# → 에러: \"규칙은 삭제할 수 없습니다\"

# 기획서 삭제: 확인 필요
DELETE FROM specs WHERE id = ?
# → UI: \"정말 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.\"
```

---

## 아키텍처 원칙

### 5. 모듈 독립성 (Module Independence)

**원칙**: 각 모듈은 독립적으로 테스트·배포 가능

**구현**:
```
app/
├── db/           # 데이터 계층 (ORM, 스키마)
├── services/     # 비즈니스 로직 (검색, 임베딩)
├── routers/      # HTTP 엔드포인트
├── tools/        # MCP 도구
└── worker/       # 비동기 작업

각 계층은 하위 계층에만 의존 (역의존 금지)
```

---

### 6. 암묵적 동작 금지 (No Magic)

**원칙**: 모든 동작이 명시적이고 문서화됨

**의미**:
- 주석 없이 이해되는 코드
- 숨겨진 부작용 없음
- 설정 오버라이드는 명확

**반례**:
```python
# ❌ 나쁜 예 (암묵적)
class Spec(Base):
    @property
    def chunks(self):  # 선택적으로 로드
        if self._chunks is None:
            self._chunks = db.query(SpecChunk)
        return self._chunks

# ✅ 좋은 예 (명시적)
spec = db.query(Spec).options(selectinload(Spec.chunks)).first()
```

---

### 7. 명확한 데이터 흐름 (Clear Data Flow)

**원칙**: 데이터의 출처와 변환 과정이 명확

**구현**:
```
클라이언트 (JSON) 
  ↓ (Pydantic 검증)
요청 모델
  ↓ (비즈니스 로직)
DB 엔티티
  ↓ (쿼리 응답)
응답 모델
  ↓ (JSON 직렬화)
클라이언트 (JSON)
```

각 단계에서 타입이 명확하고, 변환이 명시적

---

## 성능 원칙

### 8. 비동기 우선 (Async-First)

**원칙**: CPU/IO 집약적 작업은 비동기로

**구현**:
- FastAPI: async/await
- Celery: 워커 분리
- 임베딩: 배치 처리

---

### 9. 캐싱 전략 (Caching Strategy)

**원칙**: 읽기 작업은 캐시, 쓰기는 즉시

**구현**:
```python
# 규칙 조회: 캐시 (버전 변경 시 무효화)
rule = cache.get(f\"rule:{app_name}:{version}\")
if not rule:
    rule = db.query(...)
    cache.set(...)

# 규칙 발행: 즉시 DB (캐시 무효화)
db.insert(new_rule)
cache.delete(f\"rule:{app_name}:*\")
```

---

## 보안 원칙

### 10. 최소 권한 (Principle of Least Privilege)

**원칙**: 각 역할은 최소한의 권한만

**구현** (향후):
```
어드민: 규칙 발행, 기획서 삭제
에이전트: 규칙 조회, 기획서 검색 (읽기만)
워커: 색인만 (쓰기 제한)
```

---

### 11. 기본 보안 (Secure by Default)

**원칙**: 보안 설정이 기본값

**구현**:
- Host/Origin 검증 활성화 (비활성화는 명시)
- CSRF 토큰 필수
- HTTPS 권장
- 환경 변수로 민감정보 분리

---

## 개발 원칙

### 12. 테스트 우선 (Test-Driven)

**원칙**: 기능 구현 전 테스트 작성

**단계**:
1. 테스트 작성 (실패)
2. 최소 구현 (통과)
3. 리팩토링 (개선)

---

### 13. 문서 자동화 (Documentation as Code)

**원칙**: 코드와 문서를 동기화

**구현**:
```python
@app.post(\"/api/specs\")
\"\"\"기획서 생성.

Args:
    title: 기획서 제목
    content: 기획서 본문

Returns:
    {\"id\": 123, \"created_at\": \"2026-03-30T...\"}
\"\"\"
async def create_spec(req: CreateSpecRequest):
    # OpenAPI 자동 생성
    ...
```

---

## 의사결정 기준

### 기술 선택

**기준** (우선순위):
1. 안정성 (버그 적음, 커뮤니티 활발)
2. 성능 (응답 시간, 메모리)
3. 개발 생산성 (코드 짧음, 배우기 쉬움)
4. 운영 복잡도 (배포, 모니터링)

**예**:
- FastAPI: 안정성 (Starlette) + 생산성 (async) ✅
- SQLAlchemy: 안정성 (오래됨) + 유연성 ✅
- Celery: 안정성 + 복잡도 (trade-off) ⚠️

---

## 관련 문서

- **docs/DESIGN_SUMMARY.md** — 기술 설계 종합 요약
- **ARCHITECTURE.md** — 기술 세부사항
- **docs/dev_log.md** — 작업 로그 (결정 이유)
"