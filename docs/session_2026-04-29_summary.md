# mcper 세션 요약 — 2026-04-29

**컨텍스트**: 하네스 엔지니어링 기반 대규모 리팩터링 세션. 감사 → 자동화 툴 → 스케일/LB 준비 → P1 품질 개선 순서.

## 누적 변경 (origin/main 대비 26 커밋 ahead)

### 신규 기능

| 영역 | 커밋 | 내용 |
|---|---|---|
| MCP | `57116e2` | stateless_http=False — Claude Code OAuth 호환 |
| Docs 타입 | `250f405` | Rules/Skills/Workflows와 동급의 "Docs" 컨텐츠 타입 풀 복제 (Workflows 미러) |
| Mermaid | `220702f` `2b33b22` `de8e888` `ebe8e4b` | 워크플로우 버전별 Mermaid 다이어그램 — "한눈에 보기" 버튼 + 모달 + MCP 도구 |

### 감사 & 설계 문서

| 파일 | 설명 |
|---|---|
| `docs/audit_2026-04-29.md` | 36건 전체 감사 (P0×5 / P1×17 / P2×14) |
| `docs/design-docs/session-store-redis.md` | Redis 세션 스토어 이관 설계 (L01/L02/L03) |
| `docs/design-docs/embedding-provider-migration.md` | 임베딩 외부화 설계 — C안(sidecar) 추천 |
| `docs/design-docs/pgbouncer-setup.md` | PgBouncer 도입 설계 |

### Phase 4 — 품질/보안/성능 수정

| ID | 커밋 | 내용 |
|---|---|---|
| Q01/Q02 | `e9d0e74` | 공통 헬퍼 추출 (`admin_common.py`, `tools/_common.py`) |
| S01/S02/S03/S06 | `633f178` | 인증 기본값 기동 차단 (changeme/empty secret) |
| P01/P02 | `9491f76` | admin-rules N+1 쿼리 제거 (101쿼리 → 3쿼리) |
| S04 | `1f82814` | postgres 테이블명 화이트리스트 |
| S05 | `6ff8bb8` | data_tools TOCTOU 제거 |
| P03 | `dce2e93` | versioned 테이블 `created_at` 인덱스 9개 |
| P06 | `f77f46e` | `list_sections_*` DB 정렬 (9개 함수) |
| P07 | `9edc802` | 카드 목록 페이지네이션 (8개 엔드포인트) |
| L07/L08 | `727b71f` | Celery result backend 명시 + beat 가이드 |
| Q05 | `17a6799` | `versioned_*` 지연 import 제거 |

### Phase 3 — 스케일/LB 대비 (실구현)

| ID | 커밋 | 내용 |
|---|---|---|
| L09 | `6cc8525` | `/health/live`, `/health/ready`, `/health/startup` 3단계 분리 |
| L10 | `0d5c4d5` | Redis 연결 풀 싱글톤 (`app/services/redis_pool.py`) |
| L11 | `36a68ca` | ContextVar 디버그 헬퍼 |
| L01-L03 | `203b2ae` `5539da5` | SessionStore 추상화 + Redis 구현 (`MCPER_SESSION_STORE=memory|redis`) |
| L04-L05 | `2ff0eb4` `6788ccb` | 임베딩 sidecar 컨테이너 + `EMBEDDING_PROVIDER=sidecar` |
| L06 | `1c508bf` | PgBouncer 컨테이너 + DB 풀 환경변수화 |

### 부가

| 커밋 | 내용 |
|---|---|
| `284d7f6` | `.env.local` ADMIN_PASSWORD 랜덤 값 (S02 수정 후 기동 위해) |
| `a60be47` | 감사 리포트 |

## 이번 세션 아키텍처 결정

### "기본값에선 동작 변경 0" 원칙

모든 스케일 기능이 환경변수 토글로 활성화:
- `MCPER_SESSION_STORE=memory` (기본) / `redis`
- `EMBEDDING_PROVIDER=local` (기본) / `sidecar`
- docker-compose profile `sidecar-embed`, `pgbouncer` (기본 기동 제외)
- `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` 환경변수

즉 프로덕션 롤아웃은 **코드 변경 없이 env/profile 토글** 로 진행 가능.

### LB 배치 시나리오 (현재 상태)

1. `MCPER_SESSION_STORE=redis` + `REDIS_URL` 설정
2. `docker compose --profile sidecar-embed up -d embed` + web에 `EMBEDDING_PROVIDER=sidecar`
3. `docker compose --profile pgbouncer up -d pgbouncer` + `DATABASE_URL` 포트 변경
4. Caddy/ALB sticky session (`Mcp-Session-Id` cookie) 활성화
5. `docker compose up -d --scale web=N`

## 새 세션에 해야 할 일 (우선순위 순)

### 즉시 가능 (환경 문제 없으면)

#### 1. `git push` — 현재 26 커밋 ahead
```bash
cd /Users/wemadeplay/workspace/personal/mcper
git push origin main
```

#### 2. worktree 정리
```bash
# 아직 참조 가능 상태. Q03 재시도 때까지 유지해도 됨.
# 정리하려면:
git worktree list
for wt in .claude/worktrees/*/; do
  git worktree unlock "$wt" 2>/dev/null
  git worktree remove "$wt" --force 2>/dev/null
done
git worktree prune
```

### 다음 세션 주요 작업

#### 3. **Q03 + Q04 묶어서 admin_rules 리팩터링** (높은 우선순위)
- **Q03**: `admin_rules.py` 1,849줄 → 3파일 분할 (`admin_rules_global/app/repo.py`)
- **Q04**: 라우터에서 `select()`, `delete()` 직접 호출 → `app/services/admin_rules_service.py` 로 이동
- worktree `worktree-agent-a94e1c1eb4f1bc501` 에 Q03 분할 초안 있음 (`8498783`). 단, main 기준 충돌 있음 — **main 기준으로 재분할 권장**
- 같은 패턴 `admin_skills/workflows/docs.py` 도 고려 (각 1,119줄)
- 예상 소요: 한 세션 통째

#### 4. **Phase 2 자동화 (ruff format)**
worktree `worktree-agent-a9384bb1d8a6b61b9` 에 있지만 충돌로 cherry-pick 불가. **main 에서 직접 실행**:
```bash
source .venv/bin/activate
ruff format app/ scripts/ tests/
ruff check --fix app/ scripts/ tests/
git diff --stat   # 확인
git commit -am "style: ruff format + lint fixes"
```
예상: 수천 줄 수정, 의미 변경 없음. 단독 커밋 1개.

#### 5. **Phase 3 고급 항목** (필요 시)
- Celery beat 실제 사용 시작 시 `celery-redbeat` 도입
- Redis Sentinel/Cluster 구성 (운영 환경 요구사항에 따라)
- PgBouncer transaction pooling 전환 검증

#### 6. **감사 리포트 남은 P2** (14건, 선택사항)
| 그룹 | 예상 | 소요 |
|---|---|---|
| 성능 P08~P12 (커밋 배치/JSON 재파싱/ORDER BY/SELECT 명시/캐싱) | 5건 | 1세션 |
| 품질 Q06~Q14 (타입힌트/Depends/에러/ConfigMerger/테스트/docstring/데드코드/응답스키마) | 9건 | 2~3세션 |
| 보안 S07~S09 (에러스키마/구식 의존성/테스트 compose 암호) | 3건 | 반세션 |

## 현재 상태 검증

- **Routes**: 240 (Mermaid 도구 + Docs 라우터 + 헬스 3종 추가)
- **MCP tools**: 51
- **DB 테이블**: 등록 완료 (doc_chunks, global_doc_versions 등)
- **컨테이너**: `spec-mcp-web-1` 정상 기동 (새 ADMIN_PASSWORD 적용됨)
- **헬스 엔드포인트**: `/health/live`, `/health/ready`, `/health/startup`, `/health/rag`, `/health` 모두 HTTP 200

## 새 세션 시작 시 첫 체크리스트

```bash
# 1. 현 상태 확인
cd /Users/wemadeplay/workspace/personal/mcper
git status
git log --oneline origin/main..HEAD | wc -l   # 26 이상이면 push 안 됨

# 2. 이 요약 문서 읽기
cat docs/session_2026-04-29_summary.md

# 3. 감사 리포트 재확인 (우선순위 조정할지)
cat docs/audit_2026-04-29.md | head -100

# 4. 컨테이너 살아있는지
docker ps --filter name=spec-mcp | tail -n +2

# 5. 각 엔드포인트 건강 확인
docker exec spec-mcp-web-1 curl -s http://localhost:8000/health/live
docker exec spec-mcp-web-1 curl -s http://localhost:8000/health/ready
```

## 주의사항 (새 세션 주의)

1. **worktree 여러 개 locked 상태** — `git worktree list` 로 확인. Q03 재시도 전까지는 `a94e1c1eb4f1bc501` 보존.
2. **`infra/docker/.env.local`** 에 실제 랜덤 비번 있음. 새 배포 시 다른 값 사용.
3. **Mermaid 테스트 데이터** `adventure/spec-implementation/v1`, `adventure/error-hunt/v1` 에 샘플 다이어그램 주입돼 있음.
4. **Global Rule v4** 에 "모든 프롬프트 실행 전 MCP 3종 검색" 규칙 추가됨 — Claude Code가 이 규칙을 따르도록 요구.
