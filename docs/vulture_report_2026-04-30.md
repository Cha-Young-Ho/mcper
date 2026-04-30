# Vulture 데드코드 스캔 리포트 (2026-04-30) — Q13

## 실행 환경

- 도구: `vulture 2.16`
- 명령: `vulture app/ --min-confidence 80`
- 브랜치: `worktree-agent-afe175c1c6fe9a7c4` (base `33c4f8e fix : caddy 설정`)

## 초기 스캔 결과 (수정 전)

```text
app/auth/mcp_oauth_provider.py:15: unused import 'AnyUrl' (90% confidence)
app/auth/mcp_oauth_provider.py:18: unused import 'OAuthAuthorizationServerProvider' (90% confidence)
app/db/skill_models.py:16: unused import 'Index' (90% confidence)
app/main.py:222: unused import '_Req' (90% confidence)
app/main.py:223: unused import '_Resp' (90% confidence)
app/metrics.py:14: unused import 'CONTENT_TYPE_LATEST' (90% confidence)
app/metrics.py:14: unused import 'generate_latest' (90% confidence)
app/routers/admin_rules.py:1713: unused variable 'rule_id' (100% confidence)
app/routers/admin_rules.py:1717: unused variable 'admin' (100% confidence)
app/routers/admin_rules.py:1751: unused variable 'rule_id' (100% confidence)
app/routers/admin_rules.py:1754: unused variable 'admin' (100% confidence)
app/routers/admin_rules.py:1772: unused variable 'admin' (100% confidence)
app/routers/admin_rules.py:1786: unused variable 'admin' (100% confidence)
app/routers/admin_specs.py:365: unused variable 'admin' (100% confidence)
app/services/versioned_skills.py:426: unused variable 'section_display' (100% confidence)
app/services/versioned_workflows.py:441: unused variable 'section_display' (100% confidence)
app/tools/global_rules.py:12: unused import 'rollback_repo_rule' (90% confidence)
```

총 17건 (90%+ 신뢰도).

## 분류

### A. 제거한 항목 (8건)

| # | 위치 | 유형 | 근거 |
|---|------|------|------|
| 1 | `app/auth/mcp_oauth_provider.py:15` | `from pydantic import AnyUrl` | 파일·tests 전체에서 import 라인 외 참조 0 |
| 2 | `app/auth/mcp_oauth_provider.py:18` | `OAuthAuthorizationServerProvider` | `McperOAuthProvider` 는 상속 없이 duck-typed, 실제 사용 0 |
| 3 | `app/db/skill_models.py:16` | `Index` | 파일 내 1회(import 자체)만 등장 |
| 4 | `app/main.py:222` | `Request as _Req` | 별칭 쓴 뒤 재참조 없음 |
| 5 | `app/main.py:223` | `Response as _Resp` | 동일 |
| 6 | `app/tools/global_rules.py:31` | `rollback_repo_rule` | 같은 파일의 `rollback_app_rule` / `rollback_global_rule` 은 tool 본체에서 실제 호출되지만 `rollback_repo_rule` 은 단순 import 잔재 |
| 7 | `app/services/versioned_skills.py:426` | `_skill_file_block(section_display)` 파라미터 | 함수 본체에서 한 번도 사용되지 않는 dead 파라미터. 호출처 3곳의 `display` 로컬 변수도 같이 제거 |
| 8 | `app/services/versioned_workflows.py:441` | `_workflow_file_block(section_display)` 파라미터 | 동일 패턴. 호출처 3곳 + 단위 테스트 1곳 시그니처 업데이트 |

#### grep 이중 확인 (제거 직전 검증)

```bash
# 1-2. AnyUrl / OAuthAuthorizationServerProvider
grep -rn "AnyUrl" app/ tests/              # → import 라인(1회)만
grep -rn "OAuthAuthorizationServerProvider" app/ tests/  # → import 라인(1회)만

# 3. Index
grep -c "Index" app/db/skill_models.py     # → 1 (import 본인)

# 4-5. _Req / _Resp
grep -n "_Req\|_Resp" app/main.py          # → import 2줄만

# 6. rollback_repo_rule
grep -n "rollback_repo_rule" app/tools/global_rules.py  # → 1 (import 본인)
# cf. rollback_app_rule / rollback_global_rule 은 본체에서 사용 (유지)

# 7. section_display in _skill_file_block
grep -rn "_skill_file_block" app/ tests/   # → 정의 1 + 호출 3, 함수 본체에 section_display 0회

# 8. section_display in _workflow_file_block
grep -rn "_workflow_file_block" app/ tests/  # → 정의 1 + 호출 3 + 단위테스트 1, 본체에 section_display 0회
```

### B. 남긴 항목 (9건) — 근거

#### B.1 FastAPI 라우트 파라미터 의존성 (7건, vulture false-positive)

| 위치 | 이름 | 남긴 이유 |
|------|------|----------|
| `app/routers/admin_rules.py:1713` | `rule_id: int` | FastAPI path parameter (URL 매칭에 필수) |
| `app/routers/admin_rules.py:1717` | `admin: str = Depends(require_admin_user)` | auth guard dependency. 파라미터 삭제 시 라우트 전체가 미인증으로 열림 |
| `app/routers/admin_rules.py:1751` | `rule_id` | 동일 (path param) |
| `app/routers/admin_rules.py:1754` | `admin` | 동일 (auth guard) |
| `app/routers/admin_rules.py:1772` | `admin` | 동일 |
| `app/routers/admin_rules.py:1786` | `admin` | 동일 |
| `app/routers/admin_specs.py:365` | `admin` | 동일 |

`vulture` 는 FastAPI `Depends(...)` 의 부수효과와 path param 의미론을 인식하지 못함. CLAUDE.md 지침에 따라 **삭제 금지**.

#### B.2 의도적 보존 (2건)

| 위치 | 이름 | 남긴 이유 |
|------|------|----------|
| `app/metrics.py:14` | `generate_latest` | Prometheus 클라이언트 표준 엔트리포인트. 현재 `/metrics` HTTP 엔드포인트가 아직 등록되지 않았지만 `PrometheusMiddleware.SKIP_PATHS` 에 `/metrics` 경로가 예약되어 있어 곧 필요 |
| `app/metrics.py:14` | `CONTENT_TYPE_LATEST` | 동일. 위 엔드포인트 구현 시 응답 Content-Type 헤더 용도 |

보수적 판단으로 유지. 리포트에만 기록.

## 수정 후 재스캔 결과

```text
app/metrics.py:14: unused import 'CONTENT_TYPE_LATEST' (90% confidence)
app/metrics.py:14: unused import 'generate_latest' (90% confidence)
app/routers/admin_rules.py:1713: unused variable 'rule_id' (100% confidence)
app/routers/admin_rules.py:1717: unused variable 'admin' (100% confidence)
app/routers/admin_rules.py:1751: unused variable 'rule_id' (100% confidence)
app/routers/admin_rules.py:1754: unused variable 'admin' (100% confidence)
app/routers/admin_rules.py:1772: unused variable 'admin' (100% confidence)
app/routers/admin_rules.py:1786: unused variable 'admin' (100% confidence)
app/routers/admin_specs.py:365: unused variable 'admin' (100% confidence)
```

잔존 9건 모두 의도적으로 유지 (위 B 표). 진짜 데드코드는 0건.

## 영향 요약

- 변경 파일 7개 (앱 6 + 테스트 1)
- 순삭제 라인: `-21 / +10`
- `ruff` 린트 오류: 14 → 8 (6 감소, 모두 F401 import-unused 해소)
- 모듈 import 스모크 테스트 통과 (`python -c "from app.services import ..."`)
- `_skill_file_block` / `_workflow_file_block` 함수 호출 결과 스모크 테스트 통과

PostgreSQL 기반 단위 테스트(`tests/unit/test_versioned_workflows_full.py`)는 로컬 DB 없음으로 **사전 실행 불가** (pre-existing); 본 변경과 무관. 테스트 파일 자체의 시그니처는 업데이트 완료.

## 향후 개선 (Out of Scope)

- `app/metrics.py` `/metrics` 엔드포인트 등록 — `generate_latest` / `CONTENT_TYPE_LATEST` 를 실제 사용하도록
- `vulture --ignore-decorators '@router.*' --ignore-decorators '@app.*'` 화이트리스트 확정 후 CI 편입 검토
- 90% 신뢰도 남은 import 중 `app/main.py` 내부 local import (`httpx`, `ClientRegistrationOptions`, `RevocationOptions`) — 이번 스캔 `--min-confidence 80` 상에서 vulture 가 감지 못했으나 ruff 는 F401 보고. 분리된 후속 작업으로 처리 권장.
