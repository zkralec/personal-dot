import json
import logging
from datetime import UTC, datetime
from typing import Any
from personal_dot.diagnostics import error_class


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
            "execution_id",
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
            "notifications_attempted",
            "errors",
            "provider",
            "provider_request_id",
            "notification_status",
            "error_class",
        ):
            value = getattr(record, key, None)
            if value is not None:
                message[key] = value
        if record.exc_info:
            # Defense in depth for dependency tracebacks; never render bodies,
            # SQL statements, parameters, chained exceptions, or local values.
            message["error_class"] = error_class(record.exc_info[1])
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
