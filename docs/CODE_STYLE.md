# 코딩 스타일 가이드

**저장소**: stz-game-service

## Python

### 형식
- **라인 길이**: 100자 이내
- **들여쓰기**: 4칸 (공백)
- **린팅**: ruff, black

### 명명규칙

| 대상 | 규칙 | 예시 |
|------|------|------|
| 함수 | snake_case | `validate_password()` |
| 클래스 | PascalCase | `CodeParser` |
| 상수 | UPPER_SNAKE | `MAX_RETRIES` |
| 변수 | snake_case | `user_id` |
| Private | `_prefix` | `_internal_method()` |

### 타입 힌팅

```python
# ✅ 좋음
def create_user(name: str, age: int) -> User:
    pass

# ❌ 나쁨
def create_user(name, age):
    pass
```

## JavaScript/TypeScript

### 형식
- **라인 길이**: 100자 이내
- **들여쓰기**: 2칸 (공백)
- **세미콜론**: 필수

### 명명규칙

| 대상 | 규칙 | 예시 |
|------|------|------|
| 함수 | camelCase | `validatePassword()` |
| 클래스 | PascalCase | `CodeParser` |
| 상수 | UPPER_SNAKE | `MAX_RETRIES` |
| 변수 | camelCase | `userId` |

## 일반 규칙

1. **주석**: 왜(Why)를 설명, 무엇(What)은 코드가 설명
2. **함수**: 한 가지 역할만 (SRP)
3. **복잡도**: 순환 복잡도 < 10
4. **테스트**: 모든 공개 함수에 테스트
