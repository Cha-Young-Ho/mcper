# AGENTS.md — 에이전트 팀 구조

본 프로젝트는 **OpenAI Harness Engineering** 패러다임을 따르는 **에이전트 팀 기반 개발** 모델을 운영합니다.

---

## 팀 구성 및 역할

| 역할 | 에이전트 | 담당 | 모델 |
|------|---------|------|------|
| **프로젝트 관리** | @pm | 타당성·우선순위·리스크 | claude-sonnet-4-6 |
| **기획 및 설계** | @planner | 요구사항 문서화·기술 기획 | claude-sonnet-4-6 |
| **아키텍처·리뷰** | @senior | 설계 검증·코드 리뷰 | claude-sonnet-4-6 |
| **핵심 구현** | @coder | 코드 작성·모듈 개발 | claude-haiku-4-5 |
| **테스트 코드** | @tester | 테스트·QA 시나리오 | claude-haiku-4-5 |
| **인프라·배포** | @infra | 배포·성능·모니터링 | claude-sonnet-4-6 |
| **대용량 분석** | @archivist | 1000줄+ 파일 읽기·메모 | claude-haiku-4-5 |

---

## 협업 흐름

```
┌─────────────┐
│     @pm     │  ← 타당성 검토 + 우선순위 결정
└──────┬──────┘
       │
┌──────▼──────┐
│  @planner   │  ← 기획서 작성 (유저 스토리, QA, 아키텍처)
└──────┬──────┘
       │
┌──────▼──────┐
│   @senior   │  ← 설계 검증 (기술 결정, 리스크)
└──────┬──────┘
       │
    ┌──┴──┐
    │     │
┌───▼─┐ ┌─▼───┐
│@coder│ │@tester│  ← 병렬 진행: 구현 + 테스트
└───┬──┘ └──┬──┘
    │       │
    └───┬───┘
        │
    ┌───▼────┐
    │ @infra │  ← 배포 검수·성능 검증
    └────────┘
```

### 단계별 책임

1. **@pm** (프로젝트 관리자)
   - 요청 타당성 검토
   - 우선순위·일정 결정
   - 리스크 식별 (규제, 보안, 기술 부채)
   - `docs/exec-plans/active/` 에 승인 기록

2. **@planner** (기획자)
   - 유저 스토리 + 수용 기준 작성
   - 정상/엣지/실패 시나리오 정의
   - 기술 아키텍처·인터페이스 설계
   - 예상 작업량 추정
   - 결과물: `docs/product-specs/` + `docs/exec-plans/active/`

3. **@senior** (시니어 개발자)
   - 설계 기술 검증
   - 기존 코드·패턴과 정합성 확인
   - 성능·확장성·보안 검토
   - 코드 리뷰 (완성 후)
   - 결과물: `docs/design-docs/`

4. **@coder** (개발자)
   - 설계 기반 구현
   - 모듈·함수·테스트 스텁 작성
   - `@tester` 와 협력 (테스트 먼저)
   - 결과물: `app/`, `scripts/`

5. **@tester** (테스트 엔지니어)
   - 설계 기반 테스트 케이스 작성 (먼저!)
   - 엣지 케이스·에러 시나리오 포함
   - 통합 테스트·성능 테스트
   - @coder 와 병렬 진행
   - 결과물: `tests/`

6. **@archivist** (데이터 라이브러리언)
   - 대용량 파일(1000줄+) 읽기 전담
   - 메모 작성·컨텍스트 요약
   - 기존 로직·의존성 분석
   - 결과물: `.claude/archivist_notes/`

7. **@infra** (인프라 관리자)
   - 배포 환경 검증
   - 성능·모니터링 검수
   - 설정·보안 정책 확인
   - 결과물: `docs/RELIABILITY.md`, `infra/`

---

## 협업 규칙

### 필수 체크리스트

| 단계 | 담당 | 산출물 | 형식 |
|------|------|--------|------|
| 1️⃣ **요청 분석** | @pm | 리스크·우선순위 | `docs/exec-plans/active/{id}.md` |
| 2️⃣ **기획** | @planner | 기획서·WBS | `docs/product-specs/{id}.md` |
| 3️⃣ **설계** | @senior | 설계·결정 기록 | `docs/design-docs/{id}.md` |
| 4️⃣ **구현+테스트** | @coder + @tester | 코드+테스트 | `app/`, `tests/` (병렬) |
| 5️⃣ **배포 검수** | @infra | 성능·보안 | `docs/RELIABILITY.md` |
| 6️⃣ **완료 보고** | 담당 에이전트 | 작업 로그 | `docs/dev_log.md` (맨 위에 추가) |

### 단순 작업 (버그픽스, 작은 기능)

```
@coder → 설계 스킵 후 직접 구현
@tester → 같은 MR에 테스트 추가 (또는 별도)
@infra → 필요시만 배포 검수
```

### 컨텍스트 절약 규칙

- **파일 읽기 전** 추측 금지 (파일 존재 확인 필수)
- **변경 전** 현재 상태 읽기 필수
- **요청 없는 개선** 금지 (버그픽스도 범위 외 리팩토링 스킵)
- **응답은 간결하게** (작업만 보고, 이유 설명 불필요)

### 선호 추적

모든 에이전트가 **선호 변경 사항을 추적**:
- 파악된 스타일·선호는 `.agents/{역할}.md` 갱신
- 예: 우선순위, 코딩 패턴, 배포 정책 등

---

## 작업 완료 후 보고

**모든 에이전트가 작업 완료 후 아래를 수행**:

### 1. 로그 기록 (`docs/dev_log.md`)

맨 위에 새 항목 추가:

```markdown
## [날짜]: @[에이전트명] [작업 제목]

### 작업 내용
- 핵심 변경 3-5줄
- 파일: [file1.py], [file2.py]

### 판단 이유
**Why:** 왜 이렇게 했는가?
**Risk:** 예상되는 위험요소

### 결과
✅ 완료 / ⚠️ 부분 완료 / ❌ 보류

### 다음 단계
- 후속 에이전트 또는 의존성
```

### 2. 작성 기준

**다음 중 하나라도 해당하면 보고서 작성:**
- 파일 3개 이상 수정
- 로직 변경 (버그픽스 제외)
- 새 기능 추가
- 아키텍처 결정

**간단한 작업** (버그 1개, 라인 수정 <50):
- 보고서 불필요
- 커밋 메시지만 상세하게

---

## 문서 구조

```
AGENTS.md                  ← 본 파일 (팀 구조·협업 규칙)
ARCHITECTURE.md            ← 기술 아키텍처
docs/
├── design-docs/
│   ├── index.md          ← 설계 문서 목록
│   ├── core-beliefs.md   ← 핵심 설계 원칙
│   └── {feature}.md      ← 기능별 설계
├── exec-plans/
│   ├── active/           ← 진행 중인 계획
│   ├── completed/        ← 완료된 계획
│   └── tech-debt-tracker.md  ← 기술 부채 로그
├── product-specs/
│   ├── index.md          ← 기획서 목록
│   └── {feature}.md      ← 기능별 기획 (유저 스토리, QA)
├── references/
│   ├── design-system-reference-llms.txt
│   ├── nixpacks-llms.txt
│   └── uv-llms.txt
├── generated/
│   └── db-schema.md      ← DB 스키마 (자동 생성)
├── DESIGN.md             ← 설계 가이드
├── FRONTEND.md           ← 프론트엔드 관례
├── PLANS.md              ← 현재 진행 중인 계획 요약
├── PRODUCT_SENSE.md      ← 제품 철학
├── QUALITY_SCORE.md      ← 품질 메트릭
├── RELIABILITY.md        ← 배포·성능·모니터링
├── SECURITY.md           ← 보안 정책
└── dev_log.md            ← 작업 로그 (최신순)
MEMORY.md                  ← 컨텍스트 메모리 인덱스
CLAUDE.md                  ← 프로젝트 지침 (기본)
```

---

## 도구 및 명령어

### MCP 도구
```
/get_global_rule          ← 에이전트 규칙 조회
/publish_global_rule      ← 전역 규칙 갱신
/upload_spec_to_db        ← 기획서 업로드
/search_spec_and_code     ← 기획·코드 하이브리드 검색
```

### 에이전트 호출
```
@pm <요청>                ← 프로젝트 관리자
@planner <요청>           ← 기획자
@senior <요청>            ← 시니어 개발자
@coder <요청>             ← 개발자
@tester <요청>            ← 테스트 엔지니어
@infra <요청>             ← 인프라 관리자
@archivist <요청>         ← 데이터 라이브러리언
```

---

## 관련 문서

- **CLAUDE.md** — 기본 지침 (모든 에이전트 필독)
- **ARCHITECTURE.md** — 기술 아키텍처 상세
- **docs/DESIGN.md** — 설계 가이드
- **docs/RELIABILITY.md** — 배포 체크리스트
- **docs/SECURITY.md** — 보안 정책
- `.agents/{역할}.md` — 각 에이전트 상세 지침
- `.claude/archivist_notes/` — 대용량 파일 메모
