# 커밋 가이드

**저장소**: stz-game-service

## 형식

```
<type>: <description>

<body (optional)>
```

## 타입

| 타입 | 설명 | 예시 |
|------|------|------|
| **feat** | 새 기능 | feat: 패스워드 강제 변경 |
| **fix** | 버그 수정 | fix: 토큰 만료 검증 |
| **docs** | 문서 수정 | docs: README 갱신 |
| **refactor** | 코드 리팩토링 | refactor: admin.py 분리 |
| **test** | 테스트 추가 | test: 단위 테스트 +40 |
| **chore** | 빌드, 의존성 | chore: pytest 버전 업 |

## 규칙

1. **소문자로 시작**
2. **명령형 현재시제** (하지말고, 합니다 아님)
3. **마침표 제거**
4. **50자 이내** (설명이 길면 body 사용)

## 예시

```bash
# ✅ 좋음
git commit -m "feat: 패스워드 강제 변경

- validate_password() 추가 (12자 + 특수문자)
- lifespan 훅에서 기본 패스워드 확인"

# ❌ 나쁨
git commit -m "패스워드 강제 변경을 했습니다"
git commit -m "Fixed bugs"
```
