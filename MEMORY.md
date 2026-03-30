# MEMORY.md

**메모리 인덱스.** 각 파일은 `.claude/projects/-Users-wemadeplay-workspace-personal-mcper/memory/` 에서 유지됨.

---

(현재 메모리 없음)

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

