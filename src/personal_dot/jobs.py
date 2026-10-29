import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from personal_dot.agent_runtime import AgentPaused, get_agent_runtime
from personal_dot.agent_service import AgentExecutionError
from personal_dot.check_in import execute_check_in
from personal_dot.config import get_settings
from personal_dot.db import SessionLocal, engine
from personal_dot.diagnostics import agent_error_message, error_class, failure_metadata
from personal_dot.memory_service import get_memory_service
from personal_dot.documentation_preview import execute_documentation, seal_documentation_result
from personal_dot.documentation_errors import DocumentationError, MESSAGES as DOCUMENTATION_MESSAGES
from personal_dot.github import get_github_client
from personal_dot.github_errors import GitHubError, safe_code, safe_message
from personal_dot.repository_inspection import discover, inspect_repository
from personal_dot.models import Task, TaskStatus, TaskType
from personal_dot.notification_service import (
    TaskNotification,
    get_notification_service,
    should_notify,
)
from personal_dot.schemas import AgentTaskPayload
from personal_dot.notification_delivery import ensure_notification, deliver_notification

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskExecutionResult:
    result: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


def _perform(task: Task) -> TaskExecutionResult | AgentPaused:
    if task.type == TaskType.DOCUMENTATION_PREVIEW:
        result, metadata = execute_documentation(task)
        return TaskExecutionResult(result=result, metadata=metadata)
    if task.type in {TaskType.GITHUB_DISCOVER, TaskType.GITHUB_INSPECT}:
        with engine.connect() as connection, connection.begin():
            if task.type == TaskType.GITHUB_INSPECT and not connection.scalar(text(
                "SELECT pg_try_advisory_xact_lock(743201, 1)"
            )):
                raise GitHubError("overlap")
            client = get_github_client()
            try:
                snapshot = (discover(client, task.payload["page"]) if task.type == TaskType.GITHUB_DISCOVER
                            else inspect_repository(client, task.payload["repository"]))
                return TaskExecutionResult(result=snapshot, metadata={
                    "handler": task.type.value, "success": True, "provider": "github",
                    "github": {"policy_version": snapshot["policy_version"],
                               "repository_id": snapshot.get("repository", {}).get("id"),
                               "commit": snapshot.get("commit")},
                })
            finally:
                client.close()
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
        if task is None or task.type in {TaskType.GITHUB_DISCOVER, TaskType.GITHUB_INSPECT, TaskType.DOCUMENTATION_PREVIEW} or not should_notify(task.notification_policy, task.status):
            return
        if task.type == TaskType.PROJECT_CHECK_IN:
            deliver_notification(task_id, service_factory=get_notification_service)
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
    except Exception:
        audit = {
            "policy": policy,
            "provider": provider_name,
            "status": "failed",
            "attempted_at": attempted_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "error": "Notification delivery failed",
        }
        logger.warning(
            "Task notification failed",
            extra={
                "event": "notification_failed",
                "task_id": str(task_id),
                "provider": provider_name,
                "notification_status": "failed",
            },
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
        logger.error(
            "Task notification audit persistence failed",
            extra={
                "event": "notification_audit_failed",
                "task_id": str(task_id),
                "provider": provider_name,
            },
        )


def execute_task(task_id: str) -> dict[str, Any]:
    # RQ persists and logs escaped exceptions, including their tracebacks. Keep
    # raw provider/DB exceptions inside this boundary, including commit failures.
    try:
        return _execute_with_project_lock(task_id)
    except Exception as exc:
        classification = error_class(exc)
        logger.error("Task job failed", extra={
            "event": "task_job_failed", "task_id": task_id,
            "error_class": classification,
        })
    raise RuntimeError(f"Task job failed ({classification})") from None


def _execute_with_project_lock(task_id: str) -> dict[str, Any]:
    parsed_id = uuid.UUID(task_id)
    with SessionLocal() as session:
        task = session.get(Task, parsed_id)
        is_check_in = task is not None and task.type == TaskType.PROJECT_CHECK_IN
        if is_check_in:
            if task.status != TaskStatus.QUEUED:
                return task.result or {}
            project_id = task.payload.get("project_id", "")
    if not is_check_in:
        return _execute_task(task_id)

    # A transaction advisory lock spans the entire handler, across task commits.
    # Hash collisions can only conservatively skip work, never permit overlap.
    with engine.connect() as connection, connection.begin():
        acquired = connection.scalar(text(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(:project, 741923))"
        ), {"project": project_id})
        if acquired:
            return _execute_task(task_id)
        with SessionLocal() as session, session.begin():
            task = session.scalar(select(Task).where(Task.id == parsed_id).with_for_update())
            assert task is not None
            if task.status == TaskStatus.QUEUED:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now(UTC)
                task.error = "Project check-in skipped: another execution holds the project lock"
                task.execution_metadata = {**(task.execution_metadata or {}),
                    "handler": "project_check_in", "success": False,
                    "execution_outcome": "skipped_overlap"}
                ensure_notification(session, task, task.completed_at)
        return {}


def _owns_execution(task: Task, execution_id: uuid.UUID) -> bool:
    # Call only after locking the current database row, never on a handler snapshot.
    owns = task.status == TaskStatus.RUNNING and task.execution_id == execution_id
    if not owns:
        logger.info("Obsolete task execution write skipped", extra={
            "event": "task_execution_write_skipped", "task_id": str(task.id),
            "execution_id": str(execution_id),
        })
    return owns


def _execute_task(task_id: str) -> dict[str, Any]:
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
        execution_id = uuid.uuid4()
        task.execution_id = execution_id
        # Approval wait time and previous executions are not active runtime.
        task.started_at = datetime.now(UTC)
        task.execution_metadata = dict(task.execution_metadata or {})
        task.execution_metadata.pop("waiting_for_approval", None)
        task.completed_at = None
        task.result = None
        task.error = None
        if task.agent_state is None:
            task.execution_metadata = {**task.execution_metadata, "handler": task.type.value, "success": None}
        schedule_metadata = {"schedule": task.execution_metadata["schedule"]} if "schedule" in task.execution_metadata else {}
        session.commit()
        logger.info(
            "Task execution started",
            extra={"event": "task_started", "task_id": task_id,
                   "execution_id": str(execution_id)},
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
            if not _owns_execution(task, execution_id):
                return task.result or {}
            task.execution_id = None
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now(UTC)
            task.result = None
            task.error = (
                "AgentExecutionError: " + agent_error_message(exc)
                if isinstance(exc, AgentExecutionError)
                else f"Task execution failed ({error_class(exc)})"
            )
            if isinstance(exc, DocumentationError):
                task.error = DOCUMENTATION_MESSAGES.get(exc.code, DOCUMENTATION_MESSAGES['input_invalid'])
                task.result = exc.result
            if isinstance(exc, GitHubError):
                task.error = safe_message(exc)
            task.agent_state = None
            if isinstance(exc, AgentExecutionError):
                task.execution_metadata = failure_metadata(exc.metadata)
            else:
                task.execution_metadata = {
                    "handler": task.type.value,
                    "success": False,
                }
            if isinstance(exc, DocumentationError):
                task.execution_metadata = exc.metadata
                if exc.metadata.get("request_outcome") == "unknown":
                    task.status = TaskStatus.UNCERTAIN
            if isinstance(exc, GitHubError):
                task.execution_metadata["github"] = {"error_code": safe_code(exc)}
            task.execution_metadata = {**schedule_metadata, **task.execution_metadata}
            task.execution_metadata.pop("waiting_for_approval", None)
            if task.type == TaskType.PROJECT_CHECK_IN and task.execution_metadata.get("request_outcome") == "unknown":
                task.status = TaskStatus.UNCERTAIN
                task.error = "Project check-in request interrupted; provider outcome unknown; automatic execution retry disabled"
                task.execution_metadata["execution_outcome"] = "unknown"
            ensure_notification(session, task, task.completed_at)
            session.commit()
            log_metadata = task.execution_metadata
        _notify_terminal_task(parsed_id)
        logger.error(
            "Task execution failed",
            extra={
                "event": "task_failed",
                "task_id": task_id,
                "execution_id": str(execution_id),
                "model": log_metadata.get("model"),
                "response_id": log_metadata.get("response_id"),
                "request_id": log_metadata.get("request_id"),
                "error_class": error_class(exc),
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
            if not _owns_execution(task, execution_id):
                return task.result or {}
            task.execution_id = None
            task.status = TaskStatus.WAITING_FOR_APPROVAL
            task.agent_state = result.state
            task.execution_metadata = result.metadata
            task.completed_at = None
            session.commit()
        logger.info(
            "Task is waiting for tool approval",
            extra={"event": "task_waiting_for_approval", "task_id": task_id,
                   "execution_id": str(execution_id)},
        )
        return {"status": TaskStatus.WAITING_FOR_APPROVAL.value}

    with SessionLocal() as session:
        task = session.scalar(
            select(Task).where(Task.id == parsed_id).with_for_update()
        )
        if task is None:
            raise LookupError(f"task {task_id} does not exist")
        if not _owns_execution(task, execution_id):
            return task.result or {}
        task.execution_id = None
        task.status = TaskStatus.SUCCEEDED
        task.result = (seal_documentation_result(session, task, result.result)
                       if task.type == TaskType.DOCUMENTATION_PREVIEW else result.result)
        task.execution_metadata = {**schedule_metadata, **result.metadata}
        task.execution_metadata.pop("waiting_for_approval", None)
        if task.type == TaskType.DOCUMENTATION_PREVIEW:
            task.execution_metadata["success"] = True
            task.execution_metadata["documentation_preview"]["stage"] = task.result['stage']
        task.agent_state = None
        task.completed_at = datetime.now(UTC)
        ensure_notification(session, task, task.completed_at)
        session.commit()
    _notify_terminal_task(parsed_id)
    logger.info(
        "Task execution succeeded",
        extra={"event": "task_succeeded", "task_id": task_id,
               "execution_id": str(execution_id)},
    )
    return result.result
