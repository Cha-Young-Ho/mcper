# docs/DESIGN.md — 설계 가이드

프로젝트의 **설계 철학**과 **아키텍처 결정 기록**을 담습니다.

---

## 핵심 설계 원칙

### 1. **MCP 중심 에이전트 협업**

**원칙**: 클라이언트(Cursor/Claude) ↔ 서버 간 도구 기반 통신

**근거**:
- 에이전트가 도구 호출로 정보 검색 + 수정 가능
- 코드베이스 변경 없이 규칙·기획서 업데이트
- 버전 관리 (규칙은 append-only, 기획서는 타임스탬프)

**구현**:
- FastMCP (async 도구)
- Streamable HTTP (실시간 응답)
- Host/Origin 검증 (보안)

---

### 2. **벡터 + FTS 하이브리드 검색**

**원칙**: 의미론적 검색(벡터) + 키워드 검색(FTS) + RRF 병합

**근거**:
- 벡터만: "관련 문제"도 높은 유사도 (거짓 양성)
- FTS만: "임베딩"이라는 단어를 못 찾으면 검색 실패
- 하이브리드: 두 방식 상호 보완

**구현**:
```sql
-- 벡터 검색
SELECT * FROM spec_chunks
WHERE (embedding <-> query_embedding) < 0.5

-- FTS 검색
SELECT * FROM spec_chunks
WHERE content @@ to_tsquery('korean', query)

-- RRF (Reciprocal Rank Fusion)
SELECT id, (1/(32 + rank_v) + 1/(32 + rank_t)) AS score
FROM (벡터 순위 + 텍스트 순위)
```

---

### 3. **Append-Only 규칙 시스템**

**원칙**: 규칙 수정 없음, 새 버전 추가만

**근거**:
- 감사 추적 (누가, 언제, 어떤 규칙)
- 버전 롤백 가능
- 클라이언트가 로컬 캐시 무효화 가능

**구현**:
```python
# ❌ 수정 불가
UPDATE global_rule_versions SET body = '...' WHERE version = 5

# ✅ 새 버전 추가
INSERT INTO global_rule_versions (version, body, created_at)
VALUES (6, '...', now())
```

테이블:
- `global_rule_versions` (version PK)
- `repo_rule_versions` (pattern + version PK)
- `app_rule_versions` (app_name + version PK)

---

### 4. **Celery 비동기 색인**

**원칙**: 임베딩·청크 생성은 백그라운드에서

**근거**:
- API 응답 지연 없음 (기획서 업로드 100ms 이내)
- CPU 집약적 임베딩 워커 분리
- 확장성 (워커 수 증가로 처리량 증가)

**구현**:
```
POST /mcp upload_spec
├─→ INSERT specs 테이블 (즉시)
└─→ Celery 큐 (index_spec task)
    └─→ 워커 (청크, 임베딩, INSERT spec_chunks)
```

큐 깊이 모니터링:
- `/health/rag` 엔드포인트로 큐 길이 조회
- 대시보드에서 대기 시간 시각화

---

### 5. **다중 임베딩 프로바이더 지원**

**원칙**: 프로바이더 의존성 제거

**근거**:
- 로컬 (sentence-transformers): 무료, 느림, 프라이빗
- OpenAI: 빠름, 비용, 외부 API
- Bedrock: AWS 네이티브, 엔터프라이즈

**구현**:
```python
class EmbeddingBackend(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

# 구현체
LocalBackend()    # 기본
OpenAIBackend()   # config.yaml
BedrockBackend()  # config.yaml
```

factory.py에서 선택:
```python
backend = EmbeddingFactory.create(provider="openai")
```

---

### 6. **HTTP Basic + CSRF 중심 보안**

**원칙**: 어드민 UI는 HTTP Basic + CSRF, MCP는 Host 검증

**근거**:
- HTTP Basic: 간단, 기존 인프라 (ALB, nginx)
- CSRF: POST/PUT/DELETE 토큰 검증
- Host 검증: MCP는 오픈 프로토콜이므로 Host 헤더 확인

**구현**:
```python
# 어드민 (HTTP Basic)
@app.get("/admin")
@require_http_basic("admin", "password")
def admin_dashboard(): ...

# MCP (Host 검증)
@asgi_middleware
def mcp_host_gate(scope, receive, send):
    if scope["path"].startswith("/mcp"):
        host = scope["headers"].get("host")
        if host not in allowed_hosts:
            raise HTTPException(421, "Invalid Host")
```

---

### 7. **타입 안전성 (Pydantic V2)**

**원칙**: 모든 입력/출력을 Pydantic 모델로 검증

**근거**:
- 런타임 타입 검사
- 자동 JSON 직렬화
- 에러 메시지 명확성

**구현**:
```python
class UploadSpecRequest(BaseModel):
    content: str = Field(..., min_length=10)
    app_target: str
    base_branch: str = "main"
    related_files: list[str] = []

# MCP 도구
async def upload_spec_to_db(request: UploadSpecRequest) -> dict:
    # request는 이미 검증됨
    ...
```

---

## 주요 아키텍처 결정

### AD-001: 단일 FastAPI 앱 vs 마이크로서비스

**결정**: 단일 FastAPI + 워커 분리

**근거**:
- 현재 규모(기획서 1000+, 규칙 수십 개)에서 필요 없음
- 웹 + 워커는 배포로 분리 가능
- 작은 팀이 관리 쉬움

**대안**:
- ❌ 마이크로서비스: 복잡, 운영 부담
- ✅ 단일 + 비동기: 간단, 확장 가능

**롤백 시나리오**: 트래픽 급증 시 워커 분리 검토

---

### AD-002: PostgreSQL 단일 벡터 DB vs 벡터 전용 DB

**결정**: PostgreSQL pgvector 확장

**근거**:
- 기존 데이터(규칙, 기획서)와 벡터 함께 저장
- 트랜잭션 일관성 보장
- ACID 속성

**대안**:
- ❌ Pinecone: 벡터만, 메타데이터 제한
- ❌ Weaviate: 별도 인프라
- ✅ pgvector: 모든 데이터 한곳

**스케일링**: 500만+ 벡터 필요 시 전용 DB 검토

---

### AD-003: Append-Only 규칙 vs 모듈화 규칙

**결정**: Append-only 버전 관리

**근거**:
- 단순성 (INSERT만, UPDATE/DELETE 금지)
- 감사 추적 (변경 이력 완전 보존)
- 클라이언트 캐시 무효화 (버전 비교)

**대안**:
- ❌ 모듈화: 의존성 추적 복잡
- ❌ 실시간 수정: 감사 흔적 없음
- ✅ Append-only: 투명성, 단순성

**한계**: 규칙 파일이 매우 커질 경우 (년 단위) 아카이브 검토

---

### AD-004: MCP Streamable HTTP vs SSE vs gRPC

**결정**: Streamable HTTP (Cursor 우선 지원)

**근거**:
- Cursor의 기본 MCP 프로토콜
- HTTP/2 스트리밍 (SSE보다 빠름)
- 브라우저·모바일 호환성

**대안**:
- ❌ SSE: 느림, 순방향만
- ❌ gRPC: 클라이언트 지원 부족
- ✅ Streamable HTTP: 표준, 빠름

---

## 성능 및 확장성

### 기준선

| 메트릭 | 목표 | 달성 여부 |
|--------|------|---------|
| 기획서 업로드 응답 | < 200ms | ✅ (INSERT만, 색인 async) |
| 하이브리드 검색 | < 500ms (1M 벡터) | ✅ (pgvector + FTS) |
| 규칙 조회 | < 100ms | ✅ (캐시 없이 10-30ms) |
| MCP 스트림 | 실시간 | ✅ (HTTP/2) |
| 동시 클라이언트 | 10+ (로컬) | ⚠️ (워커 병렬도 높음) |

### 확장 전략

**단계 1: 단일 서버 (현재)**
- FastAPI (web) + Celery (worker) 같은 인스턴스
- PostgreSQL: 단일 인스턴스, 5G 이내
- Redis: 단일 인스턴스

**단계 2: 워커 분리** (트래픽 ↑ 50%)
- web: 1-2 인스턴스 (ALB)
- worker: 2-4 인스턴스 (큐 깊이 모니터링)
- PostgreSQL: 읽기 복제본 추가

**단계 3: 벡터 전용 DB** (벡터 500만+ 개)
- Milvus / Pinecone으로 마이그레이션
- PostgreSQL: 메타데이터만 유지

---

## 보안 정책

### 인증

**기본 (현재)**:
- HTTP Basic (어드민 UI)
- CSRF 토큰 (POST)

**선택 (MCPER_AUTH_ENABLED=true)**:
- JWT 토큰 (30분 TTL)
- OAuth2 (Google, GitHub)

### 암호화

- ✅ 비밀번호: bcrypt (rounds=12)
- ✅ JWT: HS256 (secret_key)
- ✅ TLS/HTTPS: ALB 권장

### 감시

- ✅ MCP Host 검증 (DB 화이트리스트)
- ✅ 규칙 감시 (append-only 이력)
- ⚠️ 레이트 제한 (미구현)
- ⚠️ WAF (ALB/Cloudflare 권장)

---

## 관련 문서

- **ARCHITECTURE.md** — 기술 세부사항
- **docs/SECURITY.md** — 보안 정책 상세
- **docs/RELIABILITY.md** — 배포 체크리스트
