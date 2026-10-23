import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from personal_dot.agent_runtime import AgentPaused, get_agent_runtime
from personal_dot.agent_service import AgentExecutionError
from personal_dot.check_in import execute_check_in
from personal_dot.config import get_settings
from personal_dot.db import SessionLocal
from personal_dot.memory_service import get_memory_service
from personal_dot.models import Task, TaskStatus, TaskType
from personal_dot.notification_service import (
    NotificationError,
    TaskNotification,
    get_notification_service,
    should_notify,
)
from personal_dot.schemas import AgentTaskPayload

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskExecutionResult:
    result: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


def _perform(task: Task) -> TaskExecutionResult | AgentPaused:
    if task.type == TaskType.PROJECT_CHECK_IN:
        check_in = execute_check_in(task)
        return TaskExecutionResult(result=check_in.result, metadata=check_in.metadata)
    if task.type == TaskType.FAIL:
        raise RuntimeError("requested test failure")
    if task.type == TaskType.AGENT:
        payload = AgentTaskPayload.model_validate(task.payload)
        memory_context = None
        memory_metadata = None
        if task.agent_state is None and payload.memory is not None:
            retrieved = get_memory_service().retrieve(payload.memory)
            memory_context = retrieved.text
            memory_metadata = retrieved.metadata
        agent_result = get_agent_runtime().execute(
            task_id=task.id,
            payload=payload,
            state=task.agent_state,
            memory_context=memory_context,
            memory_metadata=memory_metadata,
        )
        if isinstance(agent_result, AgentPaused):
            return agent_result
        return TaskExecutionResult(
            result={"output": agent_result.output_text},
            metadata=agent_result.metadata,
        )
    return TaskExecutionResult(
        result={"echo": task.payload},
        metadata={"handler": "echo", "success": True},
    )


def _notify_terminal_task(task_id: uuid.UUID) -> None:
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        if task is None or not should_notify(task.notification_policy, task.status):
            return
        notification = TaskNotification(
            task_id=task.id,
            task_type=task.type,
            status=task.status,
        )
        policy = task.notification_policy.value

    attempted_at = datetime.now(UTC)
    provider_name = get_settings().notification_provider
    logger.info(
        "Task notification started",
        extra={
            "event": "notification_started",
            "task_id": str(task_id),
            "provider": provider_name,
        },
    )
    try:
        result = get_notification_service().send_task_notification(notification)
    except Exception as exc:
        safe_error = (
            f"{type(exc).__name__}: {exc}"
            if isinstance(exc, NotificationError)
            else f"{type(exc).__name__}: unexpected notification failure"
        )
        audit = {
            "policy": policy,
            "provider": provider_name,
            "status": "failed",
            "attempted_at": attempted_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "error": safe_error[:1000],
        }
        logger.warning(
            "Task notification failed",
            extra={
                "event": "notification_failed",
                "task_id": str(task_id),
                "provider": provider_name,
                "notification_status": "failed",
            },
            exc_info=isinstance(exc, NotificationError),
        )
    else:
        audit = {
            "policy": policy,
            "provider": result.provider,
            "status": "sent",
            "attempted_at": attempted_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "provider_request_id": result.provider_request_id,
        }
        logger.info(
            "Task notification sent",
            extra={
                "event": "notification_sent",
                "task_id": str(task_id),
                "provider": result.provider,
                "notification_status": "sent",
                "provider_request_id": result.provider_request_id,
            },
        )

    try:
        with SessionLocal() as session:
            task = session.scalar(
                select(Task).where(Task.id == task_id).with_for_update()
            )
            if task is None:
                return
            metadata = dict(task.execution_metadata or {})
            metadata["notification"] = audit
            task.execution_metadata = metadata
            session.commit()
    except Exception:
        logger.exception(
            "Task notification audit persistence failed",
            extra={
                "event": "notification_audit_failed",
                "task_id": str(task_id),
                "provider": provider_name,
            },
        )


def execute_task(task_id: str) -> dict[str, Any]:
    parsed_id = uuid.UUID(task_id)
    with SessionLocal() as session:
        task = session.scalar(
            select(Task).where(Task.id == parsed_id).with_for_update()
        )
        if task is None:
            raise LookupError(f"task {task_id} does not exist")
        if task.status != TaskStatus.QUEUED:
            logger.info(
                "Duplicate task delivery skipped",
                extra={
                    "event": "task_delivery_skipped",
                    "task_id": task_id,
                    "task_type": task.type.value,
                },
            )
            return task.result or {}
        task.status = TaskStatus.RUNNING
        if task.started_at is None:
            task.started_at = datetime.now(UTC)
        task.completed_at = None
        task.result = None
        task.error = None
        if task.agent_state is None:
            task.execution_metadata = {"handler": task.type.value, "success": None}
        session.commit()
        logger.info(
            "Task execution started",
            extra={"event": "task_started", "task_id": task_id},
        )

    try:
        result = _perform(task)
    except Exception as exc:
        with SessionLocal() as session:
            task = session.scalar(
                select(Task).where(Task.id == parsed_id).with_for_update()
            )
            if task is None:
                raise LookupError(f"task {task_id} does not exist") from exc
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now(UTC)
            task.result = None
            task.error = f"{type(exc).__name__}: {exc}"
            task.agent_state = None
            if isinstance(exc, AgentExecutionError):
                task.execution_metadata = exc.metadata
            else:
                task.execution_metadata = {
                    "handler": task.type.value,
                    "success": False,
                }
            session.commit()
            log_metadata = task.execution_metadata
        _notify_terminal_task(parsed_id)
        logger.exception(
            "Task execution failed",
            extra={
                "event": "task_failed",
                "task_id": task_id,
                "model": log_metadata.get("model"),
                "response_id": log_metadata.get("response_id"),
                "request_id": log_metadata.get("request_id"),
            },
        )
        raise

    if isinstance(result, AgentPaused):
        with SessionLocal() as session:
            task = session.scalar(
                select(Task).where(Task.id == parsed_id).with_for_update()
            )
            if task is None:
                raise LookupError(f"task {task_id} does not exist")
            task.status = TaskStatus.WAITING_FOR_APPROVAL
            task.agent_state = result.state
            task.execution_metadata = result.metadata
            task.completed_at = None
            session.commit()
        logger.info(
            "Task is waiting for tool approval",
            extra={"event": "task_waiting_for_approval", "task_id": task_id},
        )
        return {"status": TaskStatus.WAITING_FOR_APPROVAL.value}

    with SessionLocal() as session:
        task = session.scalar(
            select(Task).where(Task.id == parsed_id).with_for_update()
        )
        if task is None:
            raise LookupError(f"task {task_id} does not exist")
        task.status = TaskStatus.SUCCEEDED
        task.result = result.result
        task.execution_metadata = result.metadata
        task.agent_state = None
        task.completed_at = datetime.now(UTC)
        session.commit()
    _notify_terminal_task(parsed_id)
    logger.info(
        "Task execution succeeded",
        extra={"event": "task_succeeded", "task_id": task_id},
    )
    return result.result
