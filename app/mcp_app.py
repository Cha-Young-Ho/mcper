"""Shared FastMCP instance and tool registration."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from app.tools.global_rules import register_global_rule_tool
from app.tools.rag_tools import register_rag_tools
from app.tools.documents import register_document_tools
from app.tools.data_tools import register_data_tools
from app.tools.skill_tools import register_skill_tools
from app.tools.harness_tools import register_harness_tools
from app.tools.workflow_tools import register_workflow_tools
from app.tools.doc_tools import register_doc_tools

# ── MCP OAuth 인증 설정 ────────────────────────────────────────────
# MCPER_AUTH_ENABLED: Admin UI auth (로그인 페이지/세션)
# MCPER_MCP_AUTH_ENABLED: MCP 엔드포인트 OAuth (RFC 명세상 HTTPS 필수).
#   HTTP 개발 환경에서는 false 로 두고, HTTPS 도메인 붙인 뒤 true 로 전환.
#   미설정 시 _AUTH_ENABLED 값을 따라감 (기존 동작 호환).
_AUTH_ENABLED = os.environ.get("MCPER_AUTH_ENABLED", "false").lower() in ("1", "true", "yes")
_MCP_AUTH_RAW = os.environ.get("MCPER_MCP_AUTH_ENABLED")
if _MCP_AUTH_RAW is None:
    _MCP_AUTH_ENABLED = _AUTH_ENABLED
else:
    _MCP_AUTH_ENABLED = _MCP_AUTH_RAW.lower() in ("1", "true", "yes")

_mcp_auth_kwargs: dict = {}
if _MCP_AUTH_ENABLED:
    from mcp.server.auth.settings import AuthSettings as McpAuthSettings
    from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
    from pydantic import AnyHttpUrl

    from app.auth.mcp_oauth_provider import McperOAuthProvider

    # issuer_url / resource_server_url: 런타임에 실제 URL 사용
    # MCP SDK 는 issuer_url 에 HTTPS 를 강제하므로, MCPER_MCP_AUTH_ENABLED=true 일 때는 기본 https.
    # MCPER_PUBLIC_SCHEME 로 명시 override 가능 (예: 로컬 테스트 시 "http").
    _server_port = os.environ.get("PORT") or os.environ.get("UVICORN_PORT") or "8001"
    _server_host = os.environ.get("MCPER_PUBLIC_HOST") or f"localhost:{_server_port}"
    _scheme = os.environ.get("MCPER_PUBLIC_SCHEME") or (
        "https" if ("443" in _server_host or _MCP_AUTH_ENABLED) else "http"
    )
    _base_url = f"{_scheme}://{_server_host}"

    # MCP 앱이 /mcp에 마운트되므로, issuer_url도 /mcp 경로 포함
    _mcp_mount = os.environ.get("MCP_MOUNT_PATH", "/mcp").rstrip("/") or "/mcp"
    _mcp_auth_kwargs = {
        "auth_server_provider": McperOAuthProvider(login_url=f"{_base_url}/auth/mcp-authorize"),
        "auth": McpAuthSettings(
            issuer_url=AnyHttpUrl(f"{_base_url}{_mcp_mount}"),
            resource_server_url=AnyHttpUrl(f"{_base_url}{_mcp_mount}/"),
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["mcp:tools"],
                default_scopes=["mcp:tools"],
            ),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=["mcp:tools"],
        ),
    }

# Cursor는 URL 기반 MCP에 Streamable HTTP를 우선 사용한다.
# FastAPI에 ``Mount("/mcp", ...)`` 할 때 내부 라우트는 ``/`` 로 두는 게 일반적이다.
mcp = FastMCP(
    "Spec MCP Server",
    instructions=(
        # ── 0. 공통 전제: app_name 식별 ──
        "[app_name 확인] "
        "프로젝트 루트의 config.dev.ini 또는 config.ini 에서 [Global] > app_name 값을 읽는다. "
        "파일이 없으면 사용자에게 app_name 을 직접 물어본다. 폴더명·브랜치명으로 추측 금지. "
        "INI app_name 식별자만 사용(예: my_app). /master 등 접미사 금지. "
        "origin_url 은 git remote -v 의 origin fetch URL. "

        # ── 0-1. 공통 전제: 룰 로드 (모든 워크플로우의 선행 조건) ──
        "[룰 로드 — 자동 선행] "
        "다음 구문을 감지하면 즉시 실행 (사용자 확인 불필요): "
        "'프로젝트 시작', '프로젝트 시작해', 'project init', 'init project', "
        "'이 프로젝트 룰 가져와', '룰 가져와', '룰 불러와', '규칙 가져와', 'load rules', 'get rules', "
        "'이 프로젝트 정보 가져와', '프로젝트 데이터 가져와', "
        "'리모트 mcp를 이용해서', 'MCP 연결해서', 'MCP로'. "
        "절차: "
        "(1) app_name 확인. "
        "(2) get_global_rule(app_name, origin_url) — 행동 지침(Global+Repo+App 3계층) 로드. "
        "(3) check_rule_versions — 버전 비교, 로컬과 다르면 재호출해 최신으로 갱신. "
        "주의: 스킬(Skills)은 이 단계에서 로드하지 않는다. 컨텍스트 절약을 위해 "
        "실제 작업 수행 시 필요한 스킬만 on-demand로 조회한다. "
        "이 룰 로드는 3개 워크플로우 모두의 선행 조건이다. 룰이 로드되지 않은 상태에서 워크플로우가 시작되면 자동으로 먼저 실행한다. "

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 워크플로우 1 — 기획서 구현 (Spec Implementation)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        "[워크플로우 1 — 기획서 구현] "
        "다음 구문을 감지하면 실행: "
        "'기획서 구현해줘', '기획서 참고해서', '기획 구현', '스펙 구현', 'implement spec', "
        "'이 기획대로 만들어줘', '기획서대로 개발해줘', '구현해줘', 'implement this'. "
        "전체 흐름: 기획서 수령 → 분석 → 설계 → 구현 → 테스트 → 수정 → 완료 → 하네스 업데이트 → 컴파운드 업데이트. "
        "절차: "
        "(1) [준비] 룰이 아직 로드되지 않았으면 룰 로드를 먼저 실행한다. "
        "(2) [기획 확인] search_documents(query=기획서 키워드, app_target=app_name) — 관련 기획서 검색. "
        "    사용자가 직접 기획서를 제공하면 그것을 사용. "
        "(3) [스킬 조회] search_skills(query=작업 키워드, app_name=app_name) — compound-* 스킬 우선 확인. "
        "    search_rules(query=작업 키워드, app_name=app_name) — 적용 규칙 확인. "
        "(4) [분석·설계] @pm이 타당성·범위 판단 → @planner가 유저스토리·수용기준 작성 → @senior가 아키텍처·API/DB 스펙 설계. "
        "(5) [구현·테스트] @coder가 설계 기반 구현 + @tester가 테스트 작성 (병렬). "
        "    Rules의 ✅/❌ 항목을 준수하며 구현. 위반 발견 시 사용자에게 명시적 알림. "
        "(6) [검수] @infra가 보안·성능·배포 관점 최종 검토. "
        "(7) [수정] 검수에서 발견된 문제 수정 → 재테스트. "
        "(8) [하네스 업데이트] 작업 중 새로 파악된 패턴·구조가 있으면 하네스 문서에 반영. "
        "    upload_harness 또는 publish_app_skill_tool로 갱신. "
        "(9) [컴파운드 업데이트] @compounder 실행 — docs/dev_log.md의 compound records를 파싱하여 "
        "    반복 실수·피드백을 스킬로 추출·발행. search_skills로 발행 검증. "
        "에이전트 시퀀스: @pm → @planner → @senior → @coder + @tester (병렬) → @infra → 하네스 → @compounder. "
        "단순 작업(버그픽스 등): 중간 단계 생략 가능. 하네스·컴파운드 업데이트는 항상 실행. "

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 워크플로우 2 — 기획서 스캔 (Spec Scan)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        "[워크플로우 2 — 기획서 스캔] "
        "다음 구문을 감지하면 실행: "
        "'spec scan', 'scan spec', '기획서 스캔', '기획서 분석해줘', "
        "'이 기획서 코드로 구현해야 해?', 'should we implement this?', "
        "'기획서 검토', 'review this spec', 'spec review', "
        "'구현해야 할지 판단해줘', '이거 구현해야 해?'. "
        "전체 흐름: 기획서 수령 → 분석 → 구현 판단 → 스킬 등록 → 하네스 업데이트 → 컴파운드 업데이트. "
        "절차: "
        "(1) [준비] 룰이 아직 로드되지 않았으면 룰 로드를 먼저 실행한다. "
        "(2) [기획서 수령] 사용자가 제공하는 기획서를 받는다 (텍스트, 파일 경로, 또는 search_documents 결과). "
        "(3) [스킬 조회] search_skills(query=기획서 키워드, app_name=app_name) — 기존 compound-* 스킬 우선 확인. "
        "(4) [분석] @senior가 분석: "
        "    - 이 기획서가 코드 구현이 필요한가? "
        "    - 구현 범위(scope)는? "
        "    - 의존성(dependencies)은? "
        "    - 기존 코드와의 충돌·중복은? "
        "(5) [판단] 구현 판정: YES / NO / PARTIAL. "
        "    YES → 워크플로우 1로 연결 가능함을 안내. "
        "    NO → 사유 설명 (이미 존재, 불필요, 범위 밖 등). "
        "    PARTIAL → 구현 필요 부분과 불필요 부분을 구분. "
        "(6) [스킬 등록] 대화 중 파악된 유용한 패턴·판단 기준을 publish_app_skill_tool로 등록. "
        "(7) [하네스 업데이트] 새로 파악된 패턴·구조가 있으면 하네스 문서에 반영. "
        "(8) [컴파운드 업데이트] @compounder 실행 — 세션 중 교정·피드백을 스킬로 추출·발행. "
        "에이전트 시퀀스: @senior → 하네스 → @compounder. "
        "출력: 구현 판정(YES/NO/PARTIAL), 범위 추정, 의존성 목록, 등록된 스킬. "

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 워크플로우 3 — 에러 헌트 (Error Hunt)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        "[워크플로우 3 — 에러 헌트] "
        "다음 구문을 감지하면 실행: "
        "'error hunt', '에러 찾아줘', '에러 분석', 'find error', 'debug this', "
        "'에러 헌트', '이 에러 뭐야', 'what is this error', '로그 분석해줘', "
        "'서버 에러', 'server error', '에러 찾기'. "
        "전체 흐름: 에러 접수 → 코드베이스 확인 → 진단 → 분류(코드/EC2/설정) → 수정 권고 → 하네스 업데이트 → 컴파운드 업데이트. "
        "절차: "
        "(1) [준비] 룰이 아직 로드되지 않았으면 룰 로드를 먼저 실행한다. "
        "(2) [코드베이스 확인] 사용자에게 묻기: '어떤 코드베이스인가요? (로컬 디렉터리 경로를 알려주세요)'. "
        "    디렉터리 경로를 받은 후 코드베이스 구조를 읽는다. "
        "(3) [에러 수집] 사용자에게서 에러 상세를 받는다 (로그, 에러 메시지, 스택 트레이스). "
        "    cmux 터미널 스킬로 터미널 출력을 읽을 수 있으면 사용한다. "
        "    터미널 화면을 읽을 수 없으면 사용자에게 요청: "
        "    '터미널을 새로 분할해서 해당 서버에 접속해주세요. 그리고 해당 터미널의 suffix 이름을 알려주세요.' "
        "    suffix 이름을 받은 후 cmux로 해당 터미널 화면을 읽는다. "
        "(4) [스킬 조회] search_skills(query=에러 키워드, app_name=app_name) — compound-* 스킬에서 동일 에러 사례 확인. "
        "(5) [진단] 에러를 코드베이스와 대조 분석: "
        "    - 코드 버그? → 파일과 라인 식별. "
        "    - EC2/인프라 이슈? → 시스템 컴포넌트 식별 (nginx, php-fpm, 디스크, 네트워크). "
        "    - 설정 불일치? → 환경 설정 비교. "
        "(6) [환경] 항상 Linux. 사용자는 EC2 인스턴스에서 코드를 실행한다. "
        "(7) **원격 실행 절대 금지**: "
        "    라이브/프로덕션 서버에서 다음 명령을 절대 제안하거나 실행하지 않는다: "
        "    rm, rm -rf, rmdir, systemctl restart, systemctl stop, service restart, "
        "    kill, killall, pkill, shutdown, reboot, "
        "    DROP TABLE, DELETE FROM, TRUNCATE, "
        "    chmod 777, chown, iptables -F, "
        "    실행 중 서비스를 수정하거나 데이터를 삭제하거나 시스템 상태를 변경하는 모든 명령. "
        "    분석은 READ-ONLY. 수정 방법은 제안만 하고 파괴적 명령은 절대 실행하지 않는다. "
        "(8) [결과] 에러 분류 (code/infra/config), 근본 원인, 수정 권고, 영향 파일. "
        "(9) [하네스 업데이트] 에러 패턴·진단 지식이 재사용 가능하면 하네스 문서에 반영. "
        "(10) [컴파운드 업데이트] @compounder 실행 — 에러 진단 과정의 실수·교정·피드백을 스킬로 추출·발행. "
        "에이전트 시퀀스: 진단 → 하네스 → @compounder. "

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 유틸리티 — 하네스 업로드 (독립 실행 가능)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        "[유틸리티 — 하네스 업로드] "
        "다음 구문을 감지하면 실행: "
        "'하네스 올려줘', '하네스 업로드', '로컬 스킬 올려줘', '스킬 등록해줘', "
        "'MCP에 올려줘', 'upload harness', '하네스 공유', '하네스 등록', "
        "'이 프로젝트 하네스 올려줘', '로컬 하네스 MCP에'. "
        "절차: "
        "(1) app_name 확인 + origin_url 확인 (git remote -v). "
        "(2) 로컬 하네스 파일들을 읽는다: "
        "CLAUDE.md, .claude/agents/*.md, .claude/skills/*/skill.md, .claude/docs/*.md, .claude/rules/*.md 등. "
        "(3) 각 파일을 분류한다: "
        "agents/*.md → type='skill', section_name='agent-{이름}'. "
        "skills/*/skill.md → type='skill', section_name='{스킬이름}'. "
        "docs/*.md → type='skill', section_name='{문서이름}'. "
        "rules/*.md → type='rule', section_name='{규칙이름}'. "
        "CLAUDE.md → type='skill', section_name='claude-md'. "
        "(4) upload_harness(app_name, files=[...], origin_url) 호출 — 일괄 등록. "
        "(5) 결과를 사용자에게 보고 (업로드 건수, 에러, 버전 정보). "
        "(6) 이미 등록된 섹션이 있으면 새 버전으로 갱신된다 (기존 버전 보존). "

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 공통 — 작업 전 검색, 행동 강령, 설정
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        "[일반 작업 — MCP 자동 활용 / 작업 전 검색 필수] "
        "위 워크플로우에 해당하지 않는 일반 요청이라도, **모든 코드 작성·수정·설계·리팩터링 작업 전에 반드시** search_rules와 search_skills를 호출한다: "
        "(a) search_rules(query=작업 키워드, app_name=app_name) → 해당 작업에 적용되는 규칙 확인. "
        "(b) search_skills(query=작업 키워드, app_name=app_name) → 관련 시스템 지식·패턴 확인. "
        "검색 결과 중 compound-* 섹션은 과거 실수/피드백에서 추출된 학습 스킬이므로 우선 참고한다. "
        "(c) 검색 결과의 Rule은 반드시 준수, Skill은 참고. 검색 결과가 없으면 일반 베스트 프랙티스로 진행. "
        "(d) 이 검색은 **자동으로** 수행한다. 사용자에게 '검색할까요?'라고 묻지 않는다. "
        "추가: "
        "(e) 기존 기능이나 기획을 참고해야 할 때 → search_documents로 검색. "
        "(f) 코드 변경 영향 범위 파악 시 → analyze_code_impact 사용. "
        "(g) 유사 기획서가 필요할 때 → find_historical_reference (기획서 초안 텍스트 기반 유사도 검색). "
        "search_documents와 find_historical_reference 구분: 키워드로 '찾는' 것은 search, 초안 본문으로 '비교'하는 것은 find_historical_reference. "

        "[행동 강령] "
        "Rules(행동 지침)은 코드 작성·리뷰·설계 시 항상 먼저 확인. "
        "✅/❌ 항목은 협의 없이 위반 불가. 위반 발견 시 사용자에게 명시적으로 알린다. "
        "Skills(스킬)는 시스템 구조·패턴 파악에 활용. 로컬에 저장하지 않으며 필요 시 MCP에서 on-demand 조회. "
        "적용 우선순위: Rules 위반 확인 → 필요 Skills on-demand 조회 → 사용자 요청 수행. "

        "[저장 규칙] "
        "Cursor: .cursor/rules/mcp-rules.mdc. Claude Code: CLAUDE.md 또는 .claude/ 하위. "
        "응답 말미 [CRITICAL — ...] 지시에 따라 IDE별 경로에 저장. Docker MCP는 호스트 클론 경로. "
        "Skills는 로컬에 저장하지 않는다. 필요할 때 MCP에서 on-demand로 조회하여 참고만 한다. "

        "[조회 옵션] version 생략·null·latest=최신, 숫자=해당 버전(없으면 최신 폴백). "
        "app_name 없으면 global 만; app_name 있으면 global+repository(URL 패턴 매칭)+앱 룰 3계층 반환. "
        "[발행 툴] publish_global_rule/publish_repo_rule/publish_app_rule(전체 본문), append_to_app_rule(덧붙이기). "
        "publish_global_skill_tool/publish_app_skill_tool/publish_repo_skill_tool 로 Skills 발행. "
        "publish_global_workflow_tool/publish_app_workflow_tool/publish_repo_workflow_tool 로 Workflows 발행. "
        "search_skills(query, app_name, scope, top_n) 로 스킬 벡터+FTS 하이브리드 검색. "
        "search_rules(query, app_name, scope, top_n) 로 룰 벡터+FTS 하이브리드 검색. "
        "get_global_workflow(app_name, origin_url) 로 워크플로우 로드. list_workflow_sections 로 카테고리 확인. "
        "search_workflows(query, app_name, scope, top_n) 로 워크플로우 키워드 검색. "
        "update_workflow(app_name, section_name, body) 로 앱 워크플로우 수정 (새 버전 발행). "
        "get_global_doc(app_name, origin_url) 로 일반 문서(Docs) 로드. list_doc_sections 로 카테고리 확인. "
        "search_docs(query, app_name, scope, top_n) 로 문서 벡터+FTS 하이브리드 검색. "
        "publish_global_doc_tool / publish_app_doc_tool / publish_repo_doc_tool 로 문서 발행. "
        "update_doc(app_name, section_name, body) 로 앱 문서 수정. "
        "Docs = 일반 문서(레퍼런스, 가이드, 메모 등 자유 형식). "

        "[권한] 인증이 활성화된 서버에서는 MCP 도구 호출 시 자동으로 권한이 검증된다. "
        "권한 에러('Permission denied') 발생 시 사용자에게 관리자 권한 요청을 안내한다. "

        "[하네스 문서 도구] MCPER 프로젝트 자체 문서(CLAUDE.md, 에이전트 가이드, 설계 문서 등)를 검색·조회할 때 사용. "
        "sync_harness_docs: 파일→DB 동기화. search_harness_docs: 하네스 문서 검색. "
        "get_harness_config: 특정 문서 전체 조회. list_harness_docs: 등록 문서 목록."
    ),
    json_response=True,
    streamable_http_path="/",
    # stateless_http=True: 로드밸런서 친화적이지만 일부 MCP 클라이언트(Claude Code 등)
    # 가 OAuth 통과 후 POST initialize 없이 GET SSE 만 열고 대기하는 문제.
    # False 로 전환해 stateful 세션(Mcp-Session-Id 헤더) 으로 전환 — 단일 프로세스라 문제없음.
    stateless_http=False,
    **_mcp_auth_kwargs,
)

register_document_tools(mcp)
register_rag_tools(mcp)
register_global_rule_tool(mcp)
register_skill_tools(mcp)
register_data_tools(mcp)
register_harness_tools(mcp)
register_workflow_tools(mcp)
register_doc_tools(mcp)
