# CLAUDE.md — MCPER 프로젝트 하네스

**FastAPI + MCP 서버.** 기획서 RAG, 버전 관리 규칙/스킬, 코드 그래프 인덱싱을 LLM 에이전트에 서빙.

---

## 기술 스택

Python 3.13 · FastAPI · FastMCP(Streamable HTTP) · PostgreSQL(pgvector) · Redis · Celery
임베딩: sentence-transformers(local) / OpenAI / Bedrock (pluggable)

---

## 에이전트 팀

| 트리거 | 역할 | 모델 | 핵심 |
|--------|------|------|------|
| `@pm` | 프로젝트 관리자 | sonnet | 타당성·범위·절차 결정. 코드 안 씀. |
| `@planner` | 기획자 | sonnet | 유저스토리·수용기준·QA 시나리오 |
| `@senior` | 시니어 개발자 | sonnet | 아키텍처·API/DB 스펙. 코드 안 씀. |
| `@coder` | 코드 작업자 | haiku | 설계 기반 구현. @tester와 병렬. |
| `@tester` | 테스트 작업자 | haiku | 단위·통합·엣지 테스트. @coder와 병렬. |
| `@infra` | 인프라 관리자 | sonnet | 보안·성능·배포 최종 검수 |
| `@archivist` | 라이브러리언 | haiku | 1000줄+ 파일 읽기→메모. 의사결정 안 함. |
| `@compounder` | Compound 엔지니어 | sonnet | 실수/피드백 수집→스킬 발행. 코드 안 씀. |

### 협업 흐름

```
@pm → @planner → @senior → @coder + @tester (병렬) → @infra → @compounder
```

단순 작업(버그픽스): 중간 단계 생략 가능.
1000줄+ 파일 또는 5개+ 동시 분석: @archivist 먼저. 시간 압박 시 스킵.

---

## 공통 규칙

1. **컨텍스트 절약** — 읽기 전 추측 금지, 변경 전 확인, 요청 없는 개선 금지
2. **문서화** — 큰 작업(3파일+/로직변경/신기능) 끝나면 `docs/dev_log.md` 맨 위에 추가
3. **선호 추적** — 파악된 스타일/선호는 `.agents/{역할}.md` 갱신
4. **협업** — 모호한 요청은 확인 후 진행, 선행 작업은 `dev_log.md` 최신 항목 먼저 읽기
5. **No Manual Code** — 프로덕션 코드는 에이전트만 작성. 사용자는 설정·문서·요청만.
6. **Compound 기록** — 작업 중 실수/피드백/수정 발생 시 보고서 Compound Records 섹션에 기록. 작업 전 `search_skills`로 compound-* 스킬 확인.

---

## 디렉터리 구조

```
app/
├── main.py              # FastAPI lifespan + 라우터
├── mcp_app.py           # FastMCP 인스턴스 + 도구 등록
├── config.py            # YAML + env 부트스트랩
├── db/                  # SQLAlchemy 모델 (Spec, Rules, Skills, Auth)
├── services/            # 비즈니스 로직 (search, rules, skills, embeddings)
├── tools/               # MCP 도구 (documents, rules, skills, rag, data)
├── routers/             # Admin REST 라우터
├── worker/              # Celery 태스크
├── templates/           # Jinja2 어드민 UI
└── static/              # CSS/JS
infra/                   # Docker, K8s
docs/                    # 설계·기획·운영 문서
.agents/                 # 에이전트별 상세 가이드
```

---

## 핵심 설정

| 환경변수 | 기본값 | 용도 |
|---------|--------|------|
| `DATABASE_URL` | — | PostgreSQL |
| `CELERY_BROKER_URL` | — | Redis (없으면 동기 폴백) |
| `EMBEDDING_PROVIDER` | `local` | local/openai/bedrock |
| `EMBEDDING_DIM` | `384` | 벡터 차원 |
| `MCPER_AUTH_ENABLED` | `false` | JWT/OAuth |
| `MCPER_ADMIN_ENABLED` | `true` | 어드민 UI |
| `MCPER_MCP_ENABLED` | `true` | MCP 엔드포인트 |

설정 우선순위: 환경변수 > config.{env}.yaml > config.yaml > 기본값

---

## MCP 도구 요약

| 카테고리 | 주요 도구 |
|---------|----------|
| 기획서 | `upload_document`, `search_documents`, `find_historical_reference` |
| 규칙 | `get_global_rule`, `publish_*_rule`, `check_rule_versions` |
| 스킬 | `get_global_skill`, `publish_*_skill` |
| 코드 | `push_code_index`, `analyze_code_impact` |

규칙 3계층: Global → Repository(URL 패턴) → App. 섹션별 독립 버전 관리.

---

## 문서 참고

| 문서 | 경로 |
|------|------|
| 아키텍처 상세 | `ARCHITECTURE.md` |
| 설계 원칙 | `docs/design-docs/core-beliefs.md` |
| 보안 정책 | `docs/SECURITY.md` |
| 운영·배포 | `docs/RELIABILITY.md` |
| 프론트엔드 | `docs/FRONTEND.md` |
| 제품 철학 | `docs/PRODUCT_SENSE.md` |
| 로드맵 | `docs/PLANS.md` |
| 작업 로그 | `docs/dev_log.md` |
| 에이전트 가이드 | `.agents/{역할}.md` |
| 보고서 템플릿 | `.agents/report_template.md` |
