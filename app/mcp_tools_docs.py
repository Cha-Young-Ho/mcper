"""MCP tool descriptions for admin UI (Tools tab + dashboard)."""

from __future__ import annotations

from typing import Any

# Order = sidebar / dashboard 표시 순서
MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_global_rule",
        "one_liner": "DB에서 global / repository / 앱 룰 마크다운 조회 (워크스페이스 진입 시 필수)",
        "title": "get_global_rule — 룰 조회",
        "summary": (
            "Postgres에 저장된 **global · repository(URL 패턴) · app** 룰을 마크다운으로 가져온다. "
            "`app_name` 이 있으면 **에이전트가 `git remote -v` 로 얻은 URL 을 `origin_url` 로 넘기는 것을 권장**(Docker MCP 에서도 Repository 매칭 가능). "
            "없으면 서버가 `repo_root` 기준으로 origin 을 읽는다."
        ),
        "params": [
            "app_name (선택): INI 앱 식별자. 없으면 **global 룰만**.",
            "version (선택): 생략·null·latest → 최신. 숫자면 해당 버전(없으면 서버가 최신으로 폴백). "
            "app_name 없을 때는 global에만 적용, 있을 때는 **앱 룰에만** 적용(global·repo는 항상 최신).",
            "origin_url (선택, app_name 있을 때 권장): `git remote -v` 의 origin fetch URL. 통째 출력도 가능(서버가 URL 추출).",
            "repo_root (선택): 서버 Git 메타용 경로. 생략 시 `GIT_REPO_ROOT` 또는 서버 CWD.",
        ],
        "notes": [
            "발행(publish)과 달리 조회만 한다. 버전 저장은 publish_* 툴이 서버에서 자동 증가한다.",
            "`origin_url` 이 있으면 repository 매칭에 우선 사용. 서버 Git 실패와 무관하게 api/web 패턴 룰 적용 가능.",
            "app_name 있을 때 응답 말미에 로컬 저장 절차 포함. MCP는 마크다운만 제공.",
            "`__default__` 앱 스트림을 전용 앱과 함께 줄지는 **앱별** 설정(/admin 앱 카드·앱 보드). 앱별 행이 없으면 Global rules 보드의 **전역 기본값**.",
            "Repository `default` 스트림을 매칭된 패턴과 함께 줄지는 **패턴별** 설정(/admin Repository rules 카드).",
        ],
        "examples": [
            "첫 부트스트랩(앱 모름): `get_global_rule()`",
            "권장: `get_global_rule(app_name=\"your_app_name\", origin_url=\"git@github.com:org/repo.git\")`",
            "3단 + remote 한 줄 통째: `get_global_rule(app_name=\"your_app_name\", origin_url=\"origin  git@github.com:org/r.git (fetch)\")`",
            "서버 Git 경로: `get_global_rule(app_name=\"your_app_name\", repo_root=\"/path/to/repo\")`",
            "특정 앱 버전: `get_global_rule(app_name=\"your_app_name\", version=3)`",
            "글로벌만 특정 버전: `get_global_rule(version=2)`",
        ],
    },
    {
        "name": "check_rule_versions",
        "one_liner": "서버 DB 최신 룰 버전 번호만 JSON으로 조회 (로컬과 불일치 시 get_global_rule 로 갱신)",
        "title": "check_rule_versions — 버전 점검",
        "summary": (
            "global / (선택) app / (선택) repository 매칭 결과의 **최신 버전 정수**만 반환한다. "
            "로컬 규칙 파일의 rule_meta·팀 메모와 비교해 다르면 **최신 본문으로 수정**하라는 용도."
        ),
        "params": [
            "app_name (선택): 있으면 해당 앱 스트림·repo 매칭까지 포함.",
            "origin_url (선택): `git remote -v` origin fetch URL — repository 버전 판별에 사용.",
            "repo_root (선택): 서버 Git 보조.",
        ],
        "notes": [
            "버전 표기는 정수 1,2,3… 만 (문자열 v1 형식 아님).",
            "`mcp_include_app_default` 는 `app_name` 이 있을 때만 true/false, 없으면 null (앱별·전역 기본 반영). `mcp_include_repo_default` 는 매칭된 repository 패턴 기준.",
        ],
        "examples": [
            '`check_rule_versions()`',
            '`check_rule_versions(app_name="your_app_name", origin_url="git@github.com:org/repo.git")`',
        ],
    },
    {
        "name": "publish_global_rule",
        "one_liner": "전역 룰 새 버전 저장 (버전 번호는 서버 자동)",
        "title": "publish_global_rule — global 새 버전",
        "summary": "전역 룰에 새 버전을 1개 추가한다. 버전 번호는 서버가 자동으로 붙인다.",
        "params": [
            "body (필수): Markdown 전체. 다음 global 버전(1,2,3…)으로 immutable 저장.",
        ],
        "notes": [
            "클라이언트가 version을 지정할 수 없다.",
        ],
        "examples": [
            '`publish_global_rule(body="# 새 전역 규칙\\n\\n- …")`',
        ],
    },
    {
        "name": "publish_app_rule",
        "one_liner": "특정 앱 룰 새 버전 저장 (버전 번호는 서버 자동)",
        "title": "publish_app_rule — 앱 룰 새 버전",
        "summary": "특정 app_name 스트림에 새 버전을 1개 추가한다. 버전은 앱별로 1부터 순증.",
        "params": [
            "app_name (필수): 예 your_app_name, __default__.",
            "body (필수): 해당 앱용 Markdown(레포/도메인 가이드를 한 덩어리로).",
        ],
        "notes": [
            "역시 version 인자는 없다.",
        ],
        "examples": [
            '`publish_app_rule(app_name="your_app_name", body="## your_app_name\\n\\n- …")`',
        ],
    },
    {
        "name": "append_to_app_rule",
        "one_liner": "앱 룰 최신 본문 뒤에 마크다운 덧붙여 새 버전 저장",
        "title": "append_to_app_rule — 앱 룰 이어 붙이기",
        "summary": (
            "해당 `app_name` 의 **최신** app_rule_versions 본문 뒤에 `append_markdown` 을 붙여 "
            "**다음 버전**으로 저장한다. **DB에 해당 앱이 없으면** 넘긴 내용만으로 **버전 1** 생성; 있으면 최신 뒤에 붙여 2, 3, …."
        ),
        "params": [
            "app_name (필수): 예 your_app_name.",
            "append_markdown (필수): 기존 최신 본문 **뒤에** 붙일 Markdown (비어 있으면 오류).",
        ],
        "notes": [
            "「앱 룰에 ~~ 추가해줘」 같은 요청에 맞춤. 전체 교체는 `publish_app_rule`.",
        ],
        "examples": [
            '`append_to_app_rule(app_name="your_app_name", append_markdown="\\n## 신규\\n\\n- 항목")`',
        ],
    },
    {
        "name": "publish_repo_rule",
        "one_liner": "origin URL 패턴별 repository 룰 새 버전 저장 (버전은 서버 자동)",
        "title": "publish_repo_rule — Repository 룰 새 버전",
        "summary": (
            "`git remote` origin URL에 **부분문자열**로 매칭되는 패턴 스트림에 새 버전을 추가한다. "
            "빈 패턴은 다른 패턴이 안 맞을 때 폴백으로 사용한다."
        ),
        "params": [
            "pattern (필수): URL에 포함되면 매칭되는 문자열(빈 문자열 = 폴백 스트림).",
            "body (필수): Markdown 전체.",
        ],
        "notes": [
            "패턴별 버전은 1부터 독립 증가. sort_order는 어드민에서 첫 버전 생성 시 또는 기존 스트림에서 유지.",
        ],
        "examples": [
            '`publish_repo_rule(pattern="api", body="## API\\n\\n- …")`',
            '`publish_repo_rule(pattern="", body="## Fallback\\n\\n- …")`',
        ],
    },
    {
        "name": "upload_spec_to_db",
        "one_liner": "기획서 본문·연결 파일 경로를 specs 테이블에 INSERT",
        "title": "upload_spec_to_db — 기획서 저장",
        "summary": "specs 테이블에 기획/스펙 본문과 메타를 INSERT 한다.",
        "params": [
            "content, app_target, base_branch (필수)",
            "related_files: 리스트 또는 JSON 배열 문자열, 생략 가능",
            "title (선택): 어드민 목록에 보일 기획서 제목",
        ],
        "notes": [],
        "examples": [
            '`upload_spec_to_db(content="…", app_target="your_app_name", base_branch="main", related_files=["a.php"], title="결제기획")`',
        ],
    },
    {
        "name": "search_spec_and_code",
        "one_liner": "앱 단위로 기획서 본문·파일 경로 키워드 검색 (JSON)",
        "title": "search_spec_and_code — 스펙 검색",
        "summary": "특정 app_target 안에서 본문·연결 파일 경로 ILIKE 검색. 최대 50건 JSON 반환.",
        "params": [
            "query, app_target (필수)",
        ],
        "notes": [],
        "examples": [
            '`search_spec_and_code(query="결제", app_target="your_app_name")`',
        ],
    },
    {
        "name": "push_code_index",
        "one_liner": "코드 AST/심볼 인덱스를 Celery 워커 큐에 넣음 (임베딩은 워커에서)",
        "title": "push_code_index — 코드 그래프 인덱싱",
        "summary": (
            "노드·엣지 JSON을 받아 `index_code_batch` 태스크를 큐에 넣는다. "
            "`file_paths`에 해당하는 기존 노드는 삭제 후 재삽입된다."
        ),
        "params": [
            "app_target (필수)",
            "file_paths: 경로 리스트 또는 JSON 배열 문자열",
            "nodes: stable_id, file_path, symbol_name, kind, content",
            "edges: source_stable_id, target_stable_id, relation (예: CALLS)",
        ],
        "notes": ["CELERY_BROKER_URL + worker 컨테이너 필요"],
        "examples": [],
    },
    {
        "name": "analyze_code_impact",
        "one_liner": "질의로 시드 코드 노드 찾고 호출 그래프 상·하류 수집",
        "title": "analyze_code_impact — 영향도(그래프)",
        "summary": "pgvector+FTS로 시드 노드 후 code_edges BFS로 upstream/downstream JSON 반환.",
        "params": ["query", "app_target"],
        "notes": ["push_code_index로 인덱스가 있어야 의미 있음"],
        "examples": [],
    },
    {
        "name": "find_historical_reference",
        "one_liner": "신규 기획서 텍스트와 유사한 과거 스펙 청크 + related_files",
        "title": "find_historical_reference — 유사 기획 참조",
        "summary": "임베딩 유사도로 spec_chunks 상위 N건과 연결 파일 경로를 반환 (Few-shot 참고용).",
        "params": ["new_spec_text", "app_target", "top_n (선택, 기본 5)"],
        "notes": ["스펙 청크 인덱스(Celery index_spec) 선행"],
        "examples": [],
    },
]


def tools_with_counts(counts: dict[str, int]) -> tuple[list[dict[str, Any]], int]:
    """Attach call_count to each tool; compute total."""
    total = 0
    out: list[dict[str, Any]] = []
    for t in MCP_TOOLS:
        c = int(counts.get(t["name"], 0))
        total += c
        row = {**t, "call_count": c}
        out.append(row)
    return out, total
