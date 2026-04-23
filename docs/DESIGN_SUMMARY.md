# 기술 설계 종합 요약 (6개 항목)

**작성일**: 2026-03-30 | **작성자**: @senior | **담당**: @coder (구현), @tester (검증)

---

## 문서 위치

- `docs/DESIGN_CRITICAL_SECURITY.md` — CRITICAL 3개 (보안)
- `docs/DESIGN_HIGH_REFACTOR.md` — HIGH 3개 (리팩터링/기능)

---

## 항목별 개요

### CRITICAL (Phase 1, 완료)

| # | 항목 | 설계서 | 핵심 |
|---|------|--------|------|
| 1 | Admin 패스워드 강제 변경 | CRITICAL § 1 | 초기 로그인 시 변경 강제 + CLI 검증 |
| 2 | API 토큰 만료 검증 | CRITICAL § 2 | JWT expiry, refresh 토큰, API 키 expires_at |
| 3 | CORS/CSRF 방어 | CRITICAL § 3 | CSRF 미들웨어, SameSite=Lax, Origin 검증 |

### HIGH (Phase 2, 구현 대기)

| # | 항목 | 설계서 | 핵심 |
|---|------|--------|------|
| 4 | admin.py 모듈 분리 | HIGH § 1 | 1293줄 → 5개 라우터 (200줄씩) |
| 5 | CodeNode 자동 파서 | HIGH § 2 | Python/JS AST 파싱 + 의존성 추출 |
| 6 | Celery 모니터링 | HIGH § 3 | FailedTask 테이블 + 대시보드 + 재시도 |

---

## 파일 변경 그룹 (병렬 작업 가능)

**그룹 A (보안)**: `app/auth/service.py`, `dependencies.py`, `router.py`, `app/db/auth_models.py`, `app/asgi/csrf_middleware.py`, `app/main.py`

**그룹 B (리팩터링)**: `app/routers/admin_*.py` (5개 신규), `admin.py` (통합)

**그룹 C (기능)**: `app/services/code_parser*.py` (3개), `app/db/celery_models.py`, `app/services/celery_monitoring.py`, `app/routers/admin_monitoring.py`

**공유 파일** (충돌 낮음): `app/main.py`, `app/db/database.py`, `app/worker/tasks.py`, `app/config.py`

---

## 구현 일정

| Phase | 항목 | 병렬 | 예상 |
|-------|------|------|------|
| 1 | CRITICAL 3개 | O | 2-3일 |
| 2 | HIGH 3개 | O | 3-4일 |
| Test | 통합 테스트 + 문서 | - | 2-3일 |
| **Total** | **6개 항목** | - | **7-10일** |

---

## DB 마이그레이션

`_apply_lightweight_migrations()` 순차 실행:
1. **Phase 1**: `mcper_users.password_changed_at` 컬럼 추가
2. **Phase 2**: `failed_tasks` 테이블 + 인덱스 생성

---

## 신규 환경 변수

```bash
SECURE_COOKIE=true                    # HTTPS only 쿠키
CORS_ALLOWED_ORIGINS=http://localhost:3000  # CORS 화이트리스트
```

---

## 롤백 계획

- **CRITICAL**: `git revert` + 마이그레이션 롤백, CSRF 미들웨어 비활성화
- **HIGH**: admin.py 복원, `auto_parse=false`, FailedTask는 기존 로직 변경 없음

---

## 성공 기준

- Admin 기본 패스워드 로그인 불가 (강제 변경)
- JWT 토큰 15분 후 자동 만료 (refresh 갱신 가능)
- CSRF 공격 시 403 Forbidden
- admin.py 각 모듈 ≤ 350줄
- Python/JS 파일 자동 파싱 (90%+ 정확도)
- 실패 태스크 재시도 UI 가능
