import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_dot.db import get_db
from personal_dot.check_in import CheckInInputError, prepare_check_in
from personal_dot.models import MaintenanceControl, Schedule, ScheduleType, Task, TaskType
from personal_dot.schedule_calculations import (
    as_utc,
    next_cron_occurrence,
    next_occurrence_after,
)
from personal_dot.schemas import (
    ScheduleCreate,
    ScheduleRead,
    ScheduleUpdate,
    TaskRead,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def _validate_check_in_inputs(task_type: TaskType, payload: dict, db: Session) -> None:
    if task_type != TaskType.PROJECT_CHECK_IN:
        return
    try:
        prepare_check_in(payload, db)
    except CheckInInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=503, detail="project check-in inputs could not be prepared") from None


def _initial_next_run(request: ScheduleCreate, now: datetime) -> datetime:
    if request.schedule_type == ScheduleType.ONCE:
        assert request.run_at is not None
        next_run = as_utc(request.run_at)
    elif request.schedule_type == ScheduleType.INTERVAL:
        assert request.interval_seconds is not None
        next_run = (
            as_utc(request.start_at)
            if request.start_at is not None
            else now + timedelta(seconds=request.interval_seconds)
        )
    else:
        assert request.cron_expression is not None
        next_run = next_cron_occurrence(
            request.cron_expression, request.timezone, now
        )

    if next_run <= now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="the first scheduled run must be in the future",
        )
    return next_run


@router.post("", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
def create_schedule(request: ScheduleCreate, db: DatabaseSession) -> Schedule:
    if request.task.type == TaskType.DOCUMENTATION_MAINTENANCE:
        raise HTTPException(409, "Configure the single daily maintenance schedule through /maintenance/configuration")
    _validate_check_in_inputs(request.task.type, request.task.payload, db)
    now = datetime.now(UTC)
    next_run = _initial_next_run(request, now)
    schedule = Schedule(
        name=request.name,
        schedule_type=request.schedule_type,
        task_type=request.task.type,
        payload=request.task.payload,
        notification_policy=request.task.notification_policy,
        enabled=request.enabled,
        one_time_at=next_run if request.schedule_type == ScheduleType.ONCE else None,
        interval_seconds=request.interval_seconds,
        cron_expression=request.cron_expression,
        timezone=request.timezone,
        next_run_at=next_run,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.get("", response_model=list[ScheduleRead])
def list_schedules(
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Schedule]:
    statement = (
        select(Schedule)
        .order_by(Schedule.created_at.desc(), Schedule.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement))


@router.get("/{schedule_id}", response_model=ScheduleRead)
def get_schedule(schedule_id: uuid.UUID, db: DatabaseSession) -> Schedule:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="schedule not found"
        )
    return schedule


@router.patch("/{schedule_id}", response_model=ScheduleRead)
def update_schedule(
    schedule_id: uuid.UUID, request: ScheduleUpdate, db: DatabaseSession
) -> Schedule:
    observed = db.get(Schedule, schedule_id)
    if observed is not None and observed.task_type == TaskType.DOCUMENTATION_MAINTENANCE:
        # Match /maintenance's control -> schedule lock order.
        db.scalar(select(MaintenanceControl).where(MaintenanceControl.id == 1).with_for_update())
    schedule = db.scalar(
        select(Schedule).where(Schedule.id == schedule_id).with_for_update()
    )
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="schedule not found"
        )

    if schedule.task_type == TaskType.DOCUMENTATION_MAINTENANCE:
        from personal_dot.maintenance_routes import require_activation
        control = db.scalar(select(MaintenanceControl).where(MaintenanceControl.id == 1).with_for_update())
        if control is None or control.schedule_id != schedule.id:
            raise HTTPException(409, "Maintenance control is missing")
        if request.enabled:
            require_activation(db, control)
        control.paused = not request.enabled
        if not request.enabled:
            control.discovery = {**control.discovery, 'pause_generation': control.discovery.get('pause_generation', 0) + 1}
    if request.enabled and not schedule.enabled:
        _validate_check_in_inputs(schedule.task_type, schedule.payload, db)
        if schedule.next_run_at is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="an exhausted one-time schedule cannot be re-enabled",
            )
        if schedule.schedule_type != ScheduleType.ONCE:
            schedule.next_run_at = next_occurrence_after(
                schedule, datetime.now(UTC)
            )
        schedule.last_error = None
    schedule.enabled = request.enabled
    db.commit()
    db.refresh(schedule)
    return schedule


@router.get("/{schedule_id}/tasks", response_model=list[TaskRead])
def list_schedule_tasks(
    schedule_id: uuid.UUID,
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Task]:
    if db.get(Schedule, schedule_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="schedule not found"
        )
    statement = (
        select(Task)
        .where(Task.schedule_id == schedule_id)
        .order_by(Task.scheduled_for.desc(), Task.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement))
