#!/usr/bin/env python3
"""Seed adventure app harness data: skills (global/repo/app) + app rules.

Run from repo root inside Docker:
    docker compose exec web python scripts/seed_adventure_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.database import init_db, SessionLocal  # noqa: E402
from app.services.versioned_skills import (  # noqa: E402
    publish_global_skill,
    publish_repo_skill,
    publish_app_skill,
)
from app.services.versioned_rules import publish_app  # noqa: E402

# ---------------------------------------------------------------------------
# Harness source directory (mounted via docker volume)
# ---------------------------------------------------------------------------
ADVENTURE_ROOT = ROOT  # In Docker, /app is the mcper repo root
# The adventure harness files are at a different location on the host.
# We'll embed the content directly since Docker doesn't mount stz-game-service.

# ---------------------------------------------------------------------------
# Global Skills — 모든 프로젝트에 공통 적용
# ---------------------------------------------------------------------------

GLOBAL_SKILL_MCP_USAGE = """\
# MCPER MCP 서버 사용 가이드

이 MCP 서버는 프로젝트의 규칙(Rules), 스킬(Skills), 기획서(Documents)를 중앙 관리합니다.

---

## 초기화 절차 (프로젝트 연결 후 최초 1회)

1. `config.dev.ini` 또는 `config.ini`에서 `[Global] > app_name` 확인
2. `get_global_rule(app_name="확인된_값", origin_url="git remote -v origin URL")` 호출 → 행동 지침 로드
3. `get_global_skill(app_name="확인된_값", origin_url="...")` 호출 → 스킬 로드
4. `check_rule_versions` → 버전 비교, 최신 아니면 재호출

---

## 도구 카탈로그

### 기획서
| 도구 | 용도 |
|------|------|
| `search_documents` | 키워드/주제로 기획서 검색 (벡터+FTS 하이브리드) |
| `upload_document` | 기획서 1건 DB 저장 (자동 청킹+임베딩) |
| `find_historical_reference` | 기획서 초안으로 유사 과거 기획 비교 |

### 규칙 (Rules) — 반드시 따라야 하는 행동 지침
| 도구 | 용도 |
|------|------|
| `get_global_rule` | 규칙 로드 (Global + Repo + App 3계층) |
| `check_rule_versions` | 로컬 vs 서버 버전 비교 |
| `publish_app_rule` | 앱별 규칙 발행 |
| `publish_repo_rule` | 레포별 규칙 발행 |

### 스킬 (Skills) — 시스템 이해를 위한 참고 자료
| 도구 | 용도 |
|------|------|
| `get_global_skill` | 스킬 로드 (Global + Repo + App 3계층) |
| `list_skill_sections` | 등록된 스킬 카테고리 목록 |
| `publish_app_skill_tool` | 앱별 스킬 발행 |
| `publish_repo_skill_tool` | 레포별 스킬 발행 |

### 코드 분석
| 도구 | 용도 |
|------|------|
| `push_code_index` | 코드 심볼 그래프 인덱싱 |
| `analyze_code_impact` | 코드 변경 영향 분석 |

---

## 도구 선택 기준

| 상황 | 사용할 도구 |
|------|------------|
| "기획서 참고해서 구현해줘" | `search_documents` → 관련 기획서 확인 → 구현 |
| "과거에 비슷한 기획 있었어?" | `find_historical_reference` |
| "프로젝트 규칙 알려줘" | `get_global_rule` |
| "이 프로젝트 환경/구조 알려줘" | `get_global_skill` |
| "규칙 최신인지 확인해" | `check_rule_versions` |
| "이 코드 수정하면 영향 범위는?" | `analyze_code_impact` |

---

## 워크플로우

### 프로젝트 초기화
```
get_global_rule(app_name, origin_url) → 로컬 저장
get_global_skill(app_name, origin_url) → 로컬 저장
```

### 기획서 기반 구현
```
search_documents(query, app_target) → 기획서 확인 → 구현
```

### 규칙 갱신
```
check_rule_versions → 불일치 시 get_global_rule 재호출
```
"""

GLOBAL_SKILL_HARNESS_CONSTRUCTION = """\
# 하네스 구축 가이드

## 하네스란?

LLM 에이전트가 프로젝트에서 효과적으로 작업하기 위한 설정 체계입니다.
규칙(Rules), 스킬(Skills), 에이전트 정의, 프로젝트 문서를 구조화하여
에이전트가 프로젝트 맥락을 빠르게 파악하고 일관된 품질로 작업할 수 있게 합니다.

---

## 하네스 구성 요소

### 1. CLAUDE.md (프로젝트 루트)
프로젝트의 **진입점(맵)**. 상세 내용은 링크된 문서에 위임.
- 리포지토리 개요 (한 줄)
- 핵심 규칙 (5개 이내)
- 디렉터리 구조
- 문서 맵 (각 문서 역할과 경로)

### 2. .claude/agents/ 또는 .agents/
역할별 에이전트 정의. 각 파일에:
- 역할 범위와 목적
- 입력/출력 정의
- 사용할 스킬 목록
- 금지사항
- 다음 phase 연결

### 3. .claude/skills/ 또는 .cursor/skills/
반복 작업을 자동화하는 스킬 정의. 각 파일에:
- 트리거 (어떤 요청에 활성화되는지)
- 단계별 절차
- 주의사항
- 사용 예시

### 4. .claude/docs/
프로젝트 문서:
- CAUTION.md — 금지/주의사항 (모든 에이전트 필독)
- DESIGN.md — 설계 원칙, 코드 패턴
- SECURITY.md — 보안 정책
- RELIABILITY.md — 안정성 기준
- references/ — 도메인별 상세 레퍼런스
- patterns/ — 재사용 가능한 구현 패턴
- workflow/ — 브랜치 전략, 개발 프로세스, 배포

### 5. .claude/rules/
도메인별 규칙 파일 (event.md, resource.md 등)

### 6. MCP 연동
- Rules: `publish_app_rule`로 행동 지침 등록
- Skills: `publish_app_skill_tool`로 스킬 등록
- 기획서: `upload_document`로 기획서 등록
- 이후 `get_global_rule`, `get_global_skill`, `search_documents`로 조회

---

## 하네스 구축 절차

### Step 1: 프로젝트 분석
```
기술 스택, 디렉터리 구조, 팀 구성 파악
기존 문서(README, 설계서 등) 수집
```

### Step 2: CLAUDE.md 작성
```
프로젝트 한줄 소개 + 핵심 규칙 + 문서 맵
```

### Step 3: 에이전트 정의
```
역할별 .claude/agents/{name}.md 생성
파이프라인 흐름 정의 (예: plan → design → code → qa → review)
```

### Step 4: 스킬 정의
```
반복 작업 패턴을 .claude/skills/{name}/skill.md로 정의
트리거, 절차, 주의사항 포함
```

### Step 5: 문서 정리
```
CAUTION.md (금지사항), DESIGN.md (설계), SECURITY.md (보안) 등
references/ 에 도메인별 상세 문서
patterns/ 에 재사용 패턴
```

### Step 6: MCP 등록
```
publish_app_rule → 행동 지침 등록
publish_app_skill_tool → 스킬 등록
upload_document → 기획서 등록
```

---

## 에이전트 팀 설계 패턴

| 역할 | 모델 권장 | 핵심 |
|------|----------|------|
| plan | sonnet | 기획 분석, 실행계획 작성. 코드 안 씀 |
| design | sonnet | 설계, 유저 플로우, QA 시나리오. 코드 리뷰 |
| code | haiku | 설계 기반 구현. 빠른 코드 생성 |
| qa | sonnet | 독립 검증. 정상 플로우 + 엣지케이스 |
| review | sonnet | 하위호환, 보안, 성능, 문서 완성도 |
| document | sonnet | 구현 문서화, 패턴 추출 |
| harness | sonnet | 하네스 문서 갱신 |
| compounder | sonnet | 실수/피드백 수집 → compound 스킬 발행 |

### 파이프라인 흐름
```
plan → design → code → qa → review → document → harness → compounder
         ↑ 수정 필요 시      ↑ 버그 발견 시
         └── code 재실행 ←── plan부터 재시작
```

---

## 하네스 유지보수

- 새 패턴 발견 시 → patterns/ 에 추가
- 사용자 교정 발생 시 → CAUTION.md에 누적
- 새 기능 구현 시 → 관련 스킬/문서 업데이트
- 코드 변경 시 → 문서와 일치 여부 확인

## Compound Engineering (학습 루프)

하네스에 **compound 워크플로우**를 추가하면 에이전트가 자동으로 학습한다:

1. 각 에이전트가 실수/피드백/수정을 `docs/dev_log.md`에 Compound Records로 기록
2. @compounder가 레코드를 수집 → 패턴 분석 → 재사용 스킬로 발행
3. 이후 에이전트가 `search_skills`로 compound-* 스킬을 조회 → 같은 실수 방지

상세: `get_global_skill`로 `compound-workflow` 섹션 참조.

**원칙: 코드가 진실. 문서보다 코드가 우선.**
"""

GLOBAL_SKILL_COMPOUND_WORKFLOW = """\
# Compound Engineering 워크플로우

## 개요

에이전트 팀의 **학습 루프**. 각 에이전트가 작업 중 실수/교정/사용자 피드백을 기록하고,
@compounder가 **4개 병렬 분석 트랙**으로 깊이 있게 분석하여 재사용 스킬로 MCPER에 발행한다.

첫 번째 해결에 30분 걸린 문제를, 문서화 후 다음에는 2분으로 단축하는 것이 목표.

---

## 워크플로우

```
@pm → @planner → @senior → @coder + @tester (병렬) → @infra → @compounder
```

각 에이전트는 작업 중:
1. **작업 전**: `search_skills(query=작업 키워드, app_name)` → `compound-*` 섹션 우선 확인
2. **작업 중/후**: 실수/피드백/수정 발생 시 Compound Records에 기록

---

## Compound Records 포맷

보고서(`docs/dev_log.md`)에 아래 섹션을 추가:

```markdown
### Compound Records (해당 시)
<!-- compound-records-start -->
- [MISTAKE] context: {파일/기능} | mistake: {내용} | fix: {수정} | keywords: {키워드}
- [FEEDBACK] context: {파일/기능} | directive: {사용자 지시} | keywords: {키워드}
- [CORRECTION] context: {파일/기능} | original: {원래} | corrected: {수정} | keywords: {키워드}
<!-- compound-records-end -->
```

---

## @compounder 모드 선택

| 모드 | 조건 | 방식 |
|------|------|------|
| **Full** | 레코드 3건+ 또는 FEEDBACK 포함 | 4개 병렬 분석 트랙 + 전문가 검토 |
| **Lightweight** | 레코드 1~2건, MISTAKE/CORRECTION만 | 단일 패스 분석 |

---

## Full 모드: 4-Phase 실행

### Phase 1: 병렬 연구 (4개 트랙 동시)

#### Track A — Context Analyzer
- 문제 유형 분류: bug / knowledge / pattern / feedback
- 파일/모듈 매핑: context에서 경로, 함수명, 모듈 경계 식별
- 발행 파일명 제안: `compound-{유형}-{키워드}`

#### Track B — Solution Extractor

**Bug 트랙** (MISTAKE/CORRECTION):
- 증상: 오류 메시지, 관찰된 동작
- 시도했지만 안 된 것: 왜 실패했는지
- 실제 해결책: 단계별 + 코드 예시
- 근본 원인: 기술적 설명
- 예방 전략: 향후 회피 방법

**Knowledge 트랙** (FEEDBACK):
- 맥락: 어떤 상황에서 피드백이 나왔는지
- 지침: 사용자가 원하는 Do/Don't
- 적용 시기: 언제 이 지침을 적용해야 하는지
- 예시: 구체적 코드/작업 예시

#### Track C — Related Docs Finder
- `search_skills`로 기존 compound-* 스킬 검색
- `list_skill_sections`로 전체 compound 섹션 목록 확인
- 중복도 평가:
  - **높음** (80%+) → 기존 스킬 갱신 (새 버전 발행)
  - **중간** (50~80%) → 새 스킬 + cross-reference
  - **낮음/없음** → 새 스킬 작성

#### Track D — Root Cause Analyzer
근본 원인을 구조적으로 분석:
- 코드 구조 문제: 네이밍 혼란, 숨겨진 의존성
- 지식 격차: 문서 부재, 도메인 지식 부족
- 프로세스 문제: 검증 누락, 테스트 부족
- 환경 문제: 설정 차이, 버전 불일치

예방 레벨 분류:
- `rule`: 규칙으로 강제 필요 → 사용자에게 Rule 등록 제안
- `skill`: 스킬로 안내 → compound 스킬 발행
- `tool`: 자동화로 방지 가능 → 도구 제안

### Phase 2: 조립 & 작성

중복도에 따라 처리:
- 높음 → 같은 section_name으로 새 버전 발행
- 중간 → 새 스킬 + 관련 스킬 cross-reference
- 낮음 → 새 스킬 작성

### Phase 3: 전문가 검토 (선택적)

| 문제 유형 | 전문가 | 검토 내용 |
|----------|--------|----------|
| 성능 이슈 | @senior | N+1 쿼리, 메모리, 불필요한 연산 |
| 보안 이슈 | @infra | 시크릿, 권한, 인젝션 |
| 아키텍처 | @senior | 설계 원칙, 의존성 방향 |
| 테스트 누락 | @tester | 엣지케이스, 모킹 전략 |

### Phase 4: 발행 & 검증

```
publish_app_skill_tool(app_name, body, section_name="compound-{topic}")
search_skills(query="{키워드}", app_name) → 검색 확인
```

---

## 스킬 문서 구조

```markdown
# compound-{topic}

## 증상
{오류 메시지, 관찰된 동작, 발생 조건}

## 근본 원인
{왜 이런 문제가 발생하는지}

## 시도했지만 안 된 접근 (해당 시)
{왜 실패했는지 — 같은 삽질 방지}

## 올바른 접근
{단계별 해결 방법, 코드 예시}

## 예방 전략
{사전에 피하는 방법}

## 적용 조건
{파일 경로, 기능명, 작업 유형}

## 관련 스킬
{기존 compound-* cross-reference}

## 키워드
{검색용 키워드}

## 메타
- 유형: {bug | knowledge | pattern | feedback}
- 출처: {에이전트명, 날짜}
- 예방 레벨: {rule | skill | tool}
```

---

## 발행 규칙

| 조건 | 처리 |
|------|------|
| FEEDBACK 1건 | 무조건 스킬화 (사용자 의도 존중) |
| MISTAKE/CORRECTION + 근본원인 재사용 가치 있음 | 스킬화 |
| 1회성 특수 상황 + 재사용 가치 없음 | 스킵 |
| 기존 스킬과 중복 높음 | 같은 section_name으로 새 버전 |
| 예방 레벨 rule | 스킬 발행 + 사용자에게 Rule 등록 제안 |
| 레코드 0건 | 보고 후 종료 |

---

## section_name 규약

- `compound-{파일명}` — 특정 파일 (예: `compound-event-controller`)
- `compound-{기능명}` — 특정 기능 (예: `compound-jwt-validation`)
- `compound-{주제}` — 범용 (예: `compound-error-handling`)
- `compound-feedback-{주제}` — 피드백 (예: `compound-feedback-code-style`)
- `compound-pattern-{주제}` — 아키텍처 패턴 (예: `compound-pattern-event-season`)
"""

# ---------------------------------------------------------------------------
# Repo Skills — stz-game-service 레포 공통
# ---------------------------------------------------------------------------

REPO_SKILL_MAIN = """\
# stz-game-service 프로젝트 개요

## 기술 스택
| 항목 | 내용 |
|------|------|
| 언어 | PHP |
| 웹서버 | nginx + php-fpm |
| 인프라 | AWS (EC2, ALB, S3, CodePipeline) |
| 배포 | rsync (사내 배포 서버 → EC2) |
| 게임 데이터 | Google Spreadsheet → S3 → LocalCache(APCu) |
| API 문서 | apidoc.php (PHPDoc 주석 자동 파싱) |

## 프로젝트 구조
HTTP 기반 게임 서버. 하나의 리포지토리에서 여러 게임을 **브랜치로 분리**하여 관리.

```
adventure/
├── url.php              # 진입점 (nginx → php-fpm → url.php)
├── ENV/                 # 환경별 설정 (config.dev.ini, config.live.ini)
├── php/
│   ├── config.php       # 전역 설정, Config 클래스, 오토로더
│   ├── controllers/     # 컨트롤러 (URL 경로와 1:1 매핑)
│   │   ├── *.php        # 공용 컨트롤러
│   │   └── adventure/   # 게임별 전용 디렉토리
│   ├── lib/             # 공용 라이브러리 (Crypto, Log, SQL 등)
│   └── templates/       # 뷰 템플릿
├── static/              # JS, CSS
├── bin/                 # 배치/스크립트
├── tests/               # 테스트
└── docker-compose.yml   # 로컬 개발 환경
```

## 코드 레이어
```
클라이언트 → nginx → php-fpm → url.php
  → php/controllers/*.php (공용)
  → php/controllers/{game}/*.php (게임별)
  → php/lib/ (공용 라이브러리)
  → DB / Cache / S3
```

## 핵심 규칙
1. **공용 코드** (`php/controllers/*.php`, `php/lib/`): 수정 시 모든 게임 영향 → 반드시 사용자 확인
2. **게임별 코드** (`php/controllers/{game}/`): 해당 게임에만 영향 → 자유 수정 가능
3. **API 버전 관리**: 기존 키 유지+새 키 추가 = OK, 기존 키 제거/변경 = 반드시 새 버전(v2, v3)
4. **apidoc 주석 필수**: 모든 API 메서드에 `@path`, `@desc`, `@param`, `@return`

## 게임 목록
| 디렉토리 | 게임 |
|----------|------|
| adventure/ | 애니팡 어드벤처 |
| anipang3/ | 애니팡3 |
| anisachun2/ | 애니사천성2 |
| shanghai/ | 상하이 |
| wbb/ | WBB |
| wbbeu/ | WBB EU |
| wbbgb/ | WBB GB |
| anitouch/ | 애니터치 |

## 인프라
- LB → EC2 (Auto Scaling), EC2 부팅 시 rsync로 코드 배포
- dev/stage: AWS CodePipeline 자동 배포
- live: 사내 배포 서버에서 게임별 수동 배포

## 게임 데이터(Resource) 흐름
```
기획자(Google Spreadsheet) → 어드민(시트 배포) → S3 → 각 EC2 → LocalCache(APCu)
```
"""

REPO_SKILL_WORKFLOW = """\
# stz-game-service 개발 워크플로우

## 브랜치 전략
```
{game}/master  ← 프로덕션
{game}/stage   ← QA/스테이징
{game}/dev     ← 개발 통합
{game}/{차수}/release  ← 릴리즈 브랜치
{game}/{차수}/ft/{작업}  ← 피처 브랜치
{game}/{차수}/fix/{작업}  ← 핫픽스 브랜치
```

### 규칙
- master 직접 커밋 금지
- 게임 간 브랜치 머지 금지
- 브랜치 생성 전 사용자에게 이름/base 확인

## 개발 프로세스
```
기획서 수령 → 브랜치 생성 → dev에서 개발 → stage QA → master 배포
```

### API 수정 체크리스트
1. 기존 응답 키 유지 여부 확인
2. 새 버전 필요 여부 판단 (키 제거/변경 시 v2 생성)
3. min_client_version 상향 필요 시 사용자 확인
4. apidoc 주석 작성/갱신
5. 변경 API에 대한 테스트 실행

## 배포 절차
| 환경 | 방식 |
|------|------|
| dev | CodePipeline 자동 (push → deploy) |
| stage | CodePipeline 자동 |
| live | 사내 배포 서버 → rsync → EC2 |

### 리소스(게임 데이터) 배포
코드 배포와 별도. 어드민에서 시트 배포 버튼 → S3 → EC2.
**주의**: resource/init 호출 시 LocalCache가 S3 원본으로 리셋됨.

## 로컬 개발 환경
```
서버: http://localhost:8041 (nginx → php-fpm)
apidoc: http://localhost:8041/{controller}.api
암호화: dev 환경 비활성 (force_encrypt 주석처리)
```
"""

# ---------------------------------------------------------------------------
# App Skills — adventure 앱 전용
# ---------------------------------------------------------------------------

ADVENTURE_SKILL_MAIN = """\
# adventure 앱 스킬

## 앱 개요
애니팡 어드벤처(애니팡4) 게임 서버. HTTP API 기반.
브랜치: `adventure/master`, `adventure/dev`, `adventure/stage`
디렉토리: `php/controllers/adventure/`

## 에이전트 팀

| phase | 모델 | 역할 |
|-------|------|------|
| plan | sonnet | 기획서 분석, 실행계획 작성, 미결사항 질문 |
| design | sonnet | 구현 설계, 유저 플로우, QA 시나리오, 코드 리뷰 |
| code | haiku | 설계 기반 구현, apidoc 주석 작성 |
| qa | sonnet | 정상 플로우 + 엣지케이스 독립 검증 |
| review | sonnet | 하위호환, 보안, 성능, apidoc 완성도 검토 |
| document | sonnet | 구현 문서화, 패턴 추출 |
| harness | sonnet | 하네스 문서 갱신, CAUTION.md 누적 |
| compounder | sonnet | 실수/피드백 수집 → compound 스킬 발행 |

### 파이프라인
```
plan → design → code → design(리뷰) → qa → design(평가) → review → document → harness → compounder
```

## 이벤트 시스템

### 핵심 구조
- **privateEventEntry**: 유저 개인 이벤트 (개인 보상, 미션 등)
- **groupEventEntry**: 그룹/랭킹 이벤트 (팀 경쟁, 공동 목표)
- **adventureEvent**: 이벤트 베이스 클래스 (공통 로직)

### 이벤트 데이터 흐름
```
Google Spreadsheet → S3 → LocalCache(APCu)
   events 시트: event_id, start, end, ui_out, enabled, min_stage
   event_group_data: group, grade, min, max, rate
   event_group_reward: reward_group, grade, item_ids
```

### 시즌제 이벤트 패턴 (event-seasonalization)
같은 이벤트 구조를 시즌별(설/추석/분식 등)로 재사용.
`extra_info.type` 필드로 시즌 구분.
헬퍼 메서드: `getEventInfo()`, `getEventType()`, `getGroupData()`

### 이벤트 개발 필수 확인
1. 이벤트 ID (중복 여부)
2. 시작/종료/UI종료 시간
3. 스프레드시트 컬럼 정의
4. 유저별 저장 데이터
5. 그룹/팀 기반 여부
6. 시즌 종료 시 데이터 처리
7. 버전 필터링 필요 여부
8. API 목록 및 이벤트 아이템 ID

## 리소스(게임 데이터)
- **읽기만**: LocalCache(APCu)에서 읽기. DB 직접 쿼리 금지.
- **서버 전용 데이터**: `_` 또는 `:` 로 시작하는 시트/컬럼은 클라이언트에 노출 안 됨
- **테스트 환경**: staticsheet API로 직접 조작 가능 (Live는 조회만)

## 주요 시트
| 시트 | 용도 |
|------|------|
| events | 이벤트 마스터 (ID, 기간, 활성 여부) |
| event_group_data | 그룹 이벤트 등급/확률 |
| event_group_reward | 그룹 보상 설정 |
| event_random_reward | 랜덤 보상 설정 |
| event_item | 이벤트 아이템 정의 |
| treasureking_list | 보물왕 리스트 |

## 스킬 목록
| 스킬 | 트리거 |
|------|--------|
| staticsheet | 시트 데이터 조회/수정 |
| eventitemtest | 이벤트 아이템 추가/설정/삭제 |
| api-test | curl로 API 테스트 |
| browser-test | apidoc 브라우저 테스트 |
| orchestrator | 기능 개발 전체 파이프라인 |
| pr-review | GitHub PR 리뷰 |
| harness-update | 하네스 문서 갱신 |
| compound | 실수/피드백 → 재사용 스킬 발행 |
| cmux-terminal | 터미널 화면 읽기 |
"""

ADVENTURE_SKILL_EVENTS = """\
# adventure 이벤트 시스템 레퍼런스

## 이벤트 데이터 흐름
```
기획자(Google Spreadsheet)
  ↓ 어드민에서 시트 배포
S3 (resource 파일)
  ↓ resource/init API 또는 자동 갱신
LocalCache (APCu)
  ↓ 컨트롤러에서 readResource()
이벤트 로직
```

## 이벤트 종류

### privateEventEntry (개인 이벤트)
- 유저 개인 데이터만 사용
- 미션 완료, 개인 보상 수령 등
- DB: 유저별 이벤트 데이터 저장

### groupEventEntry (그룹 이벤트)
- 그룹/팀 단위 공유 데이터
- 랭킹, 공동 목표, 팀 경쟁
- DB: 그룹 데이터 + 유저별 기여도

### adventureEvent (베이스 클래스)
- 공통 이벤트 로직 (시간 체크, 데이터 로드)
- privateEventEntry, groupEventEntry가 상속

## 시즌제 이벤트 패턴

같은 컨트롤러를 시즌별로 재사용하는 패턴.
`extra_info.type` 필드로 시즌 구분 (예: "snack", "chuseok", "seollal").

### 핵심 헬퍼 메서드
```php
getEventInfo()   // events 시트에서 현재 이벤트 정보 조회
getEventType()   // extra_info.type 값 반환
getGroupData()   // event_group_data 시트에서 등급/확률 조회
```

### 시즌 추가 시 TODO
1. events 시트에 새 event_id 행 추가 (extra_info.type 설정)
2. event_group_data에 등급/확률 데이터 추가
3. event_group_reward에 보상 데이터 추가
4. 기존 컨트롤러의 EVENT_ID/EVENT_NAME 상수 업데이트
5. 시트 배포 → 코드 배포 순서 (시트 먼저!)

### 참고 구현: AA-407 (분식 요리마당)
- 3개 헬퍼 메서드 도입 (getEventInfo, getEventType, getGroupData)
- SHEET_REWARD → SHEET_GROUP_REWARD 전환
- 시즌별 이벤트 ID 분기 처리

## 주요 시트 구조

### events
| 컬럼 | 설명 |
|------|------|
| event_id | 이벤트 고유 ID |
| start | 시작 시간 |
| end | 종료 시간 |
| ui_out | UI 표시 종료 시간 |
| event_val1 | 이벤트별 추가값 |
| enabled | 활성 여부 |
| min_stage | 최소 스테이지 |
| extra_info | JSON (type 등 추가 정보) |

### event_group_data
| 컬럼 | 설명 |
|------|------|
| event_id | 이벤트 ID |
| group | 그룹 번호 |
| grade | 등급 |
| min / max | 범위 |
| rate | 확률 |

### event_item
| 컬럼 | 설명 |
|------|------|
| id | 아이템 ID |
| event_id | 소속 이벤트 |
| type | 아이템 유형 |
| name | 아이템 이름 |
| max_count | 최대 보유량 |

### 주요 이벤트 아이템 예시
- 유물왕(event_id=10032): 곡괭이(1174), 드릴(1175), 브러시(1176)
"""

ADVENTURE_SKILL_API_PATTERNS = """\
# adventure API 패턴

## API 응답 규약
- 모든 응답에 `result` 키 포함 (성공/실패 여부)
- 기존 응답 키 절대 제거 금지 → 새 키 추가만 가능
- 키 제거/동작 변경 필요 시 → 반드시 새 버전(v2, v3) 생성

## apidoc 주석 필수 작성
```php
/**
 * @path /adventure/event/info
 * @desc 이벤트 정보 조회
 * @param int $user_id 유저 ID
 * @param int $event_id 이벤트 ID
 * @return array {result: bool, event: {...}}
 * @app adventure
 */
```
모든 API 메서드에 `@path`, `@desc`, `@param`, `@return` 필수.
게임 전용 API는 `@app` 태그 추가.

## URL 라우팅
```
요청: /{controller}/{path}/v{version}.{ext}
매핑: php/controllers/{controller}.php → {Controller}::{path}_v{version}()
게임별: php/controllers/{game}/{controller}.php
```
확장자별 처리: `.json`(JSON), `.xml`(XML), `.api`(apidoc 페이지), `.dump`(디버그)

## 테스트 API (dev/stage 전용)
| API | 용도 |
|-----|------|
| `/staticsheet/list/v1.json` | 시트 목록 |
| `/staticsheet/get/v1.json?sheet={name}` | 시트 행 조회 |
| `/staticsheet/upsert/v1` | 시트 행 수정 |
| `/eventitemtest/get/v1.json` | 이벤트 아이템 조회 |
| `/eventitemtest/add/v1` | 이벤트 아이템 추가 |
| `/resource/init` | 리소스 캐시 초기화 (S3 → APCu) |

**주의**: resource/init 호출 시 staticsheet로 수정한 데이터 소실됨

## 보안
- ACL(접근 제어 목록)로 API별 접근 관리
- 요청 암호화/복호화 (dev 환경은 비활성)
- SQL: 반드시 prepared statement 사용 (직접 쿼리 삽입 금지)
- admin 전용 API: 별도 권한 체크 필수
"""

ADVENTURE_SKILL_TESTING = """\
# adventure 테스트 가이드

## 테스트 환경
```
서버: http://localhost:8041 (Docker nginx → php-fpm)
apidoc: http://localhost:8041/{controller}.api
암호화: dev 환경 비활성
```

## 테스트 도구

### api-test (curl 기반)
```bash
# API 목록 조회
curl http://localhost:8041/apidoc/spec

# GET 요청
curl "http://localhost:8041/adventure/event/info/v1.json?user_id=9999&event_id=10032"

# POST 요청
curl -X POST http://localhost:8041/adventure/event/action/v1.json \\
  -d "user_id=9999&event_id=10032&action=claim"
```

### browser-test (apidoc 브라우저)
1. `http://localhost:8041/{controller}.api` 접속
2. 파라미터 폼에 값 입력
3. "실행" 클릭 → 응답 확인
4. user_id 미지정 시 임의 숫자(9999) 사용

### eventitemtest (이벤트 아이템 관리)
```bash
# 아이템 조회
curl "http://localhost:8041/eventitemtest/get/v1.json?user_id=9999&event_id=10032"

# 아이템 추가
curl -X POST http://localhost:8041/eventitemtest/add/v1.json \\
  -d "user_id=9999&event_id=10032&item_id=1174&count=10"

# 아이템 설정 (절대값)
curl -X POST http://localhost:8041/eventitemtest/set/v1.json \\
  -d "user_id=9999&event_id=10032&item_id=1174&count=5"
```

### staticsheet (시트 데이터 관리)
```bash
# 시트 목록
curl "http://localhost:8041/staticsheet/list/v1.json"

# 이벤트 활성화
curl -X POST http://localhost:8041/staticsheet/upsert/v1.json \\
  -d "sheet=events&id=10032&enabled=1&start=2026-01-01&end=2026-12-31"
```

## 이벤트 API 테스트 절차
1. `staticsheet/upsert` → events 시트에 이벤트 활성화
2. `eventitemtest/add` → 필요한 아이템 지급
3. 실제 API 호출 (정상 플로우)
4. 엣지케이스 테스트 (파라미터 누락, 기간 외 호출, 중복 수령 등)

## 주의사항
- ❌ 라이브 서버 테스트 절대 금지
- ❌ 결제/재화 API는 사용자 확인 필요
- ⚠️ resource/init 호출 시 staticsheet 변경사항 소실
"""

# ---------------------------------------------------------------------------
# App Rule — adventure 행동 규칙
# ---------------------------------------------------------------------------

ADVENTURE_APP_RULE = """\
# adventure 앱 규칙

## 코드 작성 규칙

### 공용 코드 보호
- ✅ 게임별 디렉터리(`php/controllers/adventure/`) 내부는 자유 수정
- ❌ 공용 코드(`php/controllers/*.php`, `php/lib/`) 수정 시 반드시 사용자 확인
- ❌ 다른 게임 디렉터리 수정 금지

### API 버전 관리
- ✅ 기존 응답 키 유지 + 새 키 추가 → 기존 메서드 수정 OK
- ❌ 기존 키 제거 또는 동작 변경 → 반드시 새 버전(v2, v3) 생성
- ⚠️ min_client_version 상향 → 사용자 먼저 확인

### apidoc 주석
- ✅ 모든 API 메서드에 `@path`, `@desc`, `@param`, `@return` 작성
- ✅ 게임 전용 API에 `@app adventure` 태그

### 리소스 데이터
- ✅ LocalCache(APCu)에서만 읽기
- ❌ 리소스 데이터 DB 직접 쿼리 금지

## 변경 시 필수 확인

1. **기획서 확인**: 구현 전 반드시 관련 기획서 검색 (MCP `search_documents` 사용)
2. **하위호환**: 기존 API 응답 키 제거/변경 없는지 확인
3. **영향 범위**: 공유 모듈 변경 시 다른 게임 영향 확인
4. **테스트**: 새 기능/버그 수정 시 API 테스트 동반

## 이벤트 작업 필수 사항
- EVENT_ID / EVENT_NAME 상수 정의
- privateEventEntry vs groupEventEntry 선택 근거 명시
- 시즌 종료 시 데이터 처리 방식 정의
- 시트 배포 → 코드 배포 순서 준수

## 금지 사항
- ❌ 기획서 없이 새 기능 임의 구현
- ❌ 커밋은 사용자 명시적 요청 시에만
- ❌ Opus 모델 사용 금지 (토큰 비용)
- ❌ 라이브 서버에서 테스트 금지
- ❌ 결제/재화 API 무단 실행 금지

## 커밋/브랜치 규약
- 브랜치: `adventure/{차수}/ft/{작업내용}`
- base: `adventure/{차수}/release`
- 이슈: `[adventure] {제목}`
- PR: `[adventure] {작업내용}`
- 브랜치 생성 전 사용자에게 이름/base 확인

## 기획서 구현 워크플로우
1. `search_documents(query="...", app_target="adventure")` 로 기획서 검색
2. 기획서 내용 이해 및 요구사항 정리
3. 기존 코드 패턴 참고 (`docs/patterns/` 확인)
4. 구현 → API 테스트 → 엣지케이스 확인
5. apidoc 주석 작성
"""

# ---------------------------------------------------------------------------
# Repo Rule — stz-game-service 전체 적용
# ---------------------------------------------------------------------------

REPO_RULE_STZ = """\
# stz-game-service 레포지토리 규칙

## 공용 코드 보호 정책
- `php/controllers/*.php` (루트 컨트롤러) + `php/lib/` 전체는 **공용 코드**
- 공용 코드 수정 시 모든 게임에 영향 → **반드시 사용자 확인 후 수정**
- 게임별 디렉터리(`php/controllers/{game}/`) 내부는 자유 수정

## API 버전 관리
- 기존 응답 키 유지 + 새 키 추가 = 기존 메서드 수정 가능
- 기존 키 제거/변경 = 반드시 새 버전 메서드(`v2`, `v3`) 생성
- `min_client_version` 상향 시 사용자 먼저 확인

## 브랜치 전략
- `{game}/master` 직접 커밋 금지
- 게임 간 브랜치 머지 금지
- 피처: `{game}/{차수}/ft/{작업}`, 핫픽스: `{game}/{차수}/fix/{작업}`

## 문서화
- 모든 API 메서드에 apidoc 주석 (`@path`, `@desc`, `@param`, `@return`) 필수
- 게임 전용 API는 `@app {game}` 태그 추가

## 보안
- SQL: prepared statement 필수, 직접 쿼리 삽입 금지
- ACL로 API별 접근 제어
- admin 전용 API는 별도 권한 체크

## 리소스 데이터
- 읽기: LocalCache(APCu)에서만
- DB 직접 쿼리로 리소스 읽기 금지
- resource/init 호출 시 로컬 변경사항 소실 주의
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    init_db()
    db = SessionLocal()

    try:
        print("=" * 60)
        print("adventure 앱 데이터 시딩 시작")
        print("=" * 60)

        # 1. Global Skills
        print("\n--- Global Skills ---")

        v = publish_global_skill(db, GLOBAL_SKILL_MCP_USAGE, "mcp-usage")
        print(f"  ✓ global/mcp-usage v{v}")

        v = publish_global_skill(db, GLOBAL_SKILL_HARNESS_CONSTRUCTION, "harness-construction")
        print(f"  ✓ global/harness-construction v{v}")

        v = publish_global_skill(db, GLOBAL_SKILL_COMPOUND_WORKFLOW, "compound-workflow")
        print(f"  ✓ global/compound-workflow v{v}")

        # 2. Repo Skills (pattern: stz-game-service)
        print("\n--- Repo Skills (stz-game-service) ---")

        _, sn, v = publish_repo_skill(db, "stz-game-service", REPO_SKILL_MAIN, "main", sort_order=10)
        print(f"  ✓ repo/stz-game-service/{sn} v{v}")

        _, sn, v = publish_repo_skill(db, "stz-game-service", REPO_SKILL_WORKFLOW, "workflow", sort_order=20)
        print(f"  ✓ repo/stz-game-service/{sn} v{v}")

        # 3. App Skills (adventure)
        print("\n--- App Skills (adventure) ---")

        _, sn, v = publish_app_skill(db, "adventure", ADVENTURE_SKILL_MAIN, "main")
        print(f"  ✓ app/adventure/{sn} v{v}")

        _, sn, v = publish_app_skill(db, "adventure", ADVENTURE_SKILL_EVENTS, "events")
        print(f"  ✓ app/adventure/{sn} v{v}")

        _, sn, v = publish_app_skill(db, "adventure", ADVENTURE_SKILL_API_PATTERNS, "api-patterns")
        print(f"  ✓ app/adventure/{sn} v{v}")

        _, sn, v = publish_app_skill(db, "adventure", ADVENTURE_SKILL_TESTING, "testing")
        print(f"  ✓ app/adventure/{sn} v{v}")

        # 4. App Rule (adventure)
        print("\n--- App Rule (adventure) ---")

        _, _, v = publish_app(db, "adventure", ADVENTURE_APP_RULE, "main")
        print(f"  ✓ app_rule/adventure/main v{v}")

        # 5. Repo Rule (stz-game-service)
        print("\n--- Repo Rule (stz-game-service) ---")

        from app.services.versioned_rules import publish_repo
        _, _, v = publish_repo(db, "stz-game-service", REPO_RULE_STZ, section_name="main")
        print(f"  ✓ repo_rule/stz-game-service/main v{v}")

        print("\n" + "=" * 60)
        print("시딩 완료!")
        print("=" * 60)

        # Summary
        print("\n[요약]")
        print("  Global Skills: 3개 (mcp-usage, harness-construction, compound-workflow)")
        print("  Repo Skills:   2개 (stz-game-service/main, workflow)")
        print("  App Skills:    4개 (adventure/main, events, api-patterns, testing)")
        print("  App Rule:      1개 (adventure/main)")
        print("  Repo Rule:     1개 (stz-game-service/main)")
        print("\n[테스트 방법]")
        print('  get_global_skill(app_name="adventure", origin_url="git@github.com:sundaytoz/stz-game-service.git")')
        print('  get_global_rule(app_name="adventure", origin_url="git@github.com:sundaytoz/stz-game-service.git")')

    except Exception as exc:
        db.rollback()
        print(f"\n❌ 에러: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
