"""Bounded check-in notification retries; never dispatches model work.

Intent is committed with the terminal task. Claims expire after 120 seconds,
longer than the provider's maximum configured 60-second timeout. Provider
acceptance followed by a process crash may duplicate a push on retry.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_dot.db import SessionLocal
from personal_dot.models import NotificationDelivery, Task, TaskType
from personal_dot.notification_service import (
    NotificationService, TaskNotification, get_notification_service, should_notify,
)

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
CLAIM_SECONDS = 120


def ensure_notification(session: Session, task: Task, now: datetime) -> None:
    if task.type != TaskType.PROJECT_CHECK_IN or not should_notify(task.notification_policy, task.status):
        return
    if session.get(NotificationDelivery, task.id) is None:
        delivery = NotificationDelivery(task_id=task.id, next_attempt_at=now,
                                        status="pending", attempt_count=0, attempts=[])
        session.add(delivery)
        _audit(session, delivery)


def _audit(session: Session, delivery: NotificationDelivery) -> None:
    task = session.get(Task, delivery.task_id)
    assert task is not None
    metadata = dict(task.execution_metadata or {})
    last = delivery.attempts[-1] if delivery.attempts else {}
    metadata["notification"] = {
        **last, "status": last.get("status", "pending"),
        "delivery_status": delivery.status,
        "attempt_count": delivery.attempt_count,
        "next_attempt_at": delivery.next_attempt_at.isoformat(),
        "attempts": delivery.attempts,
    }
    task.execution_metadata = metadata


def deliver_notification(
    task_id: uuid.UUID,
    *,
    now: datetime | None = None,
    service_factory: Callable[[], NotificationService] | None = None,
) -> bool:
    current = now or datetime.now(UTC)
    with SessionLocal() as session, session.begin():
        delivery = session.scalar(select(NotificationDelivery).where(
            NotificationDelivery.task_id == task_id,
            NotificationDelivery.status.in_(["pending", "sending"]),
            NotificationDelivery.next_attempt_at <= current,
        ).with_for_update(skip_locked=True))
        if delivery is None:
            return False
        if delivery.status == "sending":
            attempts = list(delivery.attempts)
            attempts[-1] = {**attempts[-1], "status": "unknown", "error": "Notification attempt interrupted; provider acceptance unknown"}
            delivery.attempts = attempts
        if delivery.attempt_count >= MAX_ATTEMPTS:
            delivery.status = "exhausted"
            _audit(session, delivery)
            return False
        task = session.get(Task, task_id)
        assert task is not None
        notification = TaskNotification(task_id=task.id, task_type=task.type, status=task.status)
        token = uuid.uuid4()
        delivery.claim_token = token
        delivery.status = "sending"
        delivery.attempt_count += 1
        delivery.next_attempt_at = current + timedelta(seconds=CLAIM_SECONDS)
        delivery.attempts = [*delivery.attempts, {
            "status": "sending", "attempted_at": current.isoformat(),
        }]
        _audit(session, delivery)

    try:
        result = (service_factory or get_notification_service)().send_task_notification(notification)
    except Exception:
        # Never persist or log provider exception bodies.
        outcome = {"status": "failed", "error": "Notification delivery failed"}
    else:
        outcome = {"status": "sent", "provider": result.provider,
                   "provider_request_id": result.provider_request_id}

    with SessionLocal() as session, session.begin():
        delivery = session.scalar(select(NotificationDelivery).where(
            NotificationDelivery.task_id == task_id,
        ).with_for_update())
        assert delivery is not None
        if delivery.claim_token != token or delivery.status != "sending":
            return False
        attempts = list(delivery.attempts)
        attempts[-1] = {**attempts[-1], **outcome, "completed_at": (now or datetime.now(UTC)).isoformat()}
        delivery.attempts = attempts
        if outcome["status"] == "sent":
            delivery.status = "sent"
        elif delivery.attempt_count >= MAX_ATTEMPTS:
            delivery.status = "exhausted"
        else:
            delivery.status = "pending"
            delivery.next_attempt_at = current + timedelta(seconds=60 if delivery.attempt_count == 1 else 300)
        _audit(session, delivery)
    logger.info("Notification delivery attempt completed", extra={
        "event": "notification_delivery_attempt", "task_id": str(task_id),
        "notification_status": outcome["status"],
    })
    return True


def deliver_pending_notifications(now: datetime, limit: int) -> int:
    with SessionLocal() as session:
        ids = list(session.scalars(select(NotificationDelivery.task_id).where(
            NotificationDelivery.status.in_(["pending", "sending"]),
            NotificationDelivery.next_attempt_at <= now,
        ).order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.task_id).limit(limit)))
    return sum(deliver_notification(task_id, now=now) for task_id in ids)
