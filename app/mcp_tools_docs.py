"""MCP 도구 설명 — 어드민 UI (Tools 탭 + 대시보드)."""

from __future__ import annotations

from typing import Any

# 표시 순서 = 사이드바 / 대시보드 순서
MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_global_rule",
        "one_liner": "DB에서 글로벌·레포지토리·앱 룰을 마크다운으로 조회 (워크스페이스 진입 시 필수)",
        "title": "get_global_rule — 룰 조회",
        "summary": (
            "Postgres에 저장된 **글로벌 · 레포지토리(URL 패턴) · 앱** 룰을 마크다운으로 반환합니다. "
            "`app_name`을 전달하면 **`git remote -v`로 얻은 origin URL을 `origin_url`로 함께 넘기는 것을 권장**합니다 (Docker MCP도 레포 룰 매칭 가능). "
            "생략하면 서버가 `repo_root` 기반으로 origin을 읽습니다."
        ),
        "params": [
            "app_name (선택): INI 앱 식별자. 생략 시 **글로벌 룰만** 반환.",
            "version (선택): 생략·null·latest → 최신. 숫자 지정 시 해당 버전 (없으면 최신 폴백). "
            "app_name 없으면 글로벌에만 적용, 있으면 **앱 룰에만** 적용 (글로벌·레포는 항상 최신).",
            "origin_url (선택, app_name 있으면 권장): `git remote -v` origin fetch URL. 전체 출력을 그대로 넘겨도 서버가 URL 추출.",
            "repo_root (선택): 서버 Git 메타데이터 경로. 생략 시 `GIT_REPO_ROOT` 또는 서버 CWD 사용.",
        ],
        "notes": [
            "publish와 달리 조회만 합니다. 버전 관리는 서버의 publish_* 툴이 자동 증가.",
            "`origin_url`이 있으면 레포 매칭에서 우선 적용됩니다. 서버 Git 실패와 무관하게 API/웹 패턴 룰을 적용할 수 있습니다.",
            "app_name 제공 시 응답에 로컬 저장 절차가 포함됩니다. MCP는 마크다운만 제공.",
            "`__default__` 앱 스트림 포함 여부는 **앱별** 설정 (/admin 앱 카드·보드). 앱 행이 없으면 글로벌 룰 보드의 **글로벌 기본값**으로 폴백.",
            "매칭된 패턴과 레포 `default` 스트림 포함 여부는 **패턴별** 설정 (/admin 레포지토리 룰 카드).",
        ],
        "examples": [
            "최초 부트스트랩 (앱 미확인): `get_global_rule()`",
            "권장: `get_global_rule(app_name=\"your_app_name\", origin_url=\"git@github.com:org/repo.git\")`",
            "full remote 출력 그대로: `get_global_rule(app_name=\"your_app_name\", origin_url=\"origin  git@github.com:org/r.git (fetch)\")`",
            "서버 Git 경로 지정: `get_global_rule(app_name=\"your_app_name\", repo_root=\"/path/to/repo\")`",
            "특정 앱 버전 조회: `get_global_rule(app_name=\"your_app_name\", version=3)`",
            "글로벌 특정 버전: `get_global_rule(version=2)`",
        ],
    },
    {
        "name": "check_rule_versions",
        "one_liner": "서버 DB에서 최신 룰 버전 번호만 JSON으로 조회 (로컬과 불일치 시 get_global_rule로 갱신)",
        "title": "check_rule_versions — 버전 확인",
        "summary": (
            "글로벌 / (선택) 앱 / (선택) 레포 매칭 결과의 **최신 버전 번호(정수)만** 반환합니다. "
            "로컬 룰 파일의 rule_meta·팀 노트와 비교해 **내용이 다르면 최신으로 갱신**하는 데 사용합니다."
        ),
        "params": [
            "app_name (선택): 제공 시 해당 앱 스트림·레포 매칭 포함.",
            "origin_url (선택): `git remote -v` origin fetch URL — 레포 버전 판단에 사용.",
            "repo_root (선택): 서버 Git 보조 경로.",
        ],
        "notes": [
            "버전은 정수로만 표현됩니다: 1, 2, 3… (v1 같은 문자열 포맷 아님).",
            "`mcp_include_app_default`는 `app_name` 있을 때만 true/false, 없으면 null (앱별·글로벌 기본값 반영). `mcp_include_repo_default`는 매칭된 레포 패턴 기준.",
        ],
        "examples": [
            '`check_rule_versions()`',
            '`check_rule_versions(app_name="your_app_name", origin_url="git@github.com:org/repo.git")`',
        ],
    },
    {
        "name": "publish_global_rule",
        "one_liner": "글로벌 룰 신규 버전 저장 (버전 번호는 서버 자동 부여)",
        "title": "publish_global_rule — 글로벌 룰 신규 버전",
        "summary": "글로벌 룰에 새 버전을 하나 추가합니다. 버전 번호는 서버가 자동으로 부여합니다.",
        "params": [
            "body (필수): 완전한 마크다운 본문. 다음 글로벌 버전(1, 2, 3…)으로 불변 저장.",
        ],
        "notes": [
            "클라이언트에서 버전을 직접 지정할 수 없습니다.",
        ],
        "examples": [
            '`publish_global_rule(body="# 새 글로벌 룰\\n\\n- …")`',
        ],
    },
    {
        "name": "publish_app_rule",
        "one_liner": "앱 룰 특정 섹션에 신규 버전 저장 (버전 자동 부여)",
        "title": "publish_app_rule — 앱 룰 신규 버전 (섹션 지원)",
        "summary": (
            "특정 app_name + section_name 스트림에 새 버전을 하나 추가합니다. "
            "버전은 (앱, 섹션) 조합별로 1부터 순차 증가합니다. "
            "해당 섹션이 없으면 자동으로 첫 버전(v1)이 생성됩니다."
        ),
        "params": [
            "app_name (필수): INI 식별자. 예: your_app_name, __default__.",
            "body (필수): 해당 섹션의 마크다운 전체 본문.",
            "section_name (선택): 기본값 'main'. 예: 'admin_rules', 'code_rules'.",
        ],
        "notes": [
            "버전 인수는 없음 (서버 자동 부여).",
            "섹션 이름은 소문자+언더스코어 권장. 예: main, admin_rules, data_processing.",
            "처음 쓰는 섹션명을 넘기면 자동으로 그 섹션의 v1이 생성됨.",
        ],
        "examples": [
            '`publish_app_rule(app_name="your_app", body="## 메인\\n\\n- …")` — main 섹션',
            '`publish_app_rule(app_name="your_app", section_name="admin_rules", body="## 어드민\\n\\n- …")`',
        ],
    },
    {
        "name": "publish_section_rule",
        "one_liner": "앱 룰 특정 섹션에 신규 버전 저장 (섹션 명시 전용 툴)",
        "title": "publish_section_rule — 섹션 전용 발행",
        "summary": (
            "`publish_app_rule` 의 `section_name` 파라미터 버전과 동일하지만, "
            "섹션을 반드시 명시해야 할 때 더 직관적인 이름으로 사용합니다. "
            "해당 섹션이 없으면 자동으로 v1 생성."
        ),
        "params": [
            "app_name (필수): INI 식별자.",
            "section_name (필수): 섹션 이름. 예: admin_rules, code_rules, data_processing.",
            "body (필수): 섹션 전체 본문 (기존 내용 대체).",
        ],
        "notes": [
            "처음 쓰는 섹션명을 넘기면 그 섹션의 v1이 생성됨.",
            "기존 내용에 덧붙이려면 `append_to_app_rule(section_name=...)` 사용.",
        ],
        "examples": [
            '`publish_section_rule(app_name="myapp", section_name="admin_rules", body="## 어드민 룰\\n\\n- …")`',
            '`publish_section_rule(app_name="myapp", section_name="code_rules", body="## 코드 룰\\n\\n- …")`',
        ],
    },
    {
        "name": "list_rule_sections",
        "one_liner": "앱/레포/글로벌 룰의 섹션 목록과 최신 버전 번호 조회",
        "title": "list_rule_sections — 섹션 목록 조회",
        "summary": (
            "지정한 앱/레포/글로벌 룰의 모든 섹션 이름과 각 섹션의 최신 버전 번호를 반환합니다. "
            "섹션별로 `get_global_rule` 또는 `publish_section_rule` 을 호출할 때 섹션 이름 확인에 사용합니다."
        ),
        "params": [
            "app_name (선택): 앱 섹션 목록 조회 시 사용.",
            "repo_pattern (선택): 레포지토리 섹션 목록 조회 시 사용.",
            "둘 다 없으면: 글로벌 룰 섹션 목록.",
        ],
        "notes": [
            "반환 예: `{\"scope\": \"app\", \"app_name\": \"myapp\", \"sections\": [{\"section_name\": \"main\", \"latest_version\": 3}]}`",
        ],
        "examples": [
            '`list_rule_sections(app_name="myapp")` — 앱 섹션 목록',
            '`list_rule_sections()` — 글로벌 섹션 목록',
            '`list_rule_sections(repo_pattern="github.com/org")` — 레포 섹션 목록',
        ],
    },
    {
        "name": "append_to_app_rule",
        "one_liner": "최신 앱 룰 섹션에 마크다운을 덧붙여 새 버전으로 저장",
        "title": "append_to_app_rule — 앱 룰 내용 추가 (섹션 지원)",
        "summary": (
            "주어진 `app_name` + `section_name` 의 **최신** 버전에 `append_markdown`을 덧붙여 **다음 버전**으로 저장합니다. "
            "DB에 해당 섹션이 **없으면** 제공된 내용만으로 **버전 1**을 생성합니다."
        ),
        "params": [
            "app_name (필수): INI 식별자.",
            "append_markdown (필수): 기존 최신 내용 **뒤에** 추가할 마크다운.",
            "section_name (선택): 기본값 'main'.",
        ],
        "notes": [
            "'앱 룰에 ~~ 추가해줘' 같은 요청에 특화. 전체 교체는 `publish_app_rule` 사용.",
            "section_name 지정 시 해당 섹션의 최신 버전에 덧붙임.",
        ],
        "examples": [
            '`append_to_app_rule(app_name="myapp", append_markdown="\\n## 신규\\n\\n- 항목")`',
            '`append_to_app_rule(app_name="myapp", section_name="admin_rules", append_markdown="…")`',
        ],
    },
    {
        "name": "publish_repo_rule",
        "one_liner": "origin URL 패턴별 레포지토리 룰 신규 버전 저장 (섹션 지원)",
        "title": "publish_repo_rule — 레포지토리 룰 신규 버전",
        "summary": (
            "`git remote` origin URL을 **부분 문자열**로 매칭하는 패턴 스트림에 새 버전을 추가합니다. "
            "빈 패턴은 다른 패턴이 매칭되지 않을 때 폴백으로 동작합니다. "
            "`section_name` 으로 섹션 분리 가능."
        ),
        "params": [
            "pattern (필수): URL에 포함되면 매칭되는 문자열 (빈 문자열 = 폴백).",
            "body (필수): 마크다운 전체 본문.",
            "section_name (선택): 기본값 'main'.",
        ],
        "notes": [
            "버전은 (패턴, 섹션) 조합별로 독립적으로 1부터 증가.",
        ],
        "examples": [
            '`publish_repo_rule(pattern="api", body="## API\\n\\n- …")`',
            '`publish_repo_rule(pattern="api", section_name="ci_rules", body="## CI\\n\\n- …")`',
        ],
    },
    {
        "name": "upload_spec_to_db",
        "one_liner": "기획서 내용과 관련 파일 경로를 specs 테이블에 INSERT",
        "title": "upload_spec_to_db — 기획서 저장",
        "summary": "기획서 내용과 메타데이터를 specs 테이블에 INSERT합니다.",
        "params": [
            "content, app_target, base_branch (필수)",
            "related_files: 목록 또는 JSON 배열 문자열, 선택",
            "title (선택): 어드민 목록에 표시할 기획서 제목",
        ],
        "notes": [],
        "examples": [
            '`upload_spec_to_db(content="…", app_target="your_app_name", base_branch="main", related_files=["a.php"], title="결제기획")`',
        ],
    },
    {
        "name": "search_spec_and_code",
        "one_liner": "앱별 기획서 내용과 파일 경로를 키워드 검색 (JSON 결과 반환)",
        "title": "search_spec_and_code — 기획서 검색",
        "summary": "특정 app_target 내 기획서 내용과 관련 파일 경로를 ILIKE 검색. 최대 50건 JSON 반환.",
        "params": [
            "query, app_target (필수)",
        ],
        "notes": [],
        "examples": [
            '`search_spec_and_code(query="결제", app_target="your_app_name")`',
        ],
    },
    {
        "name": "push_spec_chunks_with_embeddings",
        "one_liner": "로컬에서 임베딩한 기획서 청크를 spec_chunks에 직접 반영 (워커 부하 시 폴백)",
        "title": "push_spec_chunks_with_embeddings — 로컬 벡터 직접 삽입",
        "summary": (
            "서버 Celery 큐가 밀리거나 임베딩 GPU가 병목일 때, 에이전트가 **동일 차원** 벡터를 직접 생성해 한꺼번에 삽입합니다. "
            "해당 spec_id의 기존 청크를 먼저 삭제 후 교체합니다."
        ),
        "params": [
            "spec_id (필수): specs.id",
            "chunks_json: JSON 배열 문자열 — 각 요소에 content, embedding(float[]), metadata(선택) 포함",
        ],
        "notes": [
            "벡터 차원과 모델이 서버 `embedding.dim`·`embedding.provider` 및 해당 모델 필드(local_model·openai_model·localhost_model·bedrock 등)와 일치해야 합니다.",
            "권장 패턴: 먼저 `upload_spec_to_db`로 spec 행 생성 후 이 툴로 청크만 채우기.",
        ],
        "examples": [
            '`push_spec_chunks_with_embeddings(spec_id=1, chunks_json="[{\\"content\\":\\"…\\",\\"embedding\\":[…]}]")`',
        ],
    },
    {
        "name": "push_code_index",
        "one_liner": "코드 AST/심볼 인덱스를 Celery 워커 큐에 푸시 (임베딩은 워커에서 처리)",
        "title": "push_code_index — 코드 그래프 인덱싱",
        "summary": (
            "nodes·edges JSON을 받아 `index_code_batch` 태스크를 큐에 등록합니다. "
            "`file_paths`와 매칭되는 기존 노드를 먼저 삭제 후 재삽입합니다."
        ),
        "params": [
            "app_target (필수)",
            "file_paths: 경로 목록 또는 JSON 배열 문자열",
            "nodes: stable_id, file_path, symbol_name, kind, content",
            "edges: source_stable_id, target_stable_id, relation (예: CALLS)",
        ],
        "notes": ["CELERY_BROKER_URL + 워커 컨테이너가 필요합니다."],
        "examples": [],
    },
    {
        "name": "analyze_code_impact",
        "one_liner": "쿼리로 코드 노드를 찾아 호출 그래프에서 상위/하위 영향 범위 수집",
        "title": "analyze_code_impact — 영향 범위 분석 (그래프)",
        "summary": "pgvector+FTS로 시드 노드를 찾은 뒤 code_edges를 BFS로 탐색해 상위/하위 노드를 수집, JSON 반환.",
        "params": ["query", "app_target"],
        "notes": ["push_code_index로 인덱스가 있어야 의미 있음."],
        "examples": [],
    },
    {
        "name": "find_historical_reference",
        "one_liner": "새 기획서 텍스트와 유사한 과거 기획서 청크를 찾아 관련 파일 경로 반환",
        "title": "find_historical_reference — 유사 기획서 참조",
        "summary": "임베딩 유사도로 상위 N개 spec_chunks와 관련 파일 경로를 반환합니다 (Few-shot 참조용).",
        "params": ["new_spec_text", "app_target", "top_n (선택, 기본값 5)"],
        "notes": ["Celery index_spec으로 기획서 청크 인덱스가 먼저 구축돼 있어야 합니다."],
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
