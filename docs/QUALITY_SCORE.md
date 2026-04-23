# docs/QUALITY_SCORE.md — 품질 메트릭

---

## 종합 점수: 6.8 / 10

| 영역 | 점수 | 비고 |
|------|------|------|
| 아키텍처 | 8/10 | MCP 중심, 모듈 분리 우수, admin.py 분리 필요 |
| 코드 품질 | 7/10 | Type hints 완전, 매직 넘버·긴 함수 일부 존재 |
| 보안 | 4/10 | Phase 1 CRITICAL 3개 계획 중, 레이트 제한 없음 |
| 테스트 | 3/10 | ~10개 단위 테스트, 통합/E2E 없음 |
| 문서 | 8/10 | 기술 가이드 충실, API 문서(OpenAPI) 미활용 |
| 운영 준비도 | 5/10 | 헬스체크 있음, 모니터링 대시보드·경고 없음 |

---

## 코드 복잡도 (주의 대상)

| 파일 | 함수 | 순환 복잡도 |
|------|------|-----------|
| search_hybrid.py | hybrid_search | 12 (매우 높음) |
| admin.py | create_rule | 8 (높음) |
| versioned_rules.py | fetch_rules | 6 (보통) |

---

## 기술 부채 요약

| 항목 | 우선순위 | 예상 시간 |
|------|---------|---------|
| 보안 강화 (CRITICAL 3개) | CRITICAL | 15.5h |
| admin.py 분리 | HIGH | 10.5h |
| CodeNode 파서 | HIGH | 9h |
| Celery 모니터링 | HIGH | 6h |
| 테스트 커버리지 (단위 50+, 통합 20+) | HIGH | 30h |
| 레이트 제한 | MEDIUM | 8h |
| 권한 관리 (RBAC) | MEDIUM | 15h |

**총 부채**: ~114시간

---

## 관련 문서

- **docs/RELIABILITY.md** — 배포 체크리스트
- **docs/SECURITY.md** — 보안 정책
- **docs/PLANS.md** — 개선 로드맵
