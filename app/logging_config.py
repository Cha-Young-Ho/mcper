"""Log format configuration: LOG_FORMAT=json (K8s/CloudWatch) or text (development default)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

# LOG_LEVEL=DEBUG 시에도 항상 WARNING 이상만 출력할 서드파티 로거.
# pdfminer는 파싱 중 수천 줄의 DEBUG를 쏟아내므로 반드시 억제.
_NOISY_LOGGERS: dict[str, int] = {
    "pdfminer":                logging.WARNING,
    "pdfminer.psparser":       logging.WARNING,
    "pdfminer.pdfinterp":      logging.WARNING,
    "pdfminer.cmapdb":         logging.WARNING,
    "pdfminer.pdfdocument":    logging.WARNING,
    "sqlalchemy.engine":       logging.WARNING,  # SQL 쿼리 로그는 명시 요청 시만
    "sqlalchemy.pool":         logging.WARNING,
    "sqlalchemy.dialects":     logging.WARNING,
    "watchfiles.main":         logging.INFO,
    "watchfiles":              logging.INFO,
    "multipart":               logging.INFO,
    "python_multipart":        logging.INFO,
    "httpx":                   logging.WARNING,
    "httpcore":                logging.WARNING,
    "sentence_transformers":   logging.WARNING,
    "transformers":            logging.WARNING,
    "torch":                   logging.WARNING,
    "PIL":                     logging.WARNING,
    "filelock":                logging.WARNING,
}


class JsonFormatter(logging.Formatter):
    """JSON logs for K8s / CloudWatch / Datadog compatibility."""

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
    LOG_FORMAT=json  → Structured JSON logs (K8s, corporate log aggregation recommended)
    LOG_FORMAT=text  → Human-readable text logs (development default)
    LOG_LEVEL=DEBUG|INFO|WARNING|ERROR

    서드파티 노이즈 로거는 _NOISY_LOGGERS에 정의된 레벨로 고정 억제.
    """
    log_format = os.environ.get("LOG_FORMAT", "text").lower()
    log_level  = os.environ.get("LOG_LEVEL", "INFO").upper()

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

    # 앱 레벨과 무관하게 서드파티 노이즈 고정 억제
    for logger_name, level in _NOISY_LOGGERS.items():
        logging.getLogger(logger_name).setLevel(level)
