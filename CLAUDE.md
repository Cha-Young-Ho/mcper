# CLAUDE.md

**에이전트 팀 운영 규칙 요약.** 상세 지침은 `.agents/` 디렉터리 참고.

---

## 빠른 참조

| 트리거 | 역할 | 모델 |
|--------|------|------|
| `@pm` | 프로젝트 관리자 | claude-sonnet-4-6 |
| `@planner` | 기획자 | claude-sonnet-4-6 |
| `@senior` | 시니어 개발자 | claude-sonnet-4-6 |
| `@coder` | 코드 작업자 | claude-haiku-4-5 |
| `@tester` | 테스트 코드 작업자 | claude-haiku-4-5 |
| `@infra` | 인프라 관리자 | claude-sonnet-4-6 |
| `@archivist` | 데이터 라이브러리언 | claude-haiku-4-5 |

---

## 공통 규칙 (필수)

1. **컨텍스트 절약** — 파일 읽기 전 추측 금지, 변경 전 확인, 요청 없는 개선 금지, compact 응답
2. **문서화** — 큰 작업 끝나면 `docs/dev_log.md` 맨 위에 추가 (최신순)
3. **선호 추적** — 파악된 스타일/선호는 `.agents/{역할}.md` 갱신
4. **협업** — 모호한 요청은 확인 후 진행, 선행 작업은 `dev_log.md` 최신 항목 먼저 읽기

---

## 협업 흐름

```
@pm → @planner → @senior → @coder (구현)
                                ↕ (병렬)
                            @tester (테스트)
                                ↓
                            @infra (검수)
     ↓ (필요시)
  @archivist (1000줄+ 파일 읽기 → 메모)
```

단순 작업(버그픽스)은 중간 단계 생략 가능.

---

## No Manual Code (Harness Engineering)

프로덕션 코드는 에이전트만 작성. 사용자는 설정·문서·요청만 담당.

---

## MCP Rule 라우팅 (stz-game-service 카테고리 구조)

**로컬 LLM이 MCP 서버에서 자동으로 받아오는 Rule들** (카테고리별):

```
Rules
└── Repository: stz-game-service
    ├── Development (v1)
    │   ├── COMMIT_GUIDE.md (커밋 컨벤션)
    │   └── CODE_STYLE.md (Python/JS 스타일)
    ├── Deployment (v1)
    │   ├── DEPLOYMENT_GUIDE.md (배포 체크리스트)
    │   └── RELIABILITY.md (모니터링, 장애 대응)
    ├── Architecture (v1)
    │   ├── DESIGN.md (설계 원칙, 아키텍처)
    │   └── PLANS.md (Phase 1-4 계획)
    └── Security (v1)
        └── SECURITY.md (보안 정책, 위협 모델)
```

**사용 방법**:
```
로컬 LLM에서 사용자가 요청:
  "규칙 받아와줘"
  → MCP 서버 /get_global_rule (stz-game-service)
  → 4개 카테고리의 Rule 자동 로드
  → Agent가 카테고리별 가이드 기반으로 작업
```

**어드민 화면에서**:
- Rules > Repository > stz-game-service 클릭
- 4개 카테고리 탭 표시 (Development, Deployment, Architecture, Security)
- 각 카테고리 내 여러 파일 포함

---

## @archivist 활용

다음 중 하나라도 해당하면 먼저 @archivist 요청:
- 파일 1000줄 이상
- 동시에 5개 이상 파일 분석
- `.claude/archivist_notes/` 에 관련 메모 있으면 재활용

예외: 시간 압박 명시 시 스킵.

---

## 작업 완료 후 보고서

파일 3개+ 수정 / 로직 변경 / 신기능 / 아키텍처 결정 시 `docs/dev_log.md` 맨 위에 추가.
포맷: `.agents/report_template.md` 참고.

---

## 문서 참고

- **기술 가이드** — `docs/TECH_GUIDE.md`
- **메모리** — `MEMORY.md`
- **에이전트별 상세 지침** — `.agents/{역할}.md`
- **작업 로그** — `docs/dev_log.md`
- **팀 구조·협업 상세** — `AGENTS.md`

---

## 사용자 선호 및 컨벤션

(파악된 내용은 `.agents/{역할}.md` 에서 유지)
