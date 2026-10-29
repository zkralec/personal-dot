import logging
from personal_dot.diagnostics import queue_error
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_dot.db import get_db
from personal_dot.models import (
    ApprovalRequest,
    ApprovalStatus,
    Task,
    TaskStatus,
    ToolCall,
    ToolCallStatus,
)
from personal_dot.schemas import (
    ApprovalDecision,
    ApprovalRead,
    ToolCallRead,
    ToolDefinitionRead,
)
from personal_dot.task_dispatch import enqueue_task
from personal_dot.tool_registry import get_tool_registry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tools"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("/tools", response_model=list[ToolDefinitionRead])
def list_tools() -> list[ToolDefinitionRead]:
    return [
        ToolDefinitionRead(
            name=definition.name,
            description=definition.description,
            input_schema=definition.input_schema,
            risk=definition.risk,
            automatic_execution_allowed=definition.automatic_execution_allowed,
            requires_approval=definition.requires_approval,
        )
        for definition in get_tool_registry().definitions()
    ]


@router.get("/tasks/{task_id}/tool-calls", response_model=list[ToolCallRead])
def list_task_tool_calls(
    task_id: uuid.UUID, db: DatabaseSession
) -> list[ToolCall]:
    if db.get(Task, task_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return list(
        db.scalars(
            select(ToolCall)
            .where(ToolCall.task_id == task_id)
            .order_by(ToolCall.requested_at, ToolCall.id)
        )
    )


@router.get("/approvals", response_model=list[ApprovalRead])
def list_approvals(
    db: DatabaseSession,
    approval_status: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[ApprovalRequest]:
    statement = select(ApprovalRequest)
    if approval_status is not None:
        statement = statement.where(ApprovalRequest.status == approval_status)
    statement = statement.order_by(
        ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc()
    ).limit(limit)
    return list(db.scalars(statement))


@router.get("/approvals/{approval_id}", response_model=ApprovalRead)
def get_approval(
    approval_id: uuid.UUID, db: DatabaseSession
) -> ApprovalRequest:
    approval = db.get(ApprovalRequest, approval_id)
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="approval request not found"
        )
    return approval


def _decide_approval(
    approval_id: uuid.UUID,
    decision: Literal["approved", "denied"],
    request: ApprovalDecision,
    db: Session,
) -> ApprovalRequest:
    approval = db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .with_for_update()
    )
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="approval request not found"
        )
    desired = (
        ApprovalStatus.APPROVED
        if decision == "approved"
        else ApprovalStatus.DENIED
    )
    if approval.status not in (ApprovalStatus.PENDING, desired):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"approval request is already {approval.status.value}",
        )

    task = db.scalar(
        select(Task).where(Task.id == approval.task_id).with_for_update()
    )
    call = db.scalar(
        select(ToolCall)
        .where(ToolCall.id == approval.tool_call_id)
        .with_for_update()
    )
    if task is None or call is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="approval request has incomplete audit state",
        )
    if (
        approval.status == ApprovalStatus.PENDING
        and task.status != TaskStatus.WAITING_FOR_APPROVAL
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="task has not reached its durable approval wait state; retry",
        )

    if approval.status == ApprovalStatus.PENDING:
        now = datetime.now(UTC)
        approval.status = desired
        approval.decided_at = now
        approval.decision_reason = request.reason
        call.approval_status = desired
        if desired == ApprovalStatus.DENIED:
            call.status = ToolCallStatus.DENIED
            call.error = "user denied this tool call"
            call.completed_at = now

    pending_count = db.scalar(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(
            ApprovalRequest.task_id == task.id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
        )
    )
    should_enqueue = False
    if pending_count == 0 and task.status == TaskStatus.WAITING_FOR_APPROVAL:
        task.status = TaskStatus.QUEUED
        should_enqueue = True
    elif pending_count == 0 and task.status == TaskStatus.QUEUED:
        should_enqueue = True
    if should_enqueue:
        task.enqueue_attempted_at = datetime.now(UTC)
        task.enqueue_error = None
    db.commit()

    logger.info(
        "Tool approval decided",
        extra={
            "event": "tool_approval_decided",
            "task_id": str(task.id),
            "tool_call_id": str(call.id),
            "approval_id": str(approval.id),
            "approval_status": desired.value,
        },
    )
    if should_enqueue:
        try:
            enqueue_task(task.id)
        except Exception as exc:
            task.enqueue_error = queue_error(exc)
            db.commit()
            logger.error(
                "Approved task could not be requeued; durable reconciliation will retry",
                extra={
                    "event": "approval_requeue_failed",
                    "task_id": str(task.id),
                    "approval_id": str(approval.id),
                },
            )
            db.refresh(approval)
            return approval
    db.refresh(approval)
    return approval


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalRead)
def approve_tool_call(
    approval_id: uuid.UUID,
    request: ApprovalDecision,
    db: DatabaseSession,
) -> ApprovalRequest:
    return _decide_approval(approval_id, "approved", request, db)


@router.post("/approvals/{approval_id}/deny", response_model=ApprovalRead)
def deny_tool_call(
    approval_id: uuid.UUID,
    request: ApprovalDecision,
    db: DatabaseSession,
) -> ApprovalRequest:
    return _decide_approval(approval_id, "denied", request, db)
