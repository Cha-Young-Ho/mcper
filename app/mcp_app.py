"""Shared FastMCP instance and tool registration."""

from mcp.server.fastmcp import FastMCP

from app.tools.global_rules import register_global_rule_tool
from app.tools.rag_tools import register_rag_tools
from app.tools.documents import register_document_tools
from app.tools.data_tools import register_data_tools

# Cursor는 URL 기반 MCP에 Streamable HTTP를 우선 사용한다.
# FastAPI에 ``Mount("/mcp", ...)`` 할 때 내부 라우트는 ``/`` 로 두는 게 일반적이다.
mcp = FastMCP(
    "Spec MCP Server",
    instructions=(
        "작업을 시작하기 전에 반드시 get_global_rule 도구를 호출해 워크스페이스 규칙을 로드하세요. "
        "check_rule_versions 로 서버의 최신 버전 번호(정수)를 받아 로컬 메타와 비교하고, 다르면 get_global_rule 로 다시 받아 로컬을 최신으로 맞출 것. "
        "조회 시에만 version 을 쓸 수 있음: 생략·null·latest 는 최신, 숫자는 해당 버전(없으면 서버가 최신으로 폴백). "
        "app_name 없으면 global 만; app_name 있으면 global 최신 + repository(URL 패턴) + 앱 룰 (version 은 앱 룰만). "
        "repository 매칭은 에이전트가 워크스페이스에서 git remote -v 실행 후 나온 origin fetch URL 을 origin_url 로 넘기는 것을 우선한다. "
        "repo_root 는 서버 Git 보조. "
        "Git 메타가 불확실하면 git remote -v 로 origin_url 을 채워 재호출하거나 사용자에게 물어보세요. "
        "INI의 app_name 식별자만 넘기세요(예: your_app_name). /master 등은 붙이지 마세요. "
        "룰 발행: publish_global_rule, publish_repo_rule, publish_app_rule(전체 본문), append_to_app_rule(최신 뒤에 덧붙여 새 버전). 버전은 서버가 자동 부여. "
        "MCP는 규칙 마크다운만 제공. 사용자가 룰을 받아와/조회해/동기화해 달라고 하면 get_global_rule 후 반드시 로컬 파일까지 저장(채팅만 출력 금지, 명시적 저장 거절 시만 예외). "
        "2차 응답 말미 [CRITICAL — …] 에 따라 Cursor/Claude/Antigravity/Gemini 등 환경별 경로·포맷으로 저장. Docker MCP는 호스트 클론 경로. "
        "서버 origin Unknown 이면 origin_url(에이전트가 git remote -v 로 얻은 값)로 재호출."
    ),
    json_response=True,
    streamable_http_path="/",
    stateless_http=True,
)

register_document_tools(mcp)
register_rag_tools(mcp)
register_global_rule_tool(mcp)
register_data_tools(mcp)
