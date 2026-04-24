"""Unit tests for mcp_tool_stats.record_mcp_tool_call — atomic upsert behavior.

현재 구현은 PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` 를 단일 statement 로 실행하므로
예전 "get → 분기 → add/increment" 흐름을 모킹하던 테스트는 의미가 없다. 이 테스트는
실제 동작인 "execute 한 번 + commit + close(finally)" 를 검증한다.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.mcp_tool_stats import record_mcp_tool_call


class TestRecordMcpToolCall:
    def test_executes_upsert_and_commits(self):
        mock_session = MagicMock()
        with patch("app.services.mcp_tool_stats.SessionLocal", return_value=mock_session):
            record_mcp_tool_call("some_tool")
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    def test_session_closed_even_when_commit_fails(self):
        mock_session = MagicMock()
        mock_session.commit.side_effect = RuntimeError("commit boom")
        with patch("app.services.mcp_tool_stats.SessionLocal", return_value=mock_session):
            # best-effort: must not raise
            record_mcp_tool_call("some_tool")
        mock_session.close.assert_called_once()

    def test_session_factory_failure_is_swallowed(self):
        with patch(
            "app.services.mcp_tool_stats.SessionLocal",
            side_effect=RuntimeError("cannot connect"),
        ):
            # must not raise
            record_mcp_tool_call("some_tool")

    def test_never_raises_on_execute_failure(self):
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("execute boom")
        with patch("app.services.mcp_tool_stats.SessionLocal", return_value=mock_session):
            record_mcp_tool_call("some_tool")
        # close still invoked in finally
        mock_session.close.assert_called_once()
