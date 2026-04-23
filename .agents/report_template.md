# 작업 보고서 템플릿

**큰 작업 완료 후 `docs/dev_log.md` 맨 위에 추가 (최신순)**

---

## 작성 기준

파일 3개 이상 수정 / 로직 변경 / 새 기능 추가 / 아키텍처 결정 / 의존성 변경

---

## 포맷

```markdown
## [날짜]: @[에이전트] [작업 제목]

### 작업 내용
- 주요 변경 3-5줄 요약
- 파일: [file1.py], [file2.py]

### 판단 이유
- Why: 왜 이렇게 했는가?
- Risk: 예상 위험요소 (있으면만)

### 결과
✅ 완료 / ⚠️ 부분 완료 / ❌ 보류

### 다음 단계 (필요시)
- @에이전트: 후속 작업

### Compound Records (해당 시)
<!-- compound-records-start -->
- [MISTAKE] context: {파일/기능} | mistake: {무엇이 잘못됐나} | fix: {어떻게 고쳤나} | keywords: {검색 키워드}
- [FEEDBACK] context: {파일/기능} | directive: {사용자 지시 내용} | keywords: {검색 키워드}
- [CORRECTION] context: {파일/기능} | original: {원래 접근} | corrected: {수정된 접근} | keywords: {검색 키워드}
<!-- compound-records-end -->
```

---

## 에이전트별 작성 시점

| 에이전트 | 작성 시점 |
|---------|---------|
| `@pm` | 타당성 + 범위 결정 후 |
| `@planner` | 기획서 완성 후 |
| `@senior` | 설계 문서 완성 후 |
| `@coder` | 코드 작성 완료 후 |
| `@tester` | 테스트 작성 완료 후 |
| `@infra` | 검수 완료 후 |
| `@archivist` | 분석 메모 완성 후 |
| `@compounder` | 세션 종료 전, 모든 에이전트 작업 완료 후 |

---

## 작성 팁

- 제목 명확히: "JWT 검증 추가" O, "기술 변경" X
- Why/Risk 간결히: "Why: 보안 CRITICAL 항목"
- 다음 단계 실행 가능하게: "@tester: 만료 토큰 E2E 테스트 추가"
- 분량: 100-200자 내외
- Compound Records: 실수/피드백 없으면 생략. 있으면 context와 keywords를 구체적으로 (파일 경로, 기능명 포함)
