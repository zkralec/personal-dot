import json
import logging
from datetime import UTC, datetime
from typing import Any


class HealthAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not (
            record.name == "uvicorn.access"
            and '"GET /health HTTP/' in record.getMessage()
        )


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        message: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "event",
            "task_id",
            "task_type",
            "schedule_id",
            "scheduled_for",
            "status_code",
            "model",
            "response_id",
            "request_id",
            "input_tokens",
            "output_tokens",
            "tasks_created",
            "tasks_enqueued",
            "tasks_recovered",
            "errors",
            "provider",
            "provider_request_id",
            "notification_status",
        ):
            value = getattr(record, key, None)
            if value is not None:
                message[key] = value
        if record.exc_info:
            message["exception"] = self.formatException(record.exc_info)
        return json.dumps(message, default=str)


def configure_logging(service: str, level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    handler.addFilter(HealthAccessFilter())
    logging.basicConfig(
        level=level.upper(),
        handlers=[handler],
        force=True,
    )
