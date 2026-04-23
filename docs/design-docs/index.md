# docs/design-docs/index.md — 설계 문서 인덱스

**용도**: 주요 기술 결정, 아키텍처 검토, 설계 검증 기록

---

## 설계 문서 목록

### 핵심 설계

- **[core-beliefs.md](core-beliefs.md)** — 프로젝트의 핵심 설계 원칙
  - MCP 중심 협업
  - Append-only 규칙
  - 벡터 + FTS 하이브리드

### 기능별 설계

- **MCP 도구 설계** (계획)
  - RAG 도구 (search, push)
  - 규칙 도구 (get, publish, check_versions)
  - 영향도 분석

- **임베딩 아키텍처** (계획)
  - Factory 패턴
  - 다중 프로바이더 (로컬, OpenAI, Bedrock)
  - 차원 일치성

- **검색 시스템** (계획)
  - 벡터 검색 (Postgres pgvector)
  - FTS 검색 (Postgres full-text)
  - RRF 병합 (Reciprocal Rank Fusion)

- **Celery 아키텍처** (계획)
  - 태스크 설계
  - 재시도 정책
  - 모니터링

- **인증 시스템** (계획)
  - HTTP Basic (어드민)
  - JWT 토큰
  - OAuth2 (Google, GitHub)

### 아키텍처 결정 기록 (ADR)

| ID | 제목 | 상태 |
|----|----|------|
| AD-001 | 단일 FastAPI vs 마이크로서비스 | ✅ 결정 |
| AD-002 | PostgreSQL pgvector vs 벡터 전용 DB | ✅ 결정 |
| AD-003 | Append-only 규칙 vs 모듈화 규칙 | ✅ 결정 |
| AD-004 | Streamable HTTP vs SSE vs gRPC | ✅ 결정 |
| AD-005 | Celery vs APScheduler | 계획 중 |
| AD-006 | Jinja2 vs React for Admin UI | 계획 중 |

상세: [core-beliefs.md](core-beliefs.md)

---

## 설계 승인 프로세스

```
설계 작성 (@senior)
  ↓
Arkad 리뷰 (@coder, @tester 입력)
  ↓
Risk 검토 (@infra)
  ↓
최종 승인 (@pm) → dev_log 기록
  ↓
구현 (@coder, @tester)
```

---

## 설계 문서 템플릿

```markdown
# [기능명] 설계

## 개요
[간단한 설명]

## 요구사항
- 기능 1
- 기능 2

## 아키텍처
[다이어그램 + 텍스트]

## 인터페이스
[API, 입출력 예시]

## 데이터 모델
[ERD, 스키마]

## 성능
[응답 시간, 확장성]

## 보안 고려
[위협, 대응]

## 테스트 전략
[단위, 통합, E2E]

## 리스크
[리스크, 대응 계획]

## 승인
- @pm: [ ] 승인
- @senior: [ ] 승인
- @infra: [ ] 승인
```

---

## 관련 문서

- **core-beliefs.md** — 핵심 설계 원칙
- **docs/dev_log.md** — 작업 로그 (설계 결정 포함)
- **ARCHITECTURE.md** — 기술 세부사항
"