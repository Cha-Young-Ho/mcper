"""Unit tests for `app.worker.tasks` — Celery task 함수의 순수 로직.

Celery 브로커/워커/실제 DB 없이, 태스크 함수를 일반 callable 처럼 호출하되
SessionLocal/서비스 팩토리를 MagicMock 으로 대체. bind=True 이므로 self 로
쓰이는 task 인스턴스도 mock.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _call_bound(task, *args, retries: int = 0, **kwargs):
    """bind=True Celery task 를 테스트에서 직접 호출.

    `__wrapped__` 는 원본 함수지만 first arg (self) 자동 주입이 안 됨.
    원본 함수에 task 인스턴스를 첫 인자로 넘긴다. `self.retry` 는 side_effect
    설정된 MagicMock 으로 교체해 예외 발생을 검증 가능.
    """
    retry_mock = MagicMock(side_effect=RuntimeError("retry-invoked"))
    fake_self = SimpleNamespace(
        request=SimpleNamespace(id="task-123", retries=retries),
        max_retries=task.max_retries,
        retry=retry_mock,
    )
    # Celery `__wrapped__` 는 task 인스턴스에 bound method. `.__func__` 로
    # 원본 언바운드 함수를 얻어 임의 fake_self 로 호출한다.
    raw = task.__wrapped__.__func__
    return raw(fake_self, *args, **kwargs), fake_self, retry_mock


class TestIndexSpecTask:
    def test_missing_spec_returns_not_found(self):
        from app.worker.tasks import index_spec_task

        db = MagicMock()
        db.get.return_value = None
        with patch("app.worker.tasks.SessionLocal", return_value=db):
            result, _, _ = _call_bound(index_spec_task, 999)
        assert result["ok"] is False
        assert "not found" in result["error"]
        assert result["spec_id"] == 999

    def test_happy_path_delegates_to_service(self):
        from app.worker.tasks import index_spec_task

        spec = MagicMock(
            content="body",
            title="t",
            app_target="myapp",
            base_branch="main",
        )
        db = MagicMock()
        db.get.return_value = spec

        indexing_result = MagicMock(
            ok=True,
            spec_id=7,
            child_count=4,
            parent_count=2,
            error=None,
        )
        service = MagicMock()
        service.index.return_value = indexing_result

        with (
            patch("app.worker.tasks.SessionLocal", return_value=db),
            patch("app.spec.service.make_default_service", return_value=service),
        ):
            result, _, _ = _call_bound(index_spec_task, 7)

        assert result == {
            "ok": True,
            "spec_id": 7,
            "chunks": 4,
            "parents": 2,
            "error": None,
        }
        service.index.assert_called_once_with(
            spec_id=7,
            content="body",
            title="t",
            app_target="myapp",
            base_branch="main",
        )
        db.close.assert_called_once()

    def test_service_exception_triggers_retry(self):
        from app.worker.tasks import index_spec_task

        spec = MagicMock(
            content="body",
            title="t",
            app_target="app",
            base_branch="main",
        )
        db = MagicMock()
        db.get.return_value = spec
        service = MagicMock()
        service.index.side_effect = RuntimeError("embedding failed")

        with (
            patch("app.worker.tasks.SessionLocal", return_value=db),
            patch("app.spec.service.make_default_service", return_value=service),
            patch("app.worker.tasks.CeleryMonitoring.log_task_failure") as log_mock,
        ):
            with pytest.raises(RuntimeError, match="retry-invoked"):
                _call_bound(index_spec_task, 1)

        log_mock.assert_called_once()
        db.rollback.assert_called_once()

    def test_final_failure_returns_error_dict(self):
        """retries 가 max 에 도달하면 retry 대신 에러 dict 반환."""
        from app.worker.tasks import index_spec_task

        spec = MagicMock(
            content="body",
            title="t",
            app_target="app",
            base_branch="main",
        )
        db = MagicMock()
        db.get.return_value = spec
        service = MagicMock()
        service.index.side_effect = RuntimeError("boom")

        with (
            patch("app.worker.tasks.SessionLocal", return_value=db),
            patch("app.spec.service.make_default_service", return_value=service),
            patch("app.worker.tasks.CeleryMonitoring.log_task_failure"),
        ):
            result, _, retry_mock = _call_bound(index_spec_task, 5, retries=3)

        assert result["ok"] is False
        assert "boom" in result["error"]
        retry_mock.assert_not_called()


class TestTaskRegistration:
    """Celery task 등록 자체를 확인 — 이름/모듈 존재."""

    def test_index_spec_task_registered(self):
        from app.worker.tasks import index_spec_task

        assert index_spec_task.name == "index_spec"

    def test_parse_and_index_upload_registered(self):
        from app.worker.tasks import parse_and_index_upload_task

        assert parse_and_index_upload_task.name == "parse_and_index_upload"

    def test_index_code_batch_registered(self):
        from app.worker.tasks import index_code_batch_task

        assert index_code_batch_task.name == "index_code_batch"

    def test_max_retries_configured(self):
        from app.worker.tasks import (
            index_spec_task,
            parse_and_index_upload_task,
            index_code_batch_task,
        )

        assert index_spec_task.max_retries == 3
        assert parse_and_index_upload_task.max_retries == 3
        assert index_code_batch_task.max_retries == 3
