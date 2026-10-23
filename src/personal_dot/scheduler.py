import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select

from personal_dot.config import Settings, get_settings
from personal_dot.db import SessionLocal
from personal_dot.models import Schedule, Task, TaskStatus
from personal_dot.schedule_calculations import as_utc, next_occurrence
from personal_dot.structured_logging import configure_logging
from personal_dot.task_dispatch import enqueue_task

logger = logging.getLogger(__name__)


@dataclass
class SchedulerStats:
    tasks_created: int = 0
    tasks_enqueued: int = 0
    tasks_recovered: int = 0
    errors: int = 0


class SchedulerService:
    def __init__(
        self,
        settings: Settings | None = None,
        session_factory: Any = SessionLocal,
        enqueue_func: Callable[[uuid.UUID | str], None] = enqueue_task,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory
        self.enqueue_func = enqueue_func
        self.stale_task_seconds = max(
            self.settings.scheduler_stale_task_seconds,
            self.settings.rq_job_timeout_seconds
            + self.settings.scheduler_requeue_after_seconds,
        )
        if self.stale_task_seconds != self.settings.scheduler_stale_task_seconds:
            logger.warning(
                "Stale-task threshold raised above the RQ job timeout",
                extra={"event": "scheduler_stale_threshold_adjusted"},
            )

    def run_once(self, now: datetime | None = None) -> SchedulerStats:
        current = as_utc(now or datetime.now(UTC))
        stats = SchedulerStats()
        for schedule_id in self._due_schedule_ids(current):
            for _ in range(self.settings.scheduler_max_catch_up):
                try:
                    materialized = self._materialize_occurrence(
                        schedule_id, current
                    )
                except Exception as exc:
                    stats.errors += 1
                    self._record_schedule_error(schedule_id, exc)
                    logger.exception(
                        "Schedule materialization failed",
                        extra={
                            "event": "schedule_failed",
                            "schedule_id": str(schedule_id),
                        },
                    )
                    break
                if materialized is None:
                    break
                task_id, created = materialized
                if created:
                    stats.tasks_created += 1
                logger.info(
                    "Schedule occurrence persisted",
                    extra={
                        "event": "schedule_materialized",
                        "schedule_id": str(schedule_id),
                        "task_id": str(task_id),
                    },
                )

        stats.tasks_recovered += self._recover_stale_tasks(current)
        enqueued, enqueue_errors = self._dispatch_pending_tasks(current)
        stats.tasks_enqueued += enqueued
        stats.errors += enqueue_errors
        return stats

    def _due_schedule_ids(self, now: datetime) -> list[uuid.UUID]:
        with self.session_factory() as session:
            statement = (
                select(Schedule.id)
                .where(
                    Schedule.enabled.is_(True),
                    Schedule.next_run_at.is_not(None),
                    Schedule.next_run_at <= now,
                )
                .order_by(Schedule.next_run_at, Schedule.id)
                .limit(self.settings.scheduler_batch_size)
            )
            return list(session.scalars(statement))

    def _materialize_occurrence(
        self, schedule_id: uuid.UUID, now: datetime
    ) -> tuple[uuid.UUID, bool] | None:
        with self.session_factory() as session, session.begin():
            schedule = session.scalar(
                select(Schedule)
                .where(
                    Schedule.id == schedule_id,
                    Schedule.enabled.is_(True),
                    Schedule.next_run_at.is_not(None),
                    Schedule.next_run_at <= now,
                )
                .with_for_update(skip_locked=True)
            )
            if schedule is None or schedule.next_run_at is None:
                return None

            occurrence = as_utc(schedule.next_run_at)
            task = session.scalar(
                select(Task).where(
                    Task.schedule_id == schedule.id,
                    Task.scheduled_for == occurrence,
                )
            )
            created = task is None
            if task is None:
                task = Task(
                    type=schedule.task_type,
                    status=TaskStatus.QUEUED,
                    payload=dict(schedule.payload),
                    notification_policy=schedule.notification_policy,
                    schedule_id=schedule.id,
                    scheduled_for=occurrence,
                )
                session.add(task)
                session.flush()

            schedule.last_run_at = occurrence
            schedule.next_run_at = next_occurrence(schedule, occurrence)
            schedule.last_error = None
            if schedule.next_run_at is None:
                schedule.enabled = False
            return task.id, created

    def _record_schedule_error(
        self, schedule_id: uuid.UUID, error: Exception
    ) -> None:
        safe_error = f"{type(error).__name__}: {error}"[:2000]
        with self.session_factory() as session, session.begin():
            schedule = session.get(Schedule, schedule_id)
            if schedule is not None:
                schedule.last_error = safe_error

    def _recover_stale_tasks(self, now: datetime) -> int:
        cutoff = now - timedelta(seconds=self.stale_task_seconds)
        with self.session_factory() as session:
            task_ids = list(
                session.scalars(
                    select(Task.id)
                    .where(
                        Task.status == TaskStatus.RUNNING,
                        Task.started_at.is_not(None),
                        Task.started_at <= cutoff,
                    )
                    .order_by(Task.started_at, Task.id)
                    .limit(self.settings.scheduler_batch_size)
                )
            )

        recovered = 0
        for task_id in task_ids:
            with self.session_factory() as session, session.begin():
                task = session.scalar(
                    select(Task)
                    .where(
                        Task.id == task_id,
                        Task.status == TaskStatus.RUNNING,
                        Task.started_at <= cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
                if task is None:
                    continue
                task.status = TaskStatus.QUEUED
                task.started_at = None
                task.completed_at = None
                task.result = None
                task.error = None
                task.enqueue_attempted_at = None
                task.enqueue_error = None
                task.execution_metadata = {
                    "handler": task.type.value,
                    "recovered_from_stale_run": True,
                }
                recovered += 1
                logger.warning(
                    "Stale task recovered",
                    extra={
                        "event": "task_recovered",
                        "task_id": str(task.id),
                        "schedule_id": str(task.schedule_id),
                    },
                )
        return recovered

    def _dispatch_pending_tasks(self, now: datetime) -> tuple[int, int]:
        retry_before = now - timedelta(
            seconds=self.settings.scheduler_requeue_after_seconds
        )
        with self.session_factory() as session:
            task_ids = list(
                session.scalars(
                    select(Task.id)
                    .where(
                        Task.status == TaskStatus.QUEUED,
                        or_(
                            Task.enqueue_attempted_at.is_(None),
                            Task.enqueue_attempted_at <= retry_before,
                        ),
                    )
                    .order_by(Task.created_at, Task.id)
                    .limit(self.settings.scheduler_batch_size)
                )
            )

        enqueued = 0
        errors = 0
        for task_id in task_ids:
            if not self._claim_enqueue_attempt(task_id, now, retry_before):
                continue
            try:
                self.enqueue_func(task_id)
            except Exception as exc:
                errors += 1
                self._record_enqueue_error(task_id, exc)
                logger.exception(
                    "Task enqueue retry failed",
                    extra={"event": "task_enqueue_retry_failed", "task_id": str(task_id)},
                )
                continue
            enqueued += 1
            logger.info(
                "Task enqueued by durable reconciliation",
                extra={"event": "task_reconciled_to_queue", "task_id": str(task_id)},
            )
        return enqueued, errors

    def _claim_enqueue_attempt(
        self, task_id: uuid.UUID, now: datetime, retry_before: datetime
    ) -> bool:
        with self.session_factory() as session, session.begin():
            task = session.scalar(
                select(Task)
                .where(
                    Task.id == task_id,
                    Task.status == TaskStatus.QUEUED,
                    or_(
                        Task.enqueue_attempted_at.is_(None),
                        Task.enqueue_attempted_at <= retry_before,
                    ),
                )
                .with_for_update(skip_locked=True)
            )
            if task is None:
                return False
            task.enqueue_attempted_at = now
            task.enqueue_error = None
            return True

    def _record_enqueue_error(self, task_id: uuid.UUID, error: Exception) -> None:
        safe_error = f"{type(error).__name__}: {error}"[:2000]
        with self.session_factory() as session, session.begin():
            task = session.get(Task, task_id)
            if task is not None and task.status == TaskStatus.QUEUED:
                task.enqueue_error = safe_error


def main() -> None:
    settings = get_settings()
    configure_logging("scheduler", settings.log_level)
    scheduler = SchedulerService(settings=settings)
    logger.info(
        "Scheduler started",
        extra={"event": "scheduler_started"},
    )
    while True:
        started = time.monotonic()
        try:
            stats = scheduler.run_once()
            if any(
                (
                    stats.tasks_created,
                    stats.tasks_enqueued,
                    stats.tasks_recovered,
                    stats.errors,
                )
            ):
                logger.info(
                    "Scheduler poll completed",
                    extra={
                        "event": "scheduler_poll",
                        "tasks_created": stats.tasks_created,
                        "tasks_enqueued": stats.tasks_enqueued,
                        "tasks_recovered": stats.tasks_recovered,
                        "errors": stats.errors,
                    },
                )
        except Exception:
            logger.exception(
                "Scheduler poll failed",
                extra={"event": "scheduler_poll_failed"},
            )
        elapsed = time.monotonic() - started
        time.sleep(max(0.1, settings.scheduler_poll_seconds - elapsed))


if __name__ == "__main__":
    main()
