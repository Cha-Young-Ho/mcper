# Redis 세션 스토어 이관 설계 (L01/L02/L03)

근거: `docs/audit_2026-04-29.md` L01–L03. 리뷰·결정용.

## 1. 배경

OAuth/MCP 세션이 프로세스 메모리에 있음.

- `app/auth/mcp_oauth_provider.py:35-37` — `_auth_codes`/`_clients`/`_refresh_tokens` dict (**L01**)
- `app/auth/mcp_oauth_provider.py:257` — `_pending_auth_requests`/`_code_user_map`/`_access_tokens` (**L02**)
- `app/mcp_app.py:264` — `stateless_http=False`, `Mcp-Session-Id` 인메모리 (**L03**)

LB 뒤 다중 인스턴스면 A 발급 code 를 B 가 교환 시 실패, 로그인 폼이 다른 노드로 가면 `request_id` 유실, MCP 세션도 최초 노드 한정. 재시작 시 전부 유실. 단일 컨테이너인 지금은 무해하나 **수평 확장 전 필수.**

## 2. Redis 스키마

| 항목 | 키 | TTL | 원자성 |
|---|---|---|---|
| auth code | `mcper:oauth:code:{c}` | 300s | `GETDEL` |
| DCR client | `mcper:oauth:client:{cid}` | 30d/DB | - |
| refresh token | `mcper:oauth:refresh:{t}` | 30d | `GETDEL` rotate |
| pending auth | `mcper:oauth:pending:{rid}` | 300s | `GETDEL` |
| access 메타 | `mcper:oauth:access:{t}` | 3600s | DB 병행 |
| MCP session | `mcper:mcp:session:{sid}` | 1h sliding | §5 |

JSON 직렬화, `mcper:` prefix.

## 3. 추상화

```python
class OAuthStore(Protocol):
    def save_auth_code(self, code, data, ttl): ...
    def pop_auth_code(self, code) -> dict | None: ...
    def save_client(self, cid, data): ...
    def get_client(self, cid) -> dict | None: ...
    def save_refresh_token(self, t, data, ttl): ...
    def pop_refresh_token(self, t) -> dict | None: ...
    def save_pending(self, rid, data, ttl): ...
    def pop_pending(self, rid) -> dict | None: ...
```

`InMemoryOAuthStore`(기존 dict 래핑, 기본·테스트)와 `RedisOAuthStore`(`redis-py` async, `SET EX`/`GETDEL`). `MCPER_SESSION_STORE=memory|redis`, 기본 `memory`(하위 호환).

## 4. 마이그레이션 (롤백)

1. 설계·리뷰(본 문서) — 폐기
2. 추상화 도입, InMemory 래핑(동작 0) — revert
3. Redis 구현 + 테스트, flag `memory` — revert
4. staging `redis` E2E — 환경변수 즉시 복원
5. prod 전환, 개발 `memory` 유지 — 환경변수 복원

## 5. FastMCP `Mcp-Session-Id` (L03)

FastMCP SDK 의 외부 스토어 주입 API 는 공개되지 않은 것으로 보임(조사 시점 미해결).

- **임시(권장)**: LB sticky — Caddy `lb_policy cookie` / ALB stickiness(`Mcp-Session-Id` 헤더). 코드 0.
- **중장기**: 업스트림 PR 로 SessionStore 훅 또는 fork. `stateless_http=True` 복귀는 Claude Code init 이력 (`mcp_app.py:261-264`).

## 6. 보안

Redis AUTH + TLS, ACL 유저 `mcper:*` 한정. Refresh token 평문 대신 HMAC-SHA256 해시 저장 검토(`ApiKey.key_hash` 패턴). 역직렬화는 JSON 고정, pickle 금지.

## 7. 운영

장애 시 503 + 명시 에러(재로그인 유도), 재시도 큐는 과설계. 모니터링: connected_clients, keyspace, evicted_keys, 레이턴시. 용량: 1–2KB × 동시 1000 ≈ 2MB. `maxmemory-policy noeviction` + OOM 알람.

## 8. 견적

| 항목 | 공수 |
|---|---|
| 추상화 레이어 | 0.5d |
| Redis 구현 + 테스트 | 1.0d |
| Sticky LB(L03) | 0.5d |
| staging 검증 | 0.5d |
| **합계** | **2.5d** |

## 9. 오픈 질문

1. staging/prod 가용 Redis — Celery 와 공유/분리?
2. Sentinel/Cluster 요구, 단일 노드 시작 가능?
3. `Mcp-Session-Id` sticky 감수 vs SDK 업스트림 대기?
4. DCR client — Redis TTL vs DB 영속화?
