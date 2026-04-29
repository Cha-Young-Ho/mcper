# 임베딩 제공자 외부화 설계 (L04 / L05)

> 근거 — `docs/audit_2026-04-29.md` L04 / L05
> 상태 — 설계 초안 (실 배포는 별도 PR)

---

## 1. 현 상태

### 1.1 구현

- **로컬 백엔드** — `app/services/embeddings/backends/local.py:11-41`
  - `LocalSentenceTransformerBackend._model_or_load()` (L18-L29) 가 `sentence-transformers` 를
    lazy import 하고 `SentenceTransformer(self._cfg.local_model)` 로 모델을 로드.
  - 기본 모델: `sentence-transformers/all-MiniLM-L6-v2` (`app/config.py:82`,
    `config.example.yaml:49`).
- **전역 싱글톤** — `app/services/embeddings/core.py:11-18`
  - 모듈 전역 `_backend: EmbeddingBackend | None` 을 `configure_embedding_backend()` 가
    주입. `get_embedding_backend()` 에서 없으면 `settings.embedding` 으로 조립.
- **팩토리** — `app/services/embeddings/factory.py`
  - `provider ∈ { local, openai, localhost, bedrock }` 중 선택
    (`app/config.py:26` Literal).
- **벡터 차원** — `EMBEDDING_DIM=384`. pgvector 컬럼이 `vector(384)` 로 고정:
  - `skill_chunks.embedding` (`database.py:350`), `rule_chunks.embedding` (L380),
    `workflow_chunks.embedding` (L412), `doc_chunks.embedding` (L504),
    `spec_chunks`, `code_nodes` (HNSW 인덱스 포함, L667·L706).

### 1.2 문제

- **웹 프로세스 메모리 폭증** — `all-MiniLM-L6-v2` + torch 런타임 ≈ 400~500 MB.
  인스턴스 수 N 만큼 선형 증가 (`infra/docker/docker-compose.yml:71-78` 주석도
  "~500MB 이상" 명시, worker 에는 2g 상한).
- **싱글톤 의존** — 모듈 전역 `_backend` 로 인해 테스트/재구성 시 명시 재주입 필수.
  의존성 주입으로 바꾸면 자연스럽게 프로세스 외부화 가능.
- **호환성 제약** — pgvector 컬럼이 384d 에 묶여있음 + HNSW 인덱스 동봉
  (`vector_cosine_ops`). 다른 차원의 제공자로 바꾸면 **전체 재인덱싱 필수**.

### 1.3 대안 제공자 일람

| 제공자 | 모델 | 차원 | 비고 |
|--------|------|------|------|
| OpenAI | `text-embedding-3-small` | 1536 | 저렴·빠름, 외부 전송 |
| OpenAI | `text-embedding-3-large` | 3072 | 품질 최상, 비용 3배 |
| Bedrock | `amazon.titan-embed-text-v1` | 1536 | AWS 내부, 기존 Bedrock 경로 재활용 |
| Voyage | `voyage-3-lite` | 512 | 다국어 강점, 외부 API |
| 로컬 Ollama | `nomic-embed-text` | 768 | self-host, OpenAI 호환 |
| 로컬 vLLM | 다수 | 가변 | 고성능 자체 호스팅 |
| 로컬 sidecar | `all-MiniLM-L6-v2` | **384** | 기존 벡터와 호환 |

---

## 2. 선택 기준

1. **데이터 민감도** — 기획서/코드 스니펫이 외부 API 로 전송 가능한가.
2. **비용** — 토큰 단가, 예상 월 호출 수 × 평균 토큰.
3. **레이턴시** — RAG 쿼리 p95. 외부 API 는 왕복 네트워크 비용.
4. **차원 수** — 384 유지면 재인덱싱 불필요, 바꾸면 전체 재인덱싱 + 인덱스
   재구축 필요.
5. **정확도** — 도메인에 한국어·영어 혼재 (기획서+코드). 다국어 강한 모델 유리.
6. **운영 부담** — 모델 배포·업데이트·스케일 방식.

---

## 3. 추천 시나리오 3안

### A안 — 로컬 Ollama sidecar + `nomic-embed-text` (768d)

- self-host 유지, 외부 전송 없음.
- Ollama 컨테이너 이미 `docker-compose.yml:121-128` 에 `local-embed` 프로파일로 존재.
- `provider=localhost` 로 전환 (OpenAI 호환 게이트웨이).
- **차원 768 → 재인덱싱 필요**.

### B안 — Bedrock `titan-embed-text-v1` (1536d)

- `provider=bedrock` 경로 이미 구현 (`factory.py:46`).
- AWS 계정·키 운영 전제. 데이터는 Bedrock 리전으로 전송.
- **차원 1536 → 재인덱싱 필요**.

### C안 (추천 1순위) — 384d sentence-transformers 를 전용 sidecar 컨테이너로 분리

- 기존 `all-MiniLM-L6-v2` 를 별도 컨테이너에 격리. 웹 프로세스에서는 HTTP
  호출만.
- **차원 384 유지 → 재인덱싱 불필요**.
- 웹 프로세스 메모리 회수 (500MB × N → sidecar 1개).
- 스케일 독립 (web 은 N 개, embed 는 1~2 개 고정).

---

## 4. C안 상세 — 임베딩 sidecar

### 4.1 신규 컨테이너 `spec-mcp-embed`

- 베이스: `python:3.13-slim` + `sentence-transformers` + `fastapi` + `uvicorn`.
- 단일 엔드포인트 `POST /embed` — `{"texts": ["..."]}` → `{"vectors": [[...]]}`.
- 헬스체크 `GET /health`.
- 모델 사전 로드(워밍업) 후 준비 상태 리턴.

### 4.2 웹 측 변경

- 신규 백엔드 `SidecarEmbeddingBackend` 를 `app/services/embeddings/backends/`
  에 추가 (OpenAI 호환 게이트웨이 패턴과 유사).
- `factory.py` 에 `provider == "sidecar"` 분기 추가.
- 기존 `localhost` 분기(`OpenAICompatibleBackend`) 를 재활용하고 sidecar 가 OpenAI
  호환 `/v1/embeddings` 만 뚫어도 충분 — 별도 구현 최소화 가능.
- 웹 이미지에서 `sentence-transformers`·`torch` 의존성 제거 → 이미지 용량 대폭 감소.

### 4.3 docker-compose 예시

```yaml
services:
  embed:
    image: spec-mcp-embed:local
    build:
      context: ../..
      dockerfile: Dockerfile.embed
    environment:
      - EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
    restart: unless-stopped
    deploy:
      resources:
        limits: { memory: 1g }
        reservations: { memory: 512m }
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 60s  # 모델 로드 시간 고려

  web:
    environment:
      - EMBEDDING_PROVIDER=sidecar
      - EMBEDDING_ENDPOINT=http://embed:8000/embed
    depends_on:
      embed:
        condition: service_healthy
```

### 4.4 환경변수

| 변수 | 기본 | 용도 |
|------|------|------|
| `EMBEDDING_PROVIDER` | `local` | `sidecar` 로 전환 |
| `EMBEDDING_ENDPOINT` | — | sidecar URL |
| `EMBEDDING_TIMEOUT_SEC` | `30` | HTTP 타임아웃 |

---

## 5. 마이그레이션 단계 (A / B 안 — 차원 변경 시)

기존 벡터와 호환 안 될 때 무중단 전환:

1. **병렬 저장** — 각 `*_chunks` 테이블에 `embedding_v2 vector(N)` 컬럼 추가.
   쓰기 경로에서 구·신 모두 채움.
2. **백필** — Celery 대량 태스크로 기존 행을 배치 재임베딩 (`embedding_v2` 채움).
3. **쿼리 플래그** — `USE_V2=true` 스테이징 배포 후 검색 품질·레이턴시 비교.
4. **기본 전환** — 플래그 기본값 true, 충분한 관측 후 구 컬럼·인덱스 drop.

---

## 6. 롤백

- **C안** — `EMBEDDING_PROVIDER=local` 로 환경변수 원복. 벡터 호환 유지되므로
  즉시 복귀.
- **A / B안** — 구 컬럼을 아직 보존 중이면 쿼리 플래그만 원복. drop 이후라면
  인덱스 재구축 + 백필 재수행 필요 — drop 은 충분한 관측 후에만.

---

## 7. 작업 견적

| 항목 | 공수 |
|------|------|
| C안 — Dockerfile + FastAPI 래퍼 + sidecar 백엔드 + 통합 | 1일 |
| A / B안 — 위 + 컬럼 추가 + 백필 태스크 + 플래그 쿼리 | 3~4일 |

---

## 8. 오픈 질문

- Bedrock 운영 계정의 임베딩 모델 쿼터·키 확보 가능한가.
- 외부 API (OpenAI·Voyage) 로 기획서/코드 청크 전송이 보안 정책상 허용되는가.
- C안 sidecar 를 GPU 로 돌릴 필요가 있는가 (현재 트래픽에서는 CPU 로 충분할 가능성이 높음).
- 재인덱싱 수행 시 서비스 영향 — 읽기 쪽 캐시 / 읽기 전용 세션으로 우회 가능한가.
