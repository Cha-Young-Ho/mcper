"""Unit tests for mcp_tool_stats: record_mcp_tool_call atomic upsert behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from app.db.mcp_tool_stats import McpToolCallStat
from app.services.mcp_tool_stats import record_mcp_tool_call


class TestRecordMcpToolCallNewEntry:
    """새 tool_name 첫 호출 시 call_count=1 행이 생성되어야 한다."""

    def test_new_tool_creates_row_with_call_count_one(self):
        """신규 tool_name으로 호출하면 call_count=1 인 행이 DB에 추가된다."""
        mock_session = MagicMock()
        mock_session.get.return_value = None  # 해당 tool_name 없음

        with patch("app.services.mcp_tool_stats.SessionLocal", return_value=mock_session):
            record_mcp_tool_call("new_tool")

        # db.get 이 McpToolCallStat, "new_tool" 로 호출됐는지 확인
        mock_session.get.assert_called_once_with(McpToolCallStat, "new_tool")

        # db.add 로 call_count=1 인 객체가 추가됐는지 확인
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert isinstance(added_obj, McpToolCallStat)
        assert added_obj.tool_name == "new_tool"
        assert added_obj.call_count == 1

        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    def test_new_tool_does_not_increment_missing_row(self):
        """get()이 None 반환 시 row.call_count 접근 없이 새 행만 추가한다."""
        mock_session = MagicMock()
        mock_session.get.return_value = None

        with patch("app.services.mcp_tool_stats.SessionLocal", return_value=mock_session):
            record_mcp_tool_call("another_tool")

        # add 는 1번, commit 은 1번
        assert mock_session.add.call_count == 1
        assert mock_session.commit.call_count == 1


class TestRecordMcpToolCallIncrement:
    """기존 tool_name 재호출 시 call_count 가 1 증가해야 한다."""

    def test_existing_tool_increments_call_count(self):
        """동일 tool_name 두 번째 호출 시 call_count 가 이전 값 +1 이 된다."""
        existing_row = McpToolCallStat(tool_name="existing_tool", call_count=1)
        mock_session = MagicMock()
        mock_session.get.return_value = existing_row

        with patch("app.services.mcp_tool_stats.SessionLocal", return_value=mock_session):
            record_mcp_tool_call("existing_tool")

        # add 는 호출되지 않아야 함 (새 행 추가 없음)
        mock_session.add.assert_not_called()
        # call_count 가 2 로 증가했는지 확인
        assert existing_row.call_count == 2
        mock_session.commit.assert_called_once()

    def test_two_consecutive_calls_result_in_call_count_two(self):
        """동일 tool_name 으로 두 번 연속 호출하면 최종 call_count 는 2 이다."""
        # 첫 번째 호출: 행 없음 → 생성
        mock_session_1 = MagicMock()
        mock_session_1.get.return_value = None

        with patch("app.services.mcp_tool_stats.SessionLocal", return_value=mock_session_1):
            record_mcp_tool_call("double_call_tool")

        added_obj = mock_session_1.add.call_args[0][0]
        assert added_obj.call_count == 1

        # 두 번째 호출: 기존 행 있음 → call_count 증가
        existing_row = McpToolCallStat(tool_name="double_call_tool", call_count=1)
        mock_session_2 = MagicMock()
        mock_session_2.get.return_value = existing_row

        with patch("app.services.mcp_tool_stats.SessionLocal", return_value=mock_session_2):
            record_mcp_tool_call("double_call_tool")

        assert existing_row.call_count == 2
        mock_session_2.commit.assert_called_once()

    def test_high_call_count_increments_correctly(self):
        """call_count 가 큰 숫자여도 +1 이 올바르게 동작한다."""
        existing_row = McpToolCallStat(tool_name="heavy_tool", call_count=9999)
        mock_session = MagicMock()
        mock_session.get.return_value = existing_row

        with patch("app.services.mcp_tool_stats.SessionLocal", return_value=mock_session):
            record_mcp_tool_call("heavy_tool")

        assert existing_row.call_count == 10000


class TestRecordMcpToolCallErrorHandling:
    """예외 발생 시 호출자에게 예외가 전파되지 않아야 한다 (best-effort)."""

    def test_db_error_does_not_raise(self):
        """SessionLocal 생성 실패 시 예외가 전파되지 않는다."""
        with patch(
            "app.services.mcp_tool_stats.SessionLocal",
            side_effect=Exception("DB connection failed"),
        ):
            # 예외 없이 조용히 실패해야 함
            record_mcp_tool_call("any_tool")

    def test_commit_error_does_not_raise(self):
        """commit() 실패 시에도 예외가 전파되지 않는다."""
        mock_session = MagicMock()
        mock_session.get.return_value = None
        mock_session.commit.side_effect = Exception("commit failed")

        with patch("app.services.mcp_tool_stats.SessionLocal", return_value=mock_session):
            record_mcp_tool_call("any_tool")

        # close 는 finally 블록이므로 반드시 호출돼야 함
        mock_session.close.assert_called_once()

    def test_session_always_closed_on_success(self):
        """정상 동작 시에도 session.close() 가 반드시 호출된다."""
        mock_session = MagicMock()
        mock_session.get.return_value = None

        with patch("app.services.mcp_tool_stats.SessionLocal", return_value=mock_session):
            record_mcp_tool_call("cleanup_test_tool")

        mock_session.close.assert_called_once()
