"""Fixed failure vocabulary. Exception messages/bodies are never diagnostics."""

from typing import Any

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError


def error_class(error: BaseException) -> str:
    if isinstance(error, SQLAlchemyError):
        return "database_error"
    if isinstance(error, (ConnectionError, RedisError)):
        return "queue_unavailable"
    if isinstance(error, TimeoutError):
        return "timeout"
    return "unexpected_error"


def queue_error(error: BaseException) -> str:
    return f"Queue delivery failed ({error_class(error)}); durable reconciliation will retry"


# Only application-authored literals may be retained, even for typed errors.
AGENT_MESSAGES = frozenset({
    "OPENAI_API_KEY is not configured for agent tasks",
    "OpenAI API request timed out", "OpenAI API connection failed",
    "OpenAI API request failed", "OpenAI API request rejected",
    "OpenAI response did not complete",
    "OpenAI response contained an unsupported output item",
    "OpenAI requested a tool when no tools were enabled",
    "OpenAI response completed without text output",
    "OpenAI returned an invalid tool call", "Agent tool-round limit exceeded",
    "Project check-in stored inputs are invalid",
    "Project check-in model request failed",
    "Project check-in returned an invalid result",
})


def agent_error_message(error: BaseException) -> str:
    message = str(error)
    return message if message in AGENT_MESSAGES else "Agent execution failed"


def failure_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Retain operational fields, never arbitrary exception diagnostic objects.

    check_in/memory are application-built provenance; provider bodies, headers,
    output items and exception payloads have no slot in this contract.
    """
    allowed = {
        "handler", "success", "provider", "model", "reasoning_effort",
        "output_verbosity", "model_started_at", "model_completed_at", "response_id",
        "request_id", "response_status", "request_outcome", "http_status_code",
        "tool_rounds", "check_in", "memory",
    }
    result = {key: value for key, value in metadata.items() if key in allowed}
    if isinstance(metadata.get("usage"), dict):
        result["usage"] = {
            key: value for key, value in metadata["usage"].items()
            if key in {"input_tokens", "output_tokens", "total_tokens",
                       "cached_input_tokens", "reasoning_tokens"}
            and type(value) is int and value >= 0
        }
    return result
