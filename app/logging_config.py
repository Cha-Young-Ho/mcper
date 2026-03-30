"""로그 포맷 설정: LOG_FORMAT=json (K8s/CloudWatch) 또는 text (개발 기본값)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """K8s / CloudWatch / Datadog 친화적 JSON 로그."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        return json.dumps(log_data, ensure_ascii=False)


def configure_logging() -> None:
    """
    LOG_FORMAT=json  → JSON 구조화 로그 (K8s, 사내 로그 수집 권장)
    LOG_FORMAT=text  → 사람이 읽기 좋은 텍스트 로그 (개발 기본값)
    LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
    """
    log_format = os.environ.get("LOG_FORMAT", "text").lower()
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
