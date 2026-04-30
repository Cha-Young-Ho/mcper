"""Unit test 전용 conftest.

부모 `tests/conftest.py` 의 `setup_test_db` 는 세션 시작 시 실제 PostgreSQL 에
`Base.metadata.create_all` 을 호출해 모든 unit 테스트가 DB 의존을 갖게 된다.
단위 테스트는 MagicMock 기반이므로 DB 없이 실행 가능해야 한다. 여기서는
부모 fixture 를 no-op 로 덮어써 unit 디렉터리 안의 테스트가 DB 없이도
독립 실행 가능하도록 한다. 실제 DB 가 필요한 테스트는 `tests/integration` 또는
`@pytest.mark.integration` 경로로 유도.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """tests/conftest.py 의 DB 초기화를 unit 스코프에서 no-op 로 덮어쓴다."""
    yield
