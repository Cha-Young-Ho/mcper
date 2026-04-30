# Docstring 스타일 가이드

## 기본 원칙

- 모든 **공개 함수·클래스**는 docstring 을 가진다. (`Q11-phase2` 기준 라우터 핸들러까지 전수 보강됨.)
- 언어는 **한국어**가 기본. 코드 심볼·기술 용어는 영어 원형 유지.
- 프라이빗 헬퍼(`_`로 시작)는 필요 시에만.

## 스타일: Google 스타일

새로 작성하는 docstring 은 Google 스타일을 따른다:

```python
def publish_app_rule(app_name: str, body: str, section_name: str | None = None) -> str:
    """새 app 룰 버전을 1개 추가한다.

    버전 번호는 서버가 (app_name, section_name) 기준으로 자동 부여한다.

    Args:
        app_name: 앱 식별자 (INI 의 `app_name` 값). 소문자로 정규화됨.
        body: 마크다운 본문 (verbatim 저장).
        section_name: 기본값 "main". 처음 쓰는 섹션이면 첫 버전(v1) 으로 생성.

    Returns:
        JSON 직렬화된 문자열: `{"scope": "app", "app_name": ..., "section_name": ..., "version": N}`.

    Raises:
        ValueError: `app_name` 이 비었을 때.
    """
```

### 섹션 순서

1. **요약** (한 줄, 마침표로 끝나는 명령조)
2. **상세 설명** (선택, 빈 줄 뒤)
3. **Args**
4. **Returns** (또는 `Yields` 제너레이터)
5. **Raises**
6. **Example** (복잡한 API 에 한해)

### MCP 도구 함수 예외

MCP `@mcp.tool()` 데코레이트 함수의 docstring 은 **LLM 이 tool description 으로 소비**하므로, Google 스타일보다 **자연어 호출 트리거·예시** 우선.

기존 MCP 도구 docstring 은 한국어 자연어 중심으로 작성되어 있으며, 그대로 유지한다. **새로 추가하는** MCP 도구는 아래 하이브리드 형태 권장:

```python
@mcp.tool()
def check_rule_versions(
    app_name: str | None = None,
    origin_url: str | None = None,
) -> str:
    """서버 DB 의 최신 룰 버전 번호(정수)만 JSON 으로 반환.

    로컬에 저장한 `<!-- rule_meta: … -->` 의 값과 비교해, 하나라도 다르면
    `get_global_rule` 로 다시 받아와 최신 본문으로 로컬을 갱신한다.

    Args:
        app_name: 없으면 global_version 만. 있으면 global + repo + app 3계층.
        origin_url: `git remote -v` 의 origin fetch URL.

    Returns:
        `{"global_version":3,"app_version":2,"repo_pattern":"api",...}` 형태의 JSON 문자열.
    """
```

## 기존 docstring 에 대한 정책

- **이미 Args/Returns 섹션이 있는 함수**: 그대로 유지.
- **자연어 중심 docstring (24+26 중 후자)**: 수정 금지. 현재 상태로 LLM/개발자 양쪽 가독성 충분.
- **docstring 이 아예 없는 함수**: 추가 시 위 스타일 적용.

## 자동 검증

- `ruff` 는 `D` 규칙(pydocstyle) 을 현재 비활성화한 상태. `pydocstyle` / `interrogate` 도입 여부는 별도 논의.
- `ast.parse` 기반 누락 검증은 CI 후보 (현재 수동):

```bash
python -c "
import ast
from pathlib import Path
missing = []
for p in Path('app').rglob('*.py'):
    if '__pycache__' in str(p): continue
    tree = ast.parse(p.read_text())
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not n.name.startswith('_') and ast.get_docstring(n) is None:
                missing.append(f'{p}:{n.lineno}:{n.name}')
print('missing docstrings:', len(missing))
"
```
