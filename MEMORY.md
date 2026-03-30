# MEMORY.md

**메모리 인덱스 및 기록관 메모.**
- 사용자·피드백·프로젝트 메모: `.claude/projects/-Users-wemadeplay-workspace-personal-mcper/memory/`
- 기록관 메모: `.claude/archivist_notes/` (대용량 파일 분석 결과)
- 프로젝트 평가: `docs/project_assessment.md` (2026-03-30 종합 평가 기록)

---

## 기록관 메모 인덱스

기록관(@archivist)이 작성한 분석 메모들. 대용량 파일 재읽기를 줄이기 위해 먼저 확인:

- (메모 없음 - 첫 기록관 요청 시 생성 예정)

---

## 프로젝트 평가 (2026-03-30)

종합 평가 및 개선 계획: `docs/project_assessment.md` 참고

**핵심:**
- ✅ 규칙 시스템 우수 (⭐⭐⭐⭐⭐)
- ⚠️ 보안 미흡 (⭐⭐) → Admin 패스워드 강제 필수
- ⚠️ 관리자 UI 너무 큼 (1293줄) → 모듈 분리 필요
- ❌ CodeNode 파서 부재 → AST 크롤러 필요

---

## 메모리 추가 방법

메모리는 5가지 타입:

1. **user** — 사용자 역할/선호/지식
2. **feedback** — 추천/금지 규칙 (왜, 어떻게 적용)
3. **project** — 진행 중 작업/목표/기한
4. **reference** — 외부 시스템 (Linear, Grafana 등)
5. **config** — 프로젝트 설정/버그 workaround

---

## 추가 예시

```bash
# 사용자 정보
- [User Role](user_role.md) — 사용자는 시니어 백엔드 엔지니어, 처음 React 접함

# 선호사항
- [No Summaries](feedback_no_summaries.md) — 응답 끝에 요약 금지, 사용자가 이미 diff 읽음

# 진행 중 작업
- [Auth Refactor](project_auth_refactor.md) — 세션 기반 → JWT로 변경, 3월 31일까지

# 외부 시스템
- [Linear Bugs](reference_linear.md) — 버그는 Linear "BUG" 프로젝트에서 추적

# 프로젝트 설정
- [pgvector Config](config_pgvector.md) — 로컬에서 pgvector 설치 필요: brew install pgvector
```

