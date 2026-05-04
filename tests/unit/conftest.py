"""Unit test 전용 conftest.

부모 `tests/conftest.py` 의 `setup_test_db` 는 세션 시작 시 실제 PostgreSQL 에
`Base.metadata.create_all` 을 호출해 모든 unit 테스트가 DB 의존을 갖게 된다.
단위 테스트는 MagicMock 기반이므로 DB 없이 실행 가능해야 한다.

여기서는:
  1. 부모 fixture 를 no-op 로 덮어써 DB 초기화를 막고
  2. `record_mcp_tool_call` (stats 집계) 을 세션 스코프에서 자동 mock 처리.
     이 함수는 모듈 전역 `SessionLocal()` 을 써서 개별 테스트의 patch 가
     잡지 못하고, 실제 DB 에 INSERT 시도하다 "relation does not exist" 로 실패.

실제 DB 가 필요한 테스트는 `tests/integration/` 으로 분리하는 것이 맞다.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_db(request):
    """tests/conftest.py 의 DB 초기화를 unit 스코프에서 no-op 로 덮어쓴다.

    단, `-m integration` 처럼 integration 마커가 선택된 실행이면 부모의
    `init_db` 로직이 필요하므로 우회하지 않고 직접 DB 초기화.
    """
    markexpr = request.config.getoption("-m") or ""
    if "integration" in markexpr and "not integration" not in markexpr:
        from app.db.database import Base, engine, init_db

        try:
            init_db()
        except Exception:
            Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _stub_record_mcp_tool_call():
    """모든 MCP 도구가 호출하는 stats 기록 함수를 no-op 로 교체.

    각 `app/tools/*.py` 가 `from app.services.mcp_tool_stats import record_mcp_tool_call`
    로 이름을 바인딩 → 해당 모듈 이름을 각각 패치해야 효과. 모듈이 아직
    import 되지 않았거나 이름이 없을 수 있으므로 실패는 무시.
    """
    targets = [
        "app.services.mcp_tool_stats.record_mcp_tool_call",
        "app.tools.documents.record_mcp_tool_call",
        "app.tools.rag_tools.record_mcp_tool_call",
        "app.tools.global_rules.record_mcp_tool_call",
        "app.tools.harness_tools.record_mcp_tool_call",
        "app.tools.workflow_tools.record_mcp_tool_call",
        "app.tools.skill_tools.record_mcp_tool_call",
        "app.tools.doc_tools.record_mcp_tool_call",
    ]
    patches = []
    for t in targets:
        try:
            p = patch(t, return_value=None)
            p.start()
            patches.append(p)
        except (AttributeError, ModuleNotFoundError):
            pass
    yield
    for p in patches:
        try:
            p.stop()
        except (AttributeError, RuntimeError):
            pass
