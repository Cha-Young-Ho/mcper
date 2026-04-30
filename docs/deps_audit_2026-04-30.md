# 의존성 보안 감사 리포트 — 2026-04-30 (S08)

**범위:** `requirements.txt`
**도구:** `pip-audit 2.10.0` (PyPI Advisory DB + OSV)
**근거 이슈:** `docs/audit_2026-04-29.md` — S08
**작성자:** @infra 위임 자동화 (Opus 4.7)

---

## 1. 실행 결과 (Before)

`pip-audit -r requirements.txt --desc` 결과 **3개 패키지에서 4건의 알려진 취약점** 발견.

| 패키지 | 현재 버전 | CVE / GHSA | Fixed In | 영향 |
|--------|-----------|------------|----------|------|
| `pdfminer.six` | `20221105` | **CVE-2025-64512** (CWE-502, RCE) | `20251107` | PDF 내부 CMap 경로 참조를 통한 `pickle.loads()` 임의 코드 실행. Windows(SMB/WebDAV)에서 원격 익스플로잇 용이. |
| `pdfminer.six` | `20221105` | **CVE-2025-70559** (CWE-502, LPE) | `20251230` | 공유 writable 디렉터리(`CMAP_PATH`)에 악성 `.pickle.gz` 배치 시 권한 상승. CVE-2025-64512 패치 우회. |
| `python-multipart` | `0.0.22` | **CVE-2026-40347** (DoS) | `0.0.26` | multipart preamble/epilogue 파싱 CPU 고갈. FastAPI 업로드 엔드포인트 영향. |
| `authlib` | `1.6.9` | **GHSA-jj8c-mmj3-mmgv** (CSRF) | `1.6.11` | `OAuth.cache` 사용 시 state 검증 누락 → OAuth 콜백 CSRF. 우리 프로젝트는 OAuth 미사용이라 노출 낮음. |

---

## 2. 적용한 업그레이드 (After)

안전 원칙: **메이저 버전 업 금지, 마이너/패치만.** 기존 `requirements.txt`의 주석·순서는 모두 보존.

| 패키지 | Before | After | 이유 |
|--------|--------|-------|------|
| `pdfminer.six` | `20221105` (2022-11-05) | `20260107` (2026-01-07, 최신 stable) | CVE-2025-64512/70559 패치 포함. 날짜형 릴리스라 "메이저" 개념이 없고, 공개 API(`high_level.extract_text`)는 안정. 스모크 테스트(import + `extract_text` 임포트) 통과. |
| `python-multipart` | `0.0.22` | `0.0.27` (최신 0.x 패치) | CVE-2026-40347 수정(0.0.26 이상). 0.0.x 시리즈 내 패치 bump. |
| `authlib` | `1.6.9` | `1.6.11` | GHSA-jj8c-mmj3-mmgv 핫픽스. 마이너(1.7.0)는 회피하고 1.6.x 패치 선. |

### 사후 검증

```
$ pip-audit -r requirements.txt
No known vulnerabilities found
```

### 스모크 테스트

```
$ pip install pdfminer.six==20260107
$ python -c "import pdfminer; from pdfminer.high_level import extract_text; print(pdfminer.__version__)"
20260107
```

현재 코드베이스 사용처:
- `app/services/document_parser.py` — `from pdfminer.high_level import extract_text` (API 유지)
- `app/logging_config.py` — 로거 이름(`pdfminer.*`) 억제 설정 (변경 불필요)

---

## 3. 이번 세션에서 **교체하지 않은** 항목

### 3.1 `python-jose[cryptography]==3.5.0` — PyJWT 마이그레이션 권고

**현재 상태 (2026-04-30 기준):**
- PyPI 최신 = `3.5.0` (2025-05-28 릴리스). 그 이전 릴리스 `3.4.0`은 2025-02, `3.3.0`은 2021-06.
- 업스트림 저장소(`mpdavis/python-jose`)는 2023년 이후 릴리스 주기가 급격히 느려졌고, 커뮤니티에선 **유지보수 불투명** 지표로 본다.
- 현재 `pip-audit` 기준 **공개 CVE는 없음** (과거 `ecdsa` 의존성 관련 이슈는 3.4.0에서 해결). 단, 응답성이 낮아 미래 CVE 대응이 느릴 수 있음.

**권고: PyJWT(`2.12.1`, 2026-03-13) 로 마이그레이션**
- PyJWT는 Pallets/Jazzband 권 유지보수로 활발(2026년 2차례 마이너 릴리스). Python 3.13 공식 지원.
- 우리 사용 범위는 단순 HS256 인코딩/디코딩(`exp` 검증) 수준이라 마이그레이션 비용 작음.

**사용처 (교체 대상 코드):**
- `app/auth/service.py`
  - `from jose import JWTError, jwt` → `import jwt` / `jwt.InvalidTokenError`
  - `jwt.encode(payload, key, algorithm="HS256")` — API 동일
  - `jwt.decode(token, key, algorithms=["HS256"], options={"verify_exp": ...})` — API 동일
  - 예외 타입: `JWTError` → `jwt.PyJWTError` (루트 클래스), `ExpiredSignatureError` → `jwt.ExpiredSignatureError`
- `app/auth/dependencies.py`
  - `from jose import ExpiredSignatureError, JWTError` → `from jwt import ExpiredSignatureError, PyJWTError`

**리스크:**
- python-jose 의 `exp` 자동 변환(`datetime` → `int`)이 PyJWT에도 동일 동작. 기존 테스트는 재사용 가능.
- JWS/JWE/JWK 고급 기능은 PyJWT 2.x 에서도 커버(단일 파일 키는 OK, JWKS 는 `PyJWKClient` 별도).

**작업 규모 추산:** 코드 변경 2파일 + 테스트 수정, 약 30분.

**이번 세션에서는 교체하지 않음** — 태스크 지시대로 단순 권고만 문서화.

### 3.2 기타 마이너(메이저 가능)

- `authlib 1.6.11 → 1.7.0` (2026-04-18): 이번엔 보수적으로 1.6.x 유지. OAuth 기능 실제 사용 시점에 재평가.
- `sentence-transformers 5.3.0`, `boto3 1.42.78`, `redis 6.4.0` 등은 CVE 경고 없음. 정기 bump 스케줄로 넘김.

---

## 4. 다음 세션 TODO (`S08 follow-up`)

- [ ] **[P1]** `python-jose` → `PyJWT` 마이그레이션 실행.
  - `requirements.txt` 에서 `python-jose[cryptography]==3.5.0` 제거, `PyJWT>=2.11,<3.0` 추가(`[crypto]` extra 고려).
  - `app/auth/service.py` 예외/임포트 치환.
  - `app/auth/dependencies.py` 예외/임포트 치환.
  - `tests/auth/` 단위 테스트 실행 + JWT 호환성(만료 토큰 재사용) 회귀 검증.
- [ ] **[P2]** CI 에 `pip-audit --strict -r requirements.txt` 게이트 추가. GitHub Actions / pre-release 단계에서 실패 시 차단.
- [ ] **[P3]** 분기별 의존성 bump 런북(`docs/RELIABILITY.md`) 반영. 본 리포트를 템플릿으로 사용.
- [ ] **[P3]** `authlib` 1.7.x 호환성 테스트 후 bump.

---

## 5. 변경 파일 요약

| 파일 | 변경 |
|------|------|
| `requirements.txt` | 3건 버전 bump (pdfminer.six, python-multipart, authlib) |
| `docs/deps_audit_2026-04-30.md` | 본 리포트 신규 생성 |

---

## 6. 남은 경고

- `pip-audit -r requirements.txt` → **0건** (High/Critical/Low 모두 0).
- 정책 차원의 권고(유지보수 불투명) → **1건** (python-jose, 본 리포트 §3.1 참고).
