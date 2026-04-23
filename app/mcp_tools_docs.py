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
        "one_liner": "기획서 내용과 관련 파일 경로를 specs 테이블에 INSERT (upload_document의 구 이름)",
        "title": "upload_document — 기획서 저장",
        "summary": (
            "기획서(스펙) 1건을 DB에 저장하고, 자동으로 청킹·임베딩 색인을 예약합니다. "
            "저장 후 Celery 워커가 백그라운드에서 청킹·임베딩을 처리하므로 "
            "search_documents로 검색되기까지 수 초~수십 초 소요됩니다."
        ),
        "params": [
            "content (필수): 기획서 전체 내용",
            "app_target (필수): 앱 식별자",
            "base_branch (필수): 기준 브랜치 (예: main)",
            "related_files (선택): 관련 소스 파일 경로 목록 또는 JSON 배열 문자열",
            "title (선택): 어드민 목록에 표시할 기획서 제목 (검색 식별자 역할)",
        ],
        "notes": [
            "upload_spec_to_db는 이전 이름. 현재 MCP 도구명은 upload_document.",
        ],
        "examples": [
            '`upload_document(content="…", app_target="your_app_name", base_branch="main", related_files=["src/payment/service.py"], title="결제 모듈 기획")`',
        ],
    },
    {
        "name": "search_spec_and_code",
        "one_liner": "현재 작업과 관련된 기획서를 키워드·벡터로 검색 (search_documents의 구 이름)",
        "title": "search_documents — 기획서 검색",
        "summary": (
            "특정 app_target 내 기획서를 벡터+FTS 하이브리드로 검색합니다. "
            "임베딩 인덱스가 없으면 키워드 ILIKE로 자동 대체됩니다. "
            "<b>find_historical_reference와의 차이</b>: "
            "search_documents는 키워드·주제로 기획서를 찾는 일반 검색이고, "
            "find_historical_reference는 기획서 초안 본문을 넘겨서 유사한 과거 기획을 찾는 유사도 검색입니다."
        ),
        "params": [
            "query (필수): 검색 키워드 또는 문장 (예: '결제 모듈', 'OAuth 인증')",
            "app_target (필수): 앱 식별자",
        ],
        "notes": [
            "search_spec_and_code는 이전 이름. 현재 MCP 도구명은 search_documents.",
            "벡터 인덱스 없으면 search_mode=legacy_ilike로 자동 대체.",
        ],
        "examples": [
            '`search_documents(query="결제", app_target="your_app_name")`',
            '`search_documents(query="OAuth 인증 플로우", app_target="your_app_name")`',
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
        "one_liner": "기획서 초안 본문과 의미적으로 유사한 과거 기획서를 찾아 관련 파일 경로 반환",
        "title": "find_historical_reference — 유사 기획서 탐색",
        "summary": (
            "작성 중인 기획서 텍스트를 넘기면, 임베딩 유사도로 과거 유사 기획서 청크와 "
            "관련 파일 경로(related_files)를 반환합니다. "
            "<b>search_documents와의 차이</b>: "
            "search_documents는 키워드 검색, "
            "find_historical_reference는 기획서 본문 전체를 의미적으로 비교합니다. "
            "코드 위치(related_files)까지 함께 반환해서 '과거에 이런 기능을 어느 파일에 구현했는지' 파악에 유용합니다."
        ),
        "params": [
            "new_spec_text (필수): 작성 중인 기획서 텍스트 (최대 8000자)",
            "app_target (필수): 앱 식별자",
            "top_n (선택, 기본값 5): 반환할 유사 기획서 개수",
        ],
        "notes": [
            "Celery index_spec 태스크로 기획서 청크 인덱스가 먼저 구축돼 있어야 합니다.",
            "upload_document 저장 후 인덱싱 완료까지 수십 초 소요.",
        ],
        "examples": [
            '`find_historical_reference(new_spec_text="알림 발송 기능을 추가한다...", app_target="your_app_name")`',
            '`find_historical_reference(new_spec_text="...", app_target="your_app_name", top_n=3)`',
        ],
    },
    # ── Skill search ─────────────────────────────────────────────
    {
        "name": "search_skills",
        "one_liner": "스킬을 벡터+FTS 하이브리드로 의미 검색 (관련 스킬만 반환)",
        "title": "search_skills — 스킬 의미 검색",
        "summary": (
            "등록된 스킬을 벡터+FTS 하이브리드(RRF)로 검색하여 쿼리와 관련된 스킬 청크만 반환합니다. "
            "get_global_skill은 전체 스킬을 로드하는 반면, search_skills는 스킬이 많을 때 "
            "관련 것만 빠르게 찾을 때 사용합니다."
        ),
        "params": [
            "query (필수): 검색 쿼리 (자연어)",
            "app_name (선택): 특정 앱 스킬만 검색",
            "scope (선택): 'all' | 'global' | 'app' | 'repo'",
            "top_n (선택, 기본값 10): 반환할 최대 결과 수",
        ],
        "notes": [
            "스킬 publish 시 자동으로 인덱싱됩니다.",
            "기존 스킬을 일괄 인덱싱하려면: scripts/reindex_all_skills.py 실행.",
            "벡터 인덱스 없으면 search_mode='no_index'로 빈 결과 반환.",
        ],
        "examples": [
            '`search_skills(query="테스트 관련", app_name="my_app")`',
            '`search_skills(query="보안 설정", scope="global")`',
        ],
    },
    # ── Harness docs ──────────────────────────────────────────────
    {
        "name": "sync_harness_docs",
        "one_liner": "MCPER 프로젝트 하네스 파일(CLAUDE.md, .agents/*.md 등)을 DB에 동기화",
        "title": "sync_harness_docs — 하네스 문서 동기화",
        "summary": (
            "프로젝트 루트의 하네스 파일(22개)을 읽어 specs 테이블에 동기화합니다. "
            "이미 동일한 내용이면 건너뛰고, 변경된 파일만 갱신 후 재색인합니다. "
            "app_target='mcper_harness'로 기존 기획서와 네임스페이스가 분리됩니다."
        ),
        "params": [],
        "notes": [
            "멱등(idempotent) — 여러 번 실행해도 안전합니다.",
            "Celery 있으면 비동기 색인, 없으면 동기 폴백.",
        ],
        "examples": ["`sync_harness_docs()`"],
    },
    {
        "name": "search_harness_docs",
        "one_liner": "MCPER 프로젝트 하네스 문서를 벡터+FTS 하이브리드로 검색",
        "title": "search_harness_docs — 하네스 문서 검색",
        "summary": (
            "하네스 문서(아키텍처, 에이전트 가이드, 설계 원칙 등)를 "
            "벡터+FTS 하이브리드로 검색합니다. scope로 범위를 제한할 수 있습니다."
        ),
        "params": [
            "query (필수): 검색어",
            "scope (선택): core / agent / guide / design / principles 중 하나",
        ],
        "notes": [
            "scope 생략 시 전체 하네스 문서에서 검색.",
            "임베딩 인덱스 없으면 ILIKE 폴백.",
        ],
        "examples": [
            '`search_harness_docs(query="보안 정책")`',
            '`search_harness_docs(query="코더 역할", scope="agent")`',
        ],
    },
    {
        "name": "get_harness_config",
        "one_liner": "특정 하네스 문서의 전체 내용을 이름으로 직접 조회",
        "title": "get_harness_config — 하네스 문서 직접 조회",
        "summary": (
            "문서 이름(예: CLAUDE, pm, ARCHITECTURE)으로 전체 내용을 반환합니다. "
            "검색이 아닌 직접 조회이므로 에이전트 부트스트래핑에 적합합니다."
        ),
        "params": [
            "target (필수): 문서 이름 (예: 'CLAUDE', 'pm', 'core-beliefs'). .md 접미사 생략 가능.",
        ],
        "notes": [
            "1순위: 제목 정확 매칭, 2순위: 파일 경로 stem 매칭, 3순위: 부분 매칭.",
            "미발견 시 등록된 문서 목록을 반환합니다.",
        ],
        "examples": [
            '`get_harness_config(target="CLAUDE")`',
            '`get_harness_config(target="pm")`',
            '`get_harness_config(target="core-beliefs")`',
        ],
    },
    {
        "name": "list_harness_docs",
        "one_liner": "등록된 모든 하네스 문서 목록 (제목, 범위, 경로, 길이)",
        "title": "list_harness_docs — 하네스 문서 목록",
        "summary": (
            "DB에 등록된 모든 하네스 문서의 제목, 범위(scope), 파일 경로, "
            "내용 길이를 반환합니다. sync_harness_docs 후 등록 상태를 확인할 때 유용합니다."
        ),
        "params": [],
        "notes": ["sync_harness_docs를 먼저 실행해야 결과가 표시됩니다."],
        "examples": ["`list_harness_docs()`"],
    },
    {
        "name": "upload_harness",
        "one_liner": "로컬 하네스 파일들을 MCP에 일괄 업로드 (스킬·룰 등록)",
        "title": "upload_harness — 하네스 일괄 업로드",
        "summary": (
            "로컬에 구축한 하네스 파일(.claude/agents/*.md, .claude/skills/*.md, "
            ".claude/docs/*.md, .claude/rules/*.md 등)을 읽어서 MCP에 스킬 또는 "
            "룰로 일괄 등록합니다. 이미 등록된 섹션은 새 버전으로 갱신됩니다."
        ),
        "params": [
            "app_name (str): 앱 식별자 (예: 'my_app')",
            "files (list[dict]): 파일 목록. 각 항목: path, content, type('skill'|'rule'), "
            "scope('app'|'repo'), section_name",
            "origin_url (str, optional): git remote origin URL (repo scope 매칭용)",
        ],
        "notes": [
            "type='skill'이 기본값. 규칙 파일은 type='rule'로 지정.",
            "scope='repo'로 지정하면 origin_url에서 추출한 패턴으로 repo 스킬/룰 등록.",
            "section_name 생략 시 파일명에서 자동 추출.",
        ],
        "examples": [
            '`upload_harness(app_name="my_app", files=[{"path":".claude/agents/code.md","content":"...","section_name":"agent-code"}])`',
        ],
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
