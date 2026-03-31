"""Shared FastMCP instance and tool registration."""

from mcp.server.fastmcp import FastMCP

from app.tools.global_rules import register_global_rule_tool
from app.tools.rag_tools import register_rag_tools
from app.tools.documents import register_document_tools
from app.tools.data_tools import register_data_tools
from app.tools.skill_tools import register_skill_tools

# Cursor는 URL 기반 MCP에 Streamable HTTP를 우선 사용한다.
# FastAPI에 ``Mount("/mcp", ...)`` 할 때 내부 라우트는 ``/`` 로 두는 게 일반적이다.
mcp = FastMCP(
    "Spec MCP Server",
    instructions=(
        "[필수 초기화 — 다른 도구보다 먼저 실행할 것] "
        "(1) 프로젝트 루트의 config.dev.ini 또는 config.ini 에서 [Global] > app_name 값을 읽는다. "
        "파일이 없으면 사용자에게 app_name 을 직접 물어본다. 폴더명·브랜치명으로 추측 금지. "
        "(2) get_global_rule(app_name='확인된_값', origin_url='git remote -v 의 origin URL') 호출 — 행동 지침 로드. "
        "(3) get_global_skill(app_name='확인된_값', origin_url='...') 호출 — 배경 지식 로드 및 SKILL FILE 블록을 지정 경로에 저장. "
        "(4) check_rule_versions 로 버전 비교, 로컬과 다르면 재호출해 최신으로 갱신. "
        "[행동 강령 적용] 로드된 Rules(행동 지침)은 코드 작성·리뷰·설계 시 항상 먼저 확인한다. "
        "✅/❌ 항목은 협의 없이 위반 불가. 위반 발견 시 사용자에게 명시적으로 알린다. "
        "Skills(배경 지식)는 시스템 구조·패턴 파악에 활용한다. 적용 우선순위: Rules 위반 확인 → Skills 맥락 파악 → 사용자 요청 수행. "
        "[저장 규칙] Cursor: .cursor/rules/mcp-rules.mdc. Claude Code: CLAUDE.md 또는 .claude/ 하위. "
        "응답 말미 [CRITICAL — ...] 지시에 따라 IDE별 경로에 저장. Docker MCP는 호스트 클론 경로. "
        "get_global_skill 응답의 SKILL FILE 블록은 .cursor/skills/ 하위 지정 경로에 각각 저장. "
        "[조회 옵션] version 생략·null·latest=최신, 숫자=해당 버전(없으면 최신 폴백). "
        "app_name 없으면 global 만; app_name 있으면 global+repository(URL 패턴 매칭)+앱 룰 3계층 반환. "
        "INI app_name 식별자만 사용(예: your_app_name). /master 등 접미사 금지. "
        "[발행 툴] publish_global_rule/publish_repo_rule/publish_app_rule(전체 본문), append_to_app_rule(덧붙이기). "
        "publish_global_skill_tool/publish_app_skill_tool/publish_repo_skill_tool 로 Skills 발행. "
        "[기획서 검색 도구 선택 기준] "
        "search_documents: 키워드·기능명으로 기획서를 찾을 때 (예: '결제 기획서 찾아줘'). "
        "find_historical_reference: 기획서 초안 본문을 가지고 있고 유사한 과거 기획을 비교하고 싶을 때. "
        "두 도구를 혼동하지 말 것. 사용자가 기획서를 '찾는' 요청이면 search_documents, "
        "'참고하려는' 새 기획서 텍스트가 있으면 find_historical_reference. "
        "[트리거 구문 — 사용자가 아래 중 하나를 말하면 즉시 초기화 절차(위 필수 초기화 1~4)를 실행할 것] "
        "트리거 목록(한국어·영어·혼용 모두 포함): "
        "'프로젝트 시작', '프로젝트 시작해', '프로젝트 시작하자', "
        "'project init', 'init project', 'project start', "
        "'이 프로젝트 정보 가져와', '이 프로젝트 정보 가져와줘', '프로젝트 정보 가져와', "
        "'이 프로젝트 룰 가져와', '이 프로젝트 룰 가져와줘', '프로젝트 룰 가져와', '룰 가져와', '룰 불러와', "
        "'이 프로젝트 스킬 가져와', '이 프로젝트 스킬 가져와줘', '스킬 가져와', "
        "'이 프로젝트 데이터 가져와', '이 프로젝트 데이터 가져와줘', '프로젝트 데이터 가져와', "
        "'규칙 가져와', '규칙 불러와', '규칙 로드', 'load rules', 'load skills', 'get rules', 'get skills'. "
        "트리거 감지 시 사용자에게 별도 확인 없이 바로 초기화 절차를 진행한다."
    ),
    json_response=True,
    streamable_http_path="/",
    stateless_http=True,
)

register_document_tools(mcp)
register_rag_tools(mcp)
register_global_rule_tool(mcp)
register_skill_tools(mcp)
register_data_tools(mcp)
